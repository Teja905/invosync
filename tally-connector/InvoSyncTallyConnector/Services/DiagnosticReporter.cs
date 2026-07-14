using System.Text;

namespace InvoSync.TallyConnector.Services;

public class DiagnosticReporter
{
    private readonly IHttpClientFactory _httpFactory;
    private readonly CompanyGuard _companyGuard;
    private readonly QueueManager _queue;
    private readonly OfflineQueue _offlineQueue;
    private readonly ConnectorLogger _logger;
    private readonly ILogger<DiagnosticReporter> _log;

    public DiagnosticReporter(IHttpClientFactory httpFactory, CompanyGuard companyGuard,
        QueueManager queue, OfflineQueue offlineQueue, ConnectorLogger logger,
        ILogger<DiagnosticReporter> log)
    {
        _httpFactory = httpFactory;
        _companyGuard = companyGuard;
        _queue = queue;
        _offlineQueue = offlineQueue;
        _logger = logger;
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

        var path = Path.Combine(AppDomain.CurrentDomain.BaseDirectory,
            $"diagnostic_{DateTime.Now:yyyyMMdd_HHmmss}.txt");
        File.WriteAllText(path, report.ToString());
        _log.LogInformation("Diagnostic report saved to {Path}", path);
        return path;
    }
}
