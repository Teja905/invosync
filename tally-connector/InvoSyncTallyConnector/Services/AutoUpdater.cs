using System.Diagnostics;
using System.Text.Json;

namespace InvoSync.TallyConnector.Services;

using System.Security.Cryptography;

public class VersionInfo
{
    public string LatestVersion { get; set; } = "1.0.0";
    public string DownloadUrl { get; set; } = "";
    public string ReleaseNotes { get; set; } = "";
    public string Sha256 { get; set; } = "";
}

public class AutoUpdater
{
    private const string CurrentVersion = "1.0.0";
    private readonly ILogger<AutoUpdater> _log;

    public AutoUpdater(ILogger<AutoUpdater> log)
    {
        _log = log;
    }

    public async Task<VersionInfo?> CheckForUpdatesAsync()
    {
        try
        {
            using var client = new HttpClient { Timeout = TimeSpan.FromSeconds(10) };
            var resp = await client.GetAsync("https://invosync-backend-yjfa.onrender.com/api/connector/version");
            if (!resp.IsSuccessStatusCode) return null;

            var json = await resp.Content.ReadAsStringAsync();
            var info = JsonSerializer.Deserialize<VersionInfo>(json);
            if (info == null) return null;

            if (IsNewer(info.LatestVersion, CurrentVersion))
            {
                _log.LogInformation("Update available: v{Latest}", info.LatestVersion);
                return info;
            }
        }
        catch (Exception ex)
        {
            _log.LogDebug("Update check failed: {Msg}", ex.Message);
        }
        return null;
    }

    public async Task<string?> DownloadUpdateAsync(string downloadUrl, string? expectedHash = null)
    {
        try
        {
            var tempPath = Path.GetTempFileName() + ".exe";
            using var client = new HttpClient { Timeout = TimeSpan.FromMinutes(5) };
            var bytes = await client.GetByteArrayAsync(downloadUrl);
            await File.WriteAllBytesAsync(tempPath, bytes);

            if (!string.IsNullOrEmpty(expectedHash))
            {
                if (!await VerifyDownloadHash(tempPath, expectedHash))
                {
                    File.Delete(tempPath);
                    _log.LogError("Download corrupted — hash mismatch");
                    return null;
                }
            }

            _log.LogInformation("Update downloaded to {Path}", tempPath);
            return tempPath;
        }
        catch (Exception ex)
        {
            _log.LogError("Download failed: {Msg}", ex.Message);
            return null;
        }
    }

    private static async Task<bool> VerifyDownloadHash(string filePath, string expectedHash)
    {
        try
        {
            using var sha256 = SHA256.Create();
            using var stream = File.OpenRead(filePath);
            var hash = Convert.ToHexString(await sha256.ComputeHashAsync(stream));
            return hash.Equals(expectedHash, StringComparison.OrdinalIgnoreCase);
        }
        catch
        {
            return false;
        }
    }

    public void ApplyUpdateAndRestart(string newExePath)
    {
        var batchPath = Path.GetTempFileName() + ".bat";
        var currentExe = Application.ExecutablePath;

        File.WriteAllText(batchPath,
$@"@echo off
timeout /t 2 /nobreak > nul
copy /y ""{newExePath}"" ""{currentExe}""
start """" ""{currentExe}""
del ""{batchPath}""
");

        Process.Start(new ProcessStartInfo
        {
            FileName = batchPath,
            WindowStyle = ProcessWindowStyle.Hidden
        });
        Application.Exit();
    }

    private static bool IsNewer(string latest, string current)
    {
        return Version.TryParse(latest, out var lv)
            && Version.TryParse(current, out var cv)
            && lv > cv;
    }
}
