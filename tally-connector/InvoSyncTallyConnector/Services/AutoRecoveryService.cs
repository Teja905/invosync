namespace InvoSync.TallyConnector.Services;

public class AutoRecoveryService
{
    private readonly CompanyGuard _companyGuard;
    private readonly ILogger<AutoRecoveryService> _log;
    private System.Threading.Timer? _timer;
    private bool _wasConnected;
    private ConnectionState _connectionState = ConnectionState.Disconnected;
    public event EventHandler? Reconnected;

    public bool IsConnected { get; private set; }

    public AutoRecoveryService(CompanyGuard companyGuard, ILogger<AutoRecoveryService> log)
    {
        _companyGuard = companyGuard;
        _log = log;
    }

    public void Start()
    {
        var interval = GetPollInterval();
        _timer = new System.Threading.Timer(async _ => await CheckAsync(), null, TimeSpan.FromSeconds(15), interval);
    }

    public void Stop() => _timer?.Dispose();

    private TimeSpan GetPollInterval()
    {
        return _connectionState switch
        {
            ConnectionState.Connected => TimeSpan.FromSeconds(30),
            ConnectionState.Reconnecting => TimeSpan.FromSeconds(10),
            ConnectionState.Disconnected => TimeSpan.FromSeconds(5),
            _ => TimeSpan.FromSeconds(30),
        };
    }

    private async Task CheckAsync()
    {
        try
        {
            var health = await _companyGuard.CheckHealthAsync();
            var nowConnected = health.IsRunning;

            if (nowConnected && !_wasConnected)
            {
                _log.LogInformation("Tally detected — auto-recovering");
                IsConnected = true;
                _connectionState = ConnectionState.Connected;
                Reconnected?.Invoke(this, EventArgs.Empty);
                _wasConnected = true;

                // Update timer interval for connected state
                _timer?.Change(GetPollInterval(), GetPollInterval());
            }
            else if (!nowConnected)
            {
                _wasConnected = false;
                IsConnected = false;
                _connectionState = ConnectionState.Disconnected;

                // Poll more frequently when disconnected
                _timer?.Change(GetPollInterval(), GetPollInterval());
            }
        }
        catch (Exception ex)
        {
            _log.LogDebug("Recovery check failed: {Msg}", ex.Message);
            IsConnected = false;
        }
    }
}
