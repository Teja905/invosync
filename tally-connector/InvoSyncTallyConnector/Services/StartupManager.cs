using Microsoft.Win32;

namespace InvoSync.TallyConnector.Services;

public enum StartupResult
{
    Success,
    RegistryAccessDenied,
    UnknownError,
}

public static class StartupManager
{
    private const string AppName = "InvoSyncConnector";
    private static readonly ILogger _log = LoggerFactory.Create(b => b.AddConsole()).CreateLogger("StartupManager");

    public static StartupResult EnableStartWithWindows()
    {
        try
        {
            using var key = Registry.CurrentUser.OpenSubKey(
                @"SOFTWARE\Microsoft\Windows\CurrentVersion\Run", writable: true);
            if (key == null)
                return StartupResult.RegistryAccessDenied;
            key.SetValue(AppName, $"\"{Application.ExecutablePath}\" --minimized");
            return StartupResult.Success;
        }
        catch (UnauthorizedAccessException)
        {
            return StartupResult.RegistryAccessDenied;
        }
        catch (Exception ex)
        {
            _log.LogError("Startup registration failed: {Msg}", ex.Message);
            return StartupResult.UnknownError;
        }
    }

    public static void DisableStartWithWindows()
    {
        try
        {
            using var key = Registry.CurrentUser.OpenSubKey(
                @"SOFTWARE\Microsoft\Windows\CurrentVersion\Run", writable: true);
            key?.DeleteValue(AppName, throwOnMissingValue: false);
        }
        catch { }
    }

    public static bool IsStartupEnabled()
    {
        try
        {
            using var key = Registry.CurrentUser.OpenSubKey(
                @"SOFTWARE\Microsoft\Windows\CurrentVersion\Run");
            return key?.GetValue(AppName) != null;
        }
        catch { return false; }
    }
}
