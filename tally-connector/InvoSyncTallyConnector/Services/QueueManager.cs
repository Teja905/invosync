using System.Collections.Concurrent;
using InvoSync.TallyConnector.Models;

namespace InvoSync.TallyConnector.Services;

public class TallyImportJob
{
    public int DisplayId { get; set; }
    public string XmlContent { get; set; } = "";
    public int RetryCount { get; set; }
}

public class QueueManager
{
    private readonly ConcurrentQueue<TallyImportJob> _queue = new();
    private readonly SemaphoreSlim _signal = new(0);

    public void Enqueue(TallyImportJob job) { _queue.Enqueue(job); _signal.Release(); }

    public async Task<TallyImportJob?> DequeueAsync(CancellationToken ct)
    {
        await _signal.WaitAsync(ct);
        if (_queue.TryDequeue(out var job)) return job;
        return null;
    }

    public int Pending => _queue.Count;
}
