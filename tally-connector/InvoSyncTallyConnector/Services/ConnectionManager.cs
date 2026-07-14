namespace InvoSync.TallyConnector.Services;

public enum ConnectionState
{
    Disconnected,
    Connecting,
    Connected,
    Reconnecting,
}

public class ConnectionManager
{
    private readonly IHttpClientFactory _httpFactory;
    private readonly ILogger<ConnectionManager> _log;
    private int _retryCount;
    private static readonly int[] BackoffSeconds = { 1, 2, 4, 8, 16, 32, 60, 120, 300 };
    private DateTime _connectedSince;

    public ConnectionState State { get; private set; } = ConnectionState.Disconnected;
    public event EventHandler<ConnectionState>? StateChanged;

    public TimeSpan ConnectionUptime =>
        State == ConnectionState.Connected ? DateTime.Now - _connectedSince : TimeSpan.Zero;

    public ConnectionManager(IHttpClientFactory httpFactory, ILogger<ConnectionManager> log)
    {
        _httpFactory = httpFactory;
        _log = log;
    }

    private static int GetBackoffWithJitter(int attempt)
    {
        var baseSeconds = attempt < BackoffSeconds.Length
            ? BackoffSeconds[attempt]
            : 300;
        var jitter = baseSeconds * 0.2;
        return (int)(baseSeconds + Random.Shared.NextDouble() * jitter * 2 - jitter);
    }

    public async Task ConnectWithRetryAsync(CancellationToken ct)
    {
        while (!ct.IsCancellationRequested)
        {
            try
            {
                SetState(ConnectionState.Connecting);
                var invosync = _httpFactory.CreateClient("InvoSync");
                var resp = await invosync.GetAsync("/health", ct).ConfigureAwait(false);
                if (resp.IsSuccessStatusCode)
                {
                    _retryCount = 0;
                    _connectedSince = DateTime.Now;
                    SetState(ConnectionState.Connected);
                    _log.LogInformation("Connected to InvoSync server");
                    await Task.Delay(TimeSpan.FromSeconds(30), ct).ConfigureAwait(false);
                    continue;
                }
                throw new HttpRequestException($"Health check returned {resp.StatusCode}");
            }
            catch (Exception ex) when (ex is not OperationCanceledException)
            {
                var waitSeconds = Math.Max(1, GetBackoffWithJitter(_retryCount));
                _log.LogWarning("Connection failed: {Msg}. Retrying in {S}s...", ex.Message, waitSeconds);
                SetState(ConnectionState.Reconnecting);
                _retryCount++;
                await Task.Delay(TimeSpan.FromSeconds(waitSeconds), ct).ConfigureAwait(false);
            }
        }
    }

    private void SetState(ConnectionState state)
    {
        State = state;
        StateChanged?.Invoke(this, state);
    }
}
