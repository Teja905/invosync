namespace InvoSync.TallyConnector.Services;

public class ConnectorLogger
{
    private readonly string _logDir;
    private readonly ILogger<ConnectorLogger> _log;

    public string TodayLogPath { get; }
    public LogLevel MinimumLevel { get; set; } = LogLevel.Info;

    public ConnectorLogger(ILogger<ConnectorLogger> log)
    {
        _log = log;
        _logDir = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "logs");
        Directory.CreateDirectory(_logDir);
        TodayLogPath = Path.Combine(_logDir, $"connector_{DateTime.Now:yyyy-MM-dd}.log");
        CleanOldLogs();
    }

    public void Debug(string message) => Write(LogLevel.Debug, "DEBUG", message);
    public void Info(string message) => Write(LogLevel.Info, "INFO", message);
    public void Warning(string message) => Write(LogLevel.Warning, "WARN", message);
    public void Error(string message, Exception? ex = null)
    {
        Write(LogLevel.Error, "ERROR", message);
        if (ex != null) Write(LogLevel.Error, "ERROR", $"Exception: {ex}");
    }

    public void TallyPush(string invoiceId, bool success, string? error = null)
    {
        var status = success ? "SUCCESS" : "FAILED";
        Write(LogLevel.Info, "TALLY", $"Invoice {invoiceId}: {status}{(error != null ? $" | {error}" : "")}");
    }

    private void Write(LogLevel level, string prefix, string message)
    {
        if (level < MinimumLevel) return;
        var line = $"{DateTime.Now:HH:mm:ss.fff} [{prefix}] {message}";
        try { File.AppendAllText(TodayLogPath, line + Environment.NewLine); }
        catch { }
        _log.LogInformation("{Msg}", line);
    }

    public (int Pushed, int Failed) GetTodayStats()
    {
        if (!File.Exists(TodayLogPath)) return (0, 0);
        var lines = File.ReadAllLines(TodayLogPath);
        return (lines.Count(l => l.Contains("[TALLY]") && l.Contains("SUCCESS")),
                lines.Count(l => l.Contains("[TALLY]") && l.Contains("FAILED")));
    }

    private void CleanOldLogs()
    {
        try
        {
            var cutoff = DateTime.Now.AddDays(-30);
            foreach (var f in Directory.GetFiles(_logDir, "connector_*.log"))
                if (File.GetCreationTime(f) < cutoff) File.Delete(f);
        }
        catch { }
    }
}

public enum LogLevel { Debug, Info, Warning, Error }
