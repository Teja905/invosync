namespace InvoSync.TallyConnector.Services;

/// <summary>
/// Circuit breaker — after N consecutive failures, stops trying for a cooldown period.
/// Prevents cascading failures when Tally or the backend is down.
/// </summary>
public class CircuitBreaker
{
    private readonly int _threshold;
    private readonly int _cooldownMs;
    private readonly ILogger _log;
    private readonly string _name;

    private int _failureCount;
    private DateTime _lastFailureTime;
    private bool _isOpen;

    public bool IsOpen => _isOpen;

    public CircuitBreaker(string name, ILogger log, int threshold = 3, int cooldownMs = 30_000)
    {
        _name = name;
        _log = log;
        _threshold = threshold;
        _cooldownMs = cooldownMs;
    }

    /// <summary>Execute an operation with circuit breaker protection.</summary>
    /// <returns>True if executed, false if circuit is open.</returns>
    public async Task<bool> ExecuteAsync(Func<Task> operation)
    {
        if (_isOpen)
        {
            var elapsed = (DateTime.UtcNow - _lastFailureTime).TotalMilliseconds;
            if (elapsed < _cooldownMs)
            {
                _log.LogDebug("[CB:{Name}] Circuit open — skipping ({Remaining:F0}s remaining)",
                    _name, (_cooldownMs - elapsed) / 1000);
                return false;
            }

            _log.LogInformation("[CB:{Name}] Circuit half-open — retrying", _name);
            _isOpen = false;
            _failureCount = 0;
        }

        try
        {
            await operation();
            _failureCount = 0;
            return true;
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            _failureCount++;
            _lastFailureTime = DateTime.UtcNow;

            if (_failureCount >= _threshold)
            {
                _isOpen = true;
                _log.LogWarning("[CB:{Name}] Circuit opened after {N} failures: {Message}",
                    _name, _failureCount, ex.Message);
            }
            else
            {
                _log.LogDebug("[CB:{Name}] Failure {N}/{T}: {Message}",
                    _name, _failureCount, _threshold, ex.Message);
            }

            throw;
        }
    }

    public void Reset()
    {
        _failureCount = 0;
        _isOpen = false;
    }
}
