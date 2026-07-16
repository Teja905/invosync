using System.Diagnostics;
using System.Text;

namespace InvoSync.TallyConnector.Services;

using static AppPaths;

public class DiagnosticReporter
{
    private readonly IHttpClientFactory _httpFactory;
    private readonly CompanyGuard _companyGuard;
    private readonly QueueManager _queue;
    private readonly OfflineQueue _offlineQueue;
    private readonly ConnectorLogger _logger;
    private readonly RecentPushStore _recentPushes;
    private readonly ILogger<DiagnosticReporter> _log;
    private static readonly PerformanceCounter? _cpuCounter;
    private static readonly DateTime _processStart = Process.GetCurrentProcess().StartTime;

    static DiagnosticReporter()
    {
        try
        {
            _cpuCounter = new PerformanceCounter("Process", "% Processor Time", Process.GetCurrentProcess().ProcessName, true);
            _cpuCounter.NextValue(); // warm-up
        }
        catch
        {
            _cpuCounter = null;
        }
    }

    public DiagnosticReporter(IHttpClientFactory httpFactory, CompanyGuard companyGuard,
        QueueManager queue, OfflineQueue offlineQueue, ConnectorLogger logger,
        RecentPushStore recentPushes,
        ILogger<DiagnosticReporter> log)
    {
        _httpFactory = httpFactory;
        _companyGuard = companyGuard;
        _queue = queue;
        _offlineQueue = offlineQueue;
        _logger = logger;
        _recentPushes = recentPushes;
        _log = log;
    }

    public async Task<string> GenerateReportAsync()
    {
        var report = new StringBuilder();
        report.AppendLine("=== InvoSync Connector Diagnostic Report ===");
        report.AppendLine($"Generated: {DateTime.Now:yyyy-MM-dd HH:mm:ss}");
        report.AppendLine($"Connector Version: 1.0.0");
        report.AppendLine();

        report.AppendLine("--- System ---");
        report.AppendLine($"OS: {Environment.OSVersion}");
        report.AppendLine($".NET: {Environment.Version}");
        report.AppendLine($"Machine: {Environment.MachineName}");
        report.AppendLine($"Process: {Environment.ProcessPath}");
        report.AppendLine($"Process uptime: {(DateTime.Now - _processStart).ToString(@"d\.hh\:mm\:ss")}");

        // CPU & RAM
        try
        {
            var proc = Process.GetCurrentProcess();
            if (_cpuCounter != null)
            {
                var cpuPct = _cpuCounter.NextValue();
                report.AppendLine($"CPU (process): {cpuPct:F1}%");
            }
            var ws = proc.WorkingSet64;
            var priv = proc.PrivateMemorySize64;
            report.AppendLine($"RAM working set: {ws / 1024 / 1024} MB");
            report.AppendLine($"RAM private: {priv / 1024 / 1024} MB");
            report.AppendLine($"Threads: {proc.Threads.Count}");
            report.AppendLine($"Handles: {proc.HandleCount}");
        }
        catch (Exception ex)
        {
            report.AppendLine($"Resource info unavailable: {ex.Message}");
        }

        // Disk
        try
        {
            var drive = new DriveInfo(Path.GetPathRoot(BaseDir) ?? "C:\\");
            report.AppendLine($"Disk ({drive.Name}): {drive.TotalFreeSpace / 1024 / 1024 / 1024} GB free / {drive.TotalSize / 1024 / 1024 / 1024} GB total");
        }
        catch { }

        // App data directory sizes
        try
        {
            var dataSize = Directory.GetFiles(DataDir, "*", SearchOption.AllDirectories).Sum(f => new FileInfo(f).Length);
            var logSize = Directory.GetFiles(LogDir, "*", SearchOption.AllDirectories).Sum(f => new FileInfo(f).Length);
            report.AppendLine($"AppData/data: {dataSize / 1024} KB");
            report.AppendLine($"AppData/logs: {logSize / 1024} KB");
        }
        catch { }

        report.AppendLine();

        report.AppendLine("--- Tally Status ---");
        var health = await _companyGuard.CheckHealthAsync();
        report.AppendLine($"Running: {health.IsRunning}");
        report.AppendLine($"Company: {health.ActiveCompany}");
        report.AppendLine($"Version: {health.Version}");
        if (!string.IsNullOrEmpty(health.Error))
            report.AppendLine($"Error: {health.Error}");
        report.AppendLine();

        report.AppendLine("--- Session ---");
        // Sanitize — never write full token in reports
        report.AppendLine("Logged in: (sanitized — see logs)");
        report.AppendLine();

        report.AppendLine("--- Queue Status ---");
        report.AppendLine($"In-memory pending: {_queue.Pending}");
        report.AppendLine($"In-memory dead letter: {_queue.DeadLetterCount}");
        report.AppendLine($"Offline DB pending: {_offlineQueue.GetPendingCount()}");
        report.AppendLine($"Offline DB dead letter: {_offlineQueue.GetDeadLetterCount()}");
        report.AppendLine();

        // Push latency from RecentPushStore
        report.AppendLine("--- Push Performance ---");
        try
        {
            var recent = _recentPushes.GetRecent(50);
            var successes = recent.Where(r => r.Success).ToList();
            var failures = recent.Where(r => !r.Success).ToList();
            report.AppendLine($"Today pushed: {_recentPushes.TodayPushCount}");
            report.AppendLine($"Today failed: {_recentPushes.TodayFailCount}");
            if (successes.Count > 0)
            {
                var avgMs = successes.Average(r => r.DurationMs);
                var maxMs = successes.Max(r => r.DurationMs);
                var minMs = successes.Min(r => r.DurationMs);
                report.AppendLine($"Last {successes.Count} pushes — avg: {avgMs:F0}ms, min: {minMs}ms, max: {maxMs}ms");
            }
            report.AppendLine($"Recent pushes with version info: {recent.Count(r => !string.IsNullOrEmpty(r.ConnectorVersion))}");
        }
        catch (Exception ex)
        {
            report.AppendLine($"Push stats unavailable: {ex.Message}");
        }
        report.AppendLine();

        report.AppendLine("--- Backend Ping ---");
        try
        {
            var invosync = _httpFactory.CreateClient("InvoSync");
            var ping = await invosync.GetAsync("/health");
            report.AppendLine($"Status: {(ping.IsSuccessStatusCode ? "OK" : $"FAIL ({ping.StatusCode})")}");
        }
        catch (Exception ex)
        {
            report.AppendLine($"Status: FAIL — {ex.Message}");
        }
        report.AppendLine();

        report.AppendLine("--- Recent Logs (last 30) ---");
        if (File.Exists(_logger.TodayLogPath))
        {
            var lines = File.ReadAllLines(_logger.TodayLogPath);
            foreach (var line in lines.TakeLast(30))
                report.AppendLine(line);
        }
        else
        {
            report.AppendLine("(no logs yet today)");
        }

        var path = DiagnosticReportPath();
        File.WriteAllText(path, report.ToString());
        _log.LogInformation("Diagnostic report saved to {Path}", path);
        return path;
    }
}
