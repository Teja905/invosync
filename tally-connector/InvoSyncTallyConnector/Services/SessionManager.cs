using System.Net.Http.Json;
using System.Text;
using System.Text.Json;
using System.Security.Cryptography;
using System.IO;

namespace InvoSync.TallyConnector.Services;

public class Session
{
    public string Token { get; set; } = "";
    public string RefreshToken { get; set; } = "";
    public string UserEmail { get; set; } = "";
    public DateTime ExpiresAt { get; set; } = DateTime.MinValue;
}

public class SessionManager
{
    private readonly string _sessionDir;
    private readonly string _sessionFile;
    private readonly IHttpClientFactory _httpFactory;
    private readonly ILogger<SessionManager> _log;
    private Session? _session;

    public SessionManager(IHttpClientFactory httpFactory, ILogger<SessionManager> log)
    {
        _httpFactory = httpFactory;
        _log = log;
        _sessionDir = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
            "InvoSync");
        _sessionFile = Path.Combine(_sessionDir, "session.json");
        Directory.CreateDirectory(_sessionDir);
        _session = LoadFromDisk();
    }

    public bool IsLoggedIn => _session != null && !string.IsNullOrEmpty(_session.Token);

    public async Task<bool> EnsureValidSessionAsync()
    {
        if (_session == null || string.IsNullOrEmpty(_session.Token))
            return false;

        if (_session.ExpiresAt > DateTime.UtcNow.AddMinutes(5))
            return true;

        try
        {
            var client = _httpFactory.CreateClient("InvoSync");
            var resp = await client.GetAsync($"/api/auth/validate?token={_session.Token}");
            if (resp.IsSuccessStatusCode)
            {
                _session.ExpiresAt = DateTime.UtcNow.AddHours(24);
                SaveToDisk();
                return true;
            }

            if (!string.IsNullOrEmpty(_session.RefreshToken))
            {
                var refreshed = await TryRefreshAsync();
                if (refreshed != null) return true;
            }

            _log.LogWarning("Session expired — user must re-login");
            return false;
        }
        catch (HttpRequestException)
        {
            _log.LogDebug("Cannot reach server — using cached session");
            return _session.ExpiresAt > DateTime.UtcNow;
        }
    }

    public async Task<Session?> TryRefreshAsync()
    {
        try
        {
            var client = _httpFactory.CreateClient("InvoSync");
            var payload = JsonContent.Create(new { refresh_token = _session!.RefreshToken });
            var resp = await client.PostAsync("/api/auth/refresh", payload);
            if (!resp.IsSuccessStatusCode) return null;

            var json = await resp.Content.ReadAsStringAsync();
            var newSession = JsonSerializer.Deserialize<Session>(json);
            if (newSession == null) return null;

            _session = newSession;
            SaveToDisk();
            return _session;
        }
        catch (Exception ex)
        {
            _log.LogDebug("Token refresh failed: {Msg}", ex.Message);
            return null;
        }
    }

    public void SaveSession(string token, string refreshToken, string email)
    {
        _session = new Session
        {
            Token = token,
            RefreshToken = refreshToken,
            UserEmail = email,
            ExpiresAt = DateTime.UtcNow.AddHours(24),
        };
        SaveToDisk();
    }

    public void Logout()
    {
        _session = null;
        try { if (File.Exists(_sessionFile)) File.Delete(_sessionFile); }
        catch { }
    }

    private void SaveToDisk()
    {
        try
        {
            var json = JsonSerializer.Serialize(_session);
            var encrypted = Protect(Encoding.UTF8.GetBytes(json));
            File.WriteAllText(_sessionFile, Convert.ToBase64String(encrypted));
        }
        catch (Exception ex)
        {
            _log.LogError("Failed to save session: {Msg}", ex.Message);
        }
    }

    private Session? LoadFromDisk()
    {
        try
        {
            if (!File.Exists(_sessionFile)) return null;
            var encrypted = Convert.FromBase64String(File.ReadAllText(_sessionFile));
            var json = Encoding.UTF8.GetString(Unprotect(encrypted));
            var session = JsonSerializer.Deserialize<Session>(json);
            if (session == null || string.IsNullOrEmpty(session.Token) || string.IsNullOrEmpty(session.UserEmail))
            {
                _log.LogWarning("Session file corrupt — clearing");
                BackupCorruptSession();
                Logout();
                return null;
            }
            return session;
        }
        catch (JsonException ex)
        {
            _log.LogWarning("Session file unreadable: {Msg}. Clearing.", ex.Message);
            BackupCorruptSession();
            Logout();
            return null;
        }
    }

    private static byte[] Protect(byte[] data)
    {
        return ProtectedData.Protect(data, null, DataProtectionScope.CurrentUser);
    }

    private static byte[] Unprotect(byte[] encrypted)
    {
        return ProtectedData.Unprotect(encrypted, null, DataProtectionScope.CurrentUser);
    }

    private void BackupCorruptSession()
    {
        try
        {
            if (!File.Exists(_sessionFile)) return;
            var backup = _sessionFile + $".corrupt.{DateTime.Now:yyyyMMddHHmmss}";
            File.Copy(_sessionFile, backup);
            _log.LogInformation("Corrupt session backed up to {Backup}", backup);
        }
        catch { }
    }
}
