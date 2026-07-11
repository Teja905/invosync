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

        // Startup diagnostic: immediate Tally port 9000 check
        bool tallyOnline = false;
        try
        {
            tallyOnline = await _companySyncer.RunStartupDiagnosticCheckAsync(ct);
            _log.LogInformation("Startup diagnostic: Tally Prime is {State}", tallyOnline ? "ONLINE" : "OFFLINE");
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            _log.LogWarning("Startup diagnostic threw: {Message}", ex.Message);
        }

        // Report connector liveness to backend immediately (even if Tally is offline)
        try
        {
            await _companySyncer.ReportConnectorAliveAsync(tallyOnline, ct);
        }
        catch (Exception ex) when (ex is not OperationCanceledException) { }

        while (!ct.IsCancellationRequested)
        {
            _tick++;
            try
            {
                if (_tick == 1 || _tick % 20 == 0)
                {
                    await _companySyncer.SyncOpenCompaniesAsync(ct);
                    // Re-run diagnostic on company sync tick
                    bool reachable = await _companySyncer.RunStartupDiagnosticCheckAsync(ct);
                    await _companySyncer.ReportConnectorAliveAsync(reachable, ct);
                }
                if (_tick == 2 || _tick % 20 == 0)
                    await _ledgerSyncer.SyncLedgerListAsync(ct);

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

                    _log.LogInformation("Pushing invoice #{Id} ({Num}, type={Type}) to Tally",
                        inv.DisplayId, inv.InvoiceNumber ?? "?", inv.VoucherType ?? "?");

                    var result = await _pusher.PushAsync(inv.XmlContent, ct);

                    if (result.Success)
                    {
                        _log.LogInformation("Tally accepted invoice #{Id}", inv.DisplayId);
                        var confirm = await client.PostAsync($"/api/v3/sync/confirm/{inv.DisplayId}", null, ct);
                        if (!confirm.IsSuccessStatusCode)
                            _log.LogWarning("Confirm #{Id} returned {Status}", inv.DisplayId, confirm.StatusCode);
                    }
                    else
                    {
                        _log.LogWarning("Tally rejected invoice #{Id}: {Error}", inv.DisplayId, result.ErrorLine);
                        var errPayload = JsonContent.Create(new { error = result.ErrorLine ?? "Unknown" });
                        var errResp = await client.PostAsync($"/api/v3/sync/error/{inv.DisplayId}", errPayload, ct);
                        if (!errResp.IsSuccessStatusCode)
                            _log.LogWarning("Error-report #{Id} returned {Status}", inv.DisplayId, errResp.StatusCode);
                    }
                }
            }
            catch (Exception ex) when (ex is not OperationCanceledException)
            {
                _log.LogWarning(ex, "Poll cycle failed");
            }

            await Task.Delay(TimeSpan.FromSeconds(_intervalSec), ct);
        }
    }
}
