using System.Collections.Concurrent;
using InvoSync.TallyConnector.Models;

namespace InvoSync.TallyConnector.Services;

public class TallyImportJob
{
    public int DisplayId { get; set; }
    public string InvoiceNumber { get; set; } = "";
    public string XmlContent { get; set; } = "";
    public int RetryCount { get; set; }
    public int MaxRetries { get; set; } = 3;
}

public class QueueManager
{
    private readonly ConcurrentQueue<TallyImportJob> _queue = new();
    private readonly SemaphoreSlim _signal = new(0);
    private readonly Dictionary<int, TallyImportJob> _deadLetter = new(); // failed after max retries
    private readonly ILogger<QueueManager> _log;

    public QueueManager(ILogger<QueueManager> log)
    {
        _log = log;
    }

    public void Enqueue(TallyImportJob job) { _queue.Enqueue(job); _signal.Release(); }

    public async Task<TallyImportJob?> DequeueAsync(CancellationToken ct)
    {
        await _signal.WaitAsync(ct);
        if (_queue.TryDequeue(out var job)) return job;
        return null;
    }

    public void RequeueOnFailure(TallyImportJob job)
    {
        job.RetryCount++;
        if (job.RetryCount >= job.MaxRetries)
        {
            _deadLetter[job.DisplayId] = job;
            _log.LogError("Invoice #{Id} moved to dead-letter queue after {N} retries", job.DisplayId, job.RetryCount);
            return;
        }
        _log.LogWarning("Requeueing invoice #{Id} (retry {N}/{M})", job.DisplayId, job.RetryCount, job.MaxRetries);
        _queue.Enqueue(job);
        _signal.Release();
    }

    public IReadOnlyDictionary<int, TallyImportJob> DeadLetter => _deadLetter;
    public int Pending => _queue.Count;
    public int DeadLetterCount => _deadLetter.Count;
}
