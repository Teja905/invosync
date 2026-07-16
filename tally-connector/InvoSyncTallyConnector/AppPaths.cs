namespace InvoSync.TallyConnector;

public static class AppPaths
{
    static AppPaths()
    {
        BaseDir = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
            "InvoSync");

        DataDir = Path.Combine(BaseDir, "data");
        LogDir = Path.Combine(BaseDir, "logs");
        CrashDir = Path.Combine(BaseDir, "crash");
        ReportDir = Path.Combine(BaseDir, "reports");
        BackupDir = Path.Combine(BaseDir, "backups");
        CacheDir = Path.Combine(BaseDir, "cache");

        foreach (var dir in new[] { DataDir, LogDir, CrashDir, ReportDir, BackupDir, CacheDir })
            Directory.CreateDirectory(dir);
    }

    public static string BaseDir { get; }
    public static string DataDir { get; }
    public static string LogDir { get; }
    public static string CrashDir { get; }
    public static string ReportDir { get; }
    public static string BackupDir { get; }
    public static string CacheDir { get; }

    public static string OfflineQueueDb => Path.Combine(DataDir, "offline_queue.db");
    public static string DailyCountersFile => Path.Combine(DataDir, "daily_counters.json");
    public static string SessionFile => Path.Combine(DataDir, "session.json");
    public static string CrashLogFile => Path.Combine(CrashDir, "connector-crash.log");
    public static string TodayLogPath(DateTime? date = null)
    {
        var d = date ?? DateTime.Now;
        return Path.Combine(LogDir, $"connector_{d:yyyy-MM-dd}.log");
    }
    public static string DiagnosticReportPath(DateTime? date = null)
    {
        var d = date ?? DateTime.Now;
        return Path.Combine(ReportDir, $"diagnostic_{d:yyyyMMdd_HHmmss}.txt");
    }
}
