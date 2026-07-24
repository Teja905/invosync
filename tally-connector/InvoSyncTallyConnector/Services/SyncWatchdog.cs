namespace InvoSync.TallyConnector.Services;

public class SyncWatchdog
{
    private readonly ILogger<SyncWatchdog> _log;
    private DateTime _lastActivity = DateTime.UtcNow;
    private System.Threading.Timer? _timer;
    private CancellationTokenSource? _cts;
    private readonly SemaphoreSlim _syncLock = new(1, 1);
    public event EventHandler? SyncRestarted;

    public bool IsStuck { get; private set; }

    public SyncWatchdog(ILogger<SyncWatchdog> log)
    {
        _log = log;
    }

    public void Start(CancellationTokenSource cts)
    {
        _cts = cts;
        _timer = new System.Threading.Timer(Check, null, TimeSpan.FromSeconds(30), TimeSpan.FromSeconds(30));
    }

    public void Stop() => _timer?.Dispose();

    public void RecordActivity() => _lastActivity = DateTime.UtcNow;

    public async Task<bool> TryStartAsync()
    {
        if (!await _syncLock.WaitAsync(0))
        {
            _log.LogInformation("Sync already in progress. Skipping.");
            return false;
        }
        RecordActivity();
        return true;
    }

    public void CompleteSync()
    {
        RecordActivity();
        _syncLock.Release();
    }

    private void Check(object? state)
    {
        var elapsed = DateTime.UtcNow - _lastActivity;
        if (elapsed <= TimeSpan.FromMinutes(2)) return;

        _log.LogWarning("Sync stuck for {Sec:F0}s — auto-recovering", elapsed.TotalSeconds);
        IsStuck = true;
        _cts?.Cancel();

        SyncRestarted?.Invoke(this, EventArgs.Empty);
        _lastActivity = DateTime.UtcNow;
        IsStuck = false;
    }
}
