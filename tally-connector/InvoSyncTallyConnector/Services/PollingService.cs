using System.Net.Http.Json;
using System.Text.Json;
using InvoSync.TallyConnector.Models;

namespace InvoSync.TallyConnector.Services;

public class PollingService : BackgroundService
{
    private static readonly JsonSerializerOptions _json = new() { PropertyNameCaseInsensitive = true };

    private readonly IHttpClientFactory _httpFactory;
    private readonly TallyPusher _pusher;
    private readonly QueueManager _queue;
    private readonly TallyCompanySyncer _companySyncer;
    private readonly TallyLedgerSyncer _ledgerSyncer;
    private readonly ILogger<PollingService> _log;
    private readonly int _intervalSec;
    private int _tick;

    public PollingService(IHttpClientFactory httpFactory, TallyPusher pusher, QueueManager queue,
        TallyCompanySyncer companySyncer, TallyLedgerSyncer ledgerSyncer,
        IConfiguration config, ILogger<PollingService> log)
    {
        _httpFactory = httpFactory;
        _pusher = pusher;
        _queue = queue;
        _companySyncer = companySyncer;
        _ledgerSyncer = ledgerSyncer;
        _log = log;
        _intervalSec = config.GetValue<int>("InvoSync:PollIntervalSeconds", 30);
    }

    protected override async Task ExecuteAsync(CancellationToken ct)
    {
        _log.LogInformation("PollingService started (interval={Interval}s)", _intervalSec);

        // Startup self-test
        await RunStartupSelfTestAsync(ct);

        while (!ct.IsCancellationRequested)
        {
            _tick++;
            try
            {
                // Periodic Tally liveness checks
                if (_tick == 1 || _tick % 20 == 0)
                {
                    await _companySyncer.SyncOpenCompaniesAsync(ct);
                    bool reachable = await _companySyncer.RunStartupDiagnosticCheckAsync(ct);
                    await _companySyncer.ReportConnectorAliveAsync(reachable, ct);
                }
                if (_tick == 2 || _tick % 20 == 0)
                    await _ledgerSyncer.SyncLedgerListAsync(ct);

                // Fetch pending invoices from backend
                var client = _httpFactory.CreateClient("InvoSync");
                var resp = await client.GetAsync("/api/v3/sync/pending", ct);

                if (!resp.IsSuccessStatusCode)
                {
                    _log.LogWarning("Sync/pending returned {Status}", resp.StatusCode);
                    continue;
                }

                var pending = await resp.Content.ReadFromJsonAsync<PendingResponse>(_json, ct);
                if (pending?.Invoices == null || pending.Invoices.Count == 0)
                {
                    _log.LogDebug("No pending invoices");
                    continue;
                }

                _log.LogInformation("Found {Count} pending invoices", pending.Invoices.Count);

                foreach (var inv in pending.Invoices)
                {
                    if (string.IsNullOrWhiteSpace(inv.XmlContent))
                    {
                        _log.LogWarning("Invoice #{Id} ({Num}) has no XML content — skipping",
                            inv.DisplayId, inv.InvoiceNumber ?? "?");
                        continue;
                    }

                    // Enqueue for processing with retry
                    _queue.Enqueue(new TallyImportJob
                    {
                        DisplayId = inv.DisplayId,
                        XmlContent = inv.XmlContent,
                        MaxRetries = 3,
                    });
                }

                // Process queue (including retries from previous cycles)
                await ProcessQueueAsync(ct);
            }
            catch (Exception ex) when (ex is not OperationCanceledException)
            {
                _log.LogWarning(ex, "Poll cycle failed");
            }

            await Task.Delay(TimeSpan.FromSeconds(_intervalSec), ct);
        }
    }

    private async Task RunStartupSelfTestAsync(CancellationToken ct)
    {
        _log.LogInformation("=== STARTUP SELF-TEST ===");

        // 1. Check config
        var cfgOk = !string.IsNullOrEmpty(_httpFactory.CreateClient("InvoSync").BaseAddress?.ToString());
        _log.LogInformation("[CONFIG] InvoSync API URL: {Url}", cfgOk ? _httpFactory.CreateClient("InvoSync").BaseAddress : "MISSING");

        // 2. Ping backend
        try
        {
            var invosync = _httpFactory.CreateClient("InvoSync");
            var ping = await invosync.GetAsync("/api/v3/tally/status", ct);
            _log.LogInformation("[BACKEND] Ping {Status} ({Code})", ping.IsSuccessStatusCode ? "OK" : "FAIL", ping.StatusCode);
        }
        catch (Exception ex)
        {
            _log.LogError("[BACKEND] Ping FAILED — {Message}", ex.Message);
        }

        // 3. Ping Tally port 9000
        bool tallyOnline = false;
        try
        {
            tallyOnline = await _companySyncer.RunStartupDiagnosticCheckAsync(ct);
            _log.LogInformation("[TALLY] Port 9000 diagnostic: {State}", tallyOnline ? "ONLINE" : "OFFLINE");
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            _log.LogWarning("[TALLY] Diagnostic threw: {Message}", ex.Message);
        }

        // 4. Report liveness
        try
        {
            await _companySyncer.ReportConnectorAliveAsync(tallyOnline, ct);
        }
        catch (Exception ex) when (ex is not OperationCanceledException) { }

        _log.LogInformation("=== SELF-TEST COMPLETE ===");
    }

    private async Task ProcessQueueAsync(CancellationToken ct)
    {
        while (_queue.Pending > 0 && !ct.IsCancellationRequested)
        {
            var job = await _queue.DequeueAsync(ct);
            if (job == null) break;

            var client = _httpFactory.CreateClient("InvoSync");
            _log.LogInformation("Pushing invoice #{Id} to Tally (attempt {N}/{M})",
                job.DisplayId, job.RetryCount + 1, job.MaxRetries);

            var result = await _pusher.PushAsync(job.XmlContent, ct, maxRetries: 3);

            if (result.Success)
            {
                _log.LogInformation("Tally accepted invoice #{Id}", job.DisplayId);
                await ConfirmSuccessAsync(client, job.DisplayId, ct);
            }
            else
            {
                _log.LogWarning("Tally rejected invoice #{Id}: {Error}", job.DisplayId, result.ErrorLine);
                job.RetryCount++;
                if (job.RetryCount >= job.MaxRetries)
                {
                    _log.LogError("Invoice #{Id} failed after {N} retries — reporting to backend", job.DisplayId, job.MaxRetries);
                    await ReportErrorAsync(client, job.DisplayId, result.ErrorLine ?? "Max retries", ct);
                }
                else
                {
                    _log.LogWarning("Requeueing invoice #{Id} (retry {N}/{M})", job.DisplayId, job.RetryCount, job.MaxRetries);
                    _queue.Enqueue(job);
                }
            }
        }
    }

    private async Task ConfirmSuccessAsync(HttpClient client, int displayId, CancellationToken ct)
    {
        try
        {
            var confirm = await client.PostAsync($"/api/v3/sync/confirm/{displayId}", null, ct);
            if (!confirm.IsSuccessStatusCode)
                _log.LogWarning("Confirm #{Id} returned {Status}", displayId, confirm.StatusCode);
        }
        catch (Exception ex) { _log.LogWarning("Confirm #{Id} failed: {Message}", displayId, ex.Message); }
    }

    private async Task ReportErrorAsync(HttpClient client, int displayId, string error, CancellationToken ct)
    {
        try
        {
            var payload = JsonContent.Create(new { error });
            var resp = await client.PostAsync($"/api/v3/sync/error/{displayId}", payload, ct);
            if (!resp.IsSuccessStatusCode)
                _log.LogWarning("Error-report #{Id} returned {Status}", displayId, resp.StatusCode);
        }
        catch (Exception ex) { _log.LogWarning("Error-report #{Id} failed: {Message}", displayId, ex.Message); }
    }
}
