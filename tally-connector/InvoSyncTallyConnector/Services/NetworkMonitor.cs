using Microsoft.Extensions.Logging;

namespace InvoSync.TallyConnector.Services;

public class NetworkMonitor : IDisposable
{
    private readonly ILogger<NetworkMonitor> _log;
    private readonly OfflineQueue _offlineQueue;
    private System.Threading.Timer? _debounceTimer;
    private bool _lastKnownState = true;
    public event EventHandler<bool>? NetworkChanged;

    public NetworkMonitor(ILogger<NetworkMonitor> log, OfflineQueue offlineQueue)
    {
        _log = log;
        _offlineQueue = offlineQueue;
        System.Net.NetworkInformation.NetworkChange.NetworkAvailabilityChanged += OnNetworkChanged;
    }

    public bool IsAvailable { get; private set; } = true;

    private void OnNetworkChanged(object? sender, System.Net.NetworkInformation.NetworkAvailabilityEventArgs e)
    {
        _debounceTimer?.Dispose();
        _debounceTimer = new System.Threading.Timer(_ =>
        {
            var isAvailable = e.IsAvailable;

            if (isAvailable == _lastKnownState) return;
            _lastKnownState = isAvailable;
            IsAvailable = isAvailable;

            NetworkChanged?.Invoke(this, isAvailable);

            if (isAvailable)
                _log.LogInformation("Network restored — PollingService will flush offline queue on next cycle");
            else
                _log.LogWarning("Network lost — switching to offline mode");

        }, null, 2000, Timeout.Infinite);
    }

    public void Dispose()
    {
        _debounceTimer?.Dispose();
        System.Net.NetworkInformation.NetworkChange.NetworkAvailabilityChanged -= OnNetworkChanged;
    }
}
