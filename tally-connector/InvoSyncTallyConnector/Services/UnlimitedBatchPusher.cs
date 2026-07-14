using System.Diagnostics;
using System.Text;
using InvoSync.TallyConnector.Models;

namespace InvoSync.TallyConnector.Services;

public class BatchProgress
{
    public int Total { get; set; }
    public int Completed { get; set; }
    public int Succeeded { get; set; }
    public int Failed { get; set; }
    public int CurrentBatch { get; set; }
    public int TotalBatches { get; set; }
    public string Status { get; set; } = "";
}

public class UnlimitedBatchPusher
{
    private readonly IHttpClientFactory _httpFactory;
    private readonly TallyPusher _pusher;
    private readonly ILogger<UnlimitedBatchPusher> _log;
    public event Action<BatchProgress>? ProgressUpdated;

    public UnlimitedBatchPusher(IHttpClientFactory httpFactory, TallyPusher pusher, ILogger<UnlimitedBatchPusher> log)
    {
        _httpFactory = httpFactory;
        _pusher = pusher;
        _log = log;
    }

    public async Task<BatchResult> PushBatchAsync(
        List<InvoiceDto> invoices,
        CancellationToken ct,
        string? tallyPassword = null)
    {
        var result = new BatchResult();
        var batches = invoices.Chunk(100).ToList();
        var total = invoices.Count;
        var tallyResponseTime = await MeasureTallyResponseTime();

        Notify(new BatchProgress
        {
            Total = total,
            TotalBatches = batches.Count,
            Status = $"Processing {total} invoices in {batches.Count} batches"
        });

        for (int b = 0; b < batches.Count; b++)
        {
            if (ct.IsCancellationRequested) break;

            var batch = batches[b];
            Notify(new BatchProgress
            {
                Total = total,
                TotalBatches = batches.Count,
                CurrentBatch = b + 1,
                Status = $"Batch {b + 1} of {batches.Count}..."
            });

            foreach (var inv in batch)
            {
                if (ct.IsCancellationRequested) break;

                if (string.IsNullOrWhiteSpace(inv.XmlContent)) continue;

                var pushResult = await _pusher.PushAsync(inv.XmlContent, ct, maxRetries: 2, tallyPassword: tallyPassword);
                result.Completed++;

                if (pushResult.Success)
                {
                    result.Succeeded++;
                    await ConfirmAsync(inv.DisplayId, ct);
                }
                else
                {
                    result.Failed.Add(new FailedInvoice
                    {
                        DisplayId = inv.DisplayId,
                        InvoiceNumber = inv.InvoiceNumber ?? "?",
                        Error = pushResult.ErrorLine ?? "Unknown"
                    });
                }

                Notify(new BatchProgress
                {
                    Total = total,
                    Completed = result.Completed,
                    Succeeded = result.Succeeded,
                    Failed = result.Failed.Count,
                    CurrentBatch = b + 1,
                    TotalBatches = batches.Count,
                    Status = $"{result.Completed}/{total} — {result.Succeeded}✓ {result.Failed.Count}✗"
                });

                var adaptiveDelay = GetAdaptiveDelay(tallyResponseTime);
                await Task.Delay(adaptiveDelay, ct);
            }

            if (b < batches.Count - 1)
                await Task.Delay(1000, ct);
        }

        return result;
    }

    private async Task<TimeSpan> MeasureTallyResponseTime()
    {
        try
        {
            var sw = Stopwatch.StartNew();
            using var cts = new CancellationTokenSource(TimeSpan.FromSeconds(5));
            var client = _httpFactory.CreateClient("Tally");
            var xml = @"<ENVELOPE><HEADER><VERSION>1</VERSION><TALLYREQUEST>Export</TALLYREQUEST><TYPE>Company</TYPE><ID>List of Companies</ID></HEADER><BODY><DESC><STATICVARIABLES></STATICVARIABLES></DESC></BODY></ENVELOPE>";
            var content = new StringContent(xml, Encoding.UTF8, "text/xml");
            var resp = await client.PostAsync("", content, cts.Token).ConfigureAwait(false);
            sw.Stop();
            return sw.Elapsed;
        }
        catch
        {
            return TimeSpan.FromMilliseconds(500);
        }
    }

    private static int GetAdaptiveDelay(TimeSpan tallyResponseTime)
    {
        var baseMs = 200;
        var multiplier = Math.Max(1.0, tallyResponseTime.TotalMilliseconds / 100);
        return (int)(baseMs * multiplier);
    }

    private async Task ConfirmAsync(int displayId, CancellationToken ct)
    {
        try
        {
            var client = _httpFactory.CreateClient("InvoSync");
            await client.PostAsync($"/api/v3/sync/confirm/{displayId}", null, ct);
        }
        catch { }
    }

    private void Notify(BatchProgress p) => ProgressUpdated?.Invoke(p);
}

public class BatchResult
{
    public int Completed { get; set; }
    public int Succeeded { get; set; }
    public List<FailedInvoice> Failed { get; set; } = new();
}

public class FailedInvoice
{
    public int DisplayId { get; set; }
    public string InvoiceNumber { get; set; } = "";
    public string Error { get; set; } = "";
}
