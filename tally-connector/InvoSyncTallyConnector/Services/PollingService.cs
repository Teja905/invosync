using System.Net.Http.Json;
using System.Text;
using System.Net.Http.Headers;
using System.Text.Json;
using InvoSync.TallyConnector.Models;

namespace InvoSync.TallyConnector.Services;

public class PollingService : BackgroundService
{
    private static readonly JsonSerializerOptions _json = new() { PropertyNameCaseInsensitive = true };

    private readonly IHttpClientFactory _httpFactory;
    private readonly TallyPusher _pusher;
    private readonly QueueManager _queue;
    private readonly OfflineQueue _offlineQueue;
    private readonly NetworkMonitor _networkMonitor;
    private readonly ConnectorLogger _connectorLogger;
    private readonly SyncWatchdog _watchdog;
    private readonly RecentPushStore _recentPushes;
    private readonly TallyCompanySyncer _companySyncer;
    private readonly TallyLedgerSyncer _ledgerSyncer;
    private readonly TallyRegisterPuller _registerPuller;
    private readonly TallyMasterReader _masterReader;
    private readonly DryRunValidator _dryRunValidator;
    private readonly ImportReporter _importReporter;
    private readonly IdempotencyChecker _idempotencyChecker;
    private readonly DiagnosticReporter _diagnosticReporter;
    private readonly ILogger<PollingService> _log;
    private readonly int _intervalSec;
    private int _tick;
    private string _tallyPassword = "";
    private string _activeCompany = "";
    private CancellationTokenSource? _watchdogCts;
    private int _consecutiveFailures;
    private readonly object _failLock = new();
    private string? _currentTraceId;
    private readonly CircuitBreaker _tallyCb;

    public PollingService(IHttpClientFactory httpFactory, TallyPusher pusher, QueueManager queue,
        OfflineQueue offlineQueue, NetworkMonitor networkMonitor,
        ConnectorLogger connectorLogger,
        SyncWatchdog watchdog, RecentPushStore recentPushes,
        TallyCompanySyncer companySyncer, TallyLedgerSyncer ledgerSyncer,
        TallyRegisterPuller registerPuller,
        TallyMasterReader masterReader, DryRunValidator dryRunValidator,
        ImportReporter importReporter, IdempotencyChecker idempotencyChecker,
        DiagnosticReporter diagnosticReporter,
        IConfiguration config, ILogger<PollingService> log)
    {
        _httpFactory = httpFactory;
        _pusher = pusher;
        _queue = queue;
        _offlineQueue = offlineQueue;
        _networkMonitor = networkMonitor;
        _connectorLogger = connectorLogger;
        _watchdog = watchdog;
        _recentPushes = recentPushes;
        _companySyncer = companySyncer;
        _ledgerSyncer = ledgerSyncer;
        _registerPuller = registerPuller;
        _masterReader = masterReader;
        _dryRunValidator = dryRunValidator;
        _importReporter = importReporter;
        _idempotencyChecker = idempotencyChecker;
        _diagnosticReporter = diagnosticReporter;
        _log = log;
        _intervalSec = config.GetValue<int>("InvoSync:PollIntervalSeconds", 30);
        _tallyCb = new CircuitBreaker("Tally", log, threshold: 3, cooldownMs: 30_000);
    }

    /// <summary>Fetches Tally password and active company from backend.</summary>
    private async Task RefreshTallyConfigAsync(CancellationToken ct)
    {
        try
        {
            var invosync = _httpFactory.CreateClient("InvoSync");
            var resp = await invosync.GetAsync("/api/v3/tally/config", ct);
            if (resp.IsSuccessStatusCode)
            {
                var cfg = await resp.Content.ReadFromJsonAsync<JsonElement>(ct);
                if (cfg.TryGetProperty("tally_password", out var pw))
                    _tallyPassword = pw.GetString() ?? "";
                if (cfg.TryGetProperty("active_company", out var ac))
                    _activeCompany = ac.GetString() ?? "";
                _log.LogDebug("Tally config refreshed (password={L}, company={C})",
                    string.IsNullOrEmpty(_tallyPassword) ? "not set" : "set",
                    string.IsNullOrEmpty(_activeCompany) ? "not set" : _activeCompany);
            }
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            _log.LogDebug("Tally config refresh failed: {Message}", ex.Message);
        }
    }

    protected override async Task ExecuteAsync(CancellationToken ct)
    {
        _log.LogInformation("PollingService started (interval={Interval}s)", _intervalSec);

        // Wire up watchdog to restart on stuck sync
        _watchdogCts = CancellationTokenSource.CreateLinkedTokenSource(ct);
        _watchdog.Start(_watchdogCts);
        _watchdog.SyncRestarted += async (_, _) =>
        {
            _log.LogInformation("Watchdog triggered sync restart");
            _watchdogCts = CancellationTokenSource.CreateLinkedTokenSource(ct);
            _watchdog.Start(_watchdogCts);
        };

        // Wire up network monitor to flush offline queue when back online
        _networkMonitor.NetworkChanged += async (_, available) =>
        {
            if (available)
            {
                _log.LogInformation("Network restored — flushing offline queue");
                await _offlineQueue.ProcessPendingAsync(async item =>
                {
                    var result = await _pusher.PushAsync(item.XmlContent, ct, maxRetries: 2, tallyPassword: _tallyPassword);
                    if (result.Success)
                    {
                        _connectorLogger.TallyPush(item.InvoiceId, true);
                var client = _httpFactory.CreateClient("InvoSync");
                if (int.TryParse(item.InvoiceId, out var id))
                    await ConfirmSuccessAsync(client, id, null, ct);
                    }
                    else
                    {
                        _connectorLogger.TallyPush(item.InvoiceId, false, result.ErrorLine);
                    }
                    return result.Success;
                });
            }
        };

        // Startup self-test + fetch Tally config
        await RunStartupSelfTestAsync(ct);
        await RefreshTallyConfigAsync(ct);

        while (!ct.IsCancellationRequested)
        {
            _tick++;
            try
            {
                // Periodic Tally liveness checks
                if (_tick == 1 || _tick % 20 == 0)
                {
                    bool reachable = await _companySyncer.RunStartupDiagnosticCheckAsync(ct);
                    await _companySyncer.SyncOpenCompaniesAsync(ct, activeCompany: "");
                    await _companySyncer.ReportConnectorAliveAsync(reachable, ct);
                }
                if (_tick == 2 || _tick % 20 == 0)
                {
                    await _tallyCb.ExecuteAsync(() => _ledgerSyncer.SyncLedgerListAsync(ct));
                }

                // Refetch config periodically (every 60 ticks ~30 min)
                if (_tick % 60 == 0)
                    await RefreshTallyConfigAsync(ct);

                // Sync Tally masters every 80 ticks (~40 min)
                if (_tick % 80 == 0 && !string.IsNullOrEmpty(_activeCompany))
                {
                    _log.LogInformation("Syncing Tally masters for company: {Company}", _activeCompany);
                    await _tallyCb.ExecuteAsync(() => SyncTallyMastersAsync(_activeCompany, ct));
                }

                // Pull vouchers from Tally (every 40 ticks ~20 min)
                if (_tick % 40 == 0 && !string.IsNullOrEmpty(_activeCompany))
                {
                    _log.LogInformation("Pulling vouchers from Tally company: {Company}", _activeCompany);
                    var (pulled, posted) = await _registerPuller.PullAndSendAsync(
                        _activeCompany, _tallyPassword, ct,
                        fromDate: DateTime.Today.AddDays(-7), toDate: DateTime.Today);
                    if (pulled > 0)
                        _log.LogInformation("Tally pull: {Pulled} found, {Posted} imported", pulled, posted);
                }

                // Fetch pending invoices from backend
                var client = _httpFactory.CreateClient("InvoSync");
                var resp = await client.GetAsync("/api/v3/sync/pending", ct);

                if (!resp.IsSuccessStatusCode)
                {
                    _log.LogWarning("Sync/pending returned {Status}", resp.StatusCode);
                    await Task.Delay(TimeSpan.FromSeconds(_intervalSec), ct);
                    continue;
                }

                var pending = await resp.Content.ReadFromJsonAsync<PendingResponse>(_json, ct);
                if (pending?.Invoices == null || pending.Invoices.Count == 0)
                {
                    _log.LogDebug("No pending invoices");
                    await Task.Delay(TimeSpan.FromSeconds(_intervalSec), ct);
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
                        InvoiceNumber = inv.InvoiceNumber ?? "",
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

    private async Task SyncTallyMastersAsync(string companyName, CancellationToken ct)
    {
        try
        {
            var ledgers = await _masterReader.GetLedgersWithDetailsAsync(companyName, ct);
            var stockItems = await _masterReader.GetStockItemsAsync(companyName, ct);
            var voucherTypes = await _masterReader.GetVoucherTypesAsync(companyName, ct);
            var groups = await _masterReader.GetGroupsAsync(companyName, ct);
            var units = await _masterReader.GetUnitsAsync(companyName, ct);

            var client = _httpFactory.CreateClient("InvoSync");
            using var masterCts = CancellationTokenSource.CreateLinkedTokenSource(ct);
            masterCts.CancelAfter(TimeSpan.FromSeconds(30));

            if (ledgers.Count > 0)
            {
                var ledgerPayload = new { ledgers = ledgers.Select(l => new { name = l.Name, parent = l.Parent, gst_type = l.GstType }) };
                using var ledgerContent = new StringContent(JsonSerializer.Serialize(ledgerPayload), Encoding.UTF8);
                ledgerContent.Headers.ContentType = new MediaTypeHeaderValue("application/json");
                await client.PostAsync("/api/v3/tally/masters/ledgers", ledgerContent, masterCts.Token);
            }
            if (stockItems.Count > 0)
            {
                var stockPayload = new { stock_items = stockItems };
                using var stockContent = new StringContent(JsonSerializer.Serialize(stockPayload), Encoding.UTF8);
                stockContent.Headers.ContentType = new MediaTypeHeaderValue("application/json");
                await client.PostAsync("/api/v3/tally/masters/stock-items", stockContent, masterCts.Token);
            }
            if (voucherTypes.Count > 0)
            {
                var vtPayload = new { voucher_types = voucherTypes };
                using var vtContent = new StringContent(JsonSerializer.Serialize(vtPayload), Encoding.UTF8);
                vtContent.Headers.ContentType = new MediaTypeHeaderValue("application/json");
                await client.PostAsync("/api/v3/tally/masters/voucher-types", vtContent, masterCts.Token);
            }
            if (groups.Count > 0)
            {
                var groupPayload = new { groups };
                using var groupContent = new StringContent(JsonSerializer.Serialize(groupPayload), Encoding.UTF8);
                groupContent.Headers.ContentType = new MediaTypeHeaderValue("application/json");
                await client.PostAsync("/api/v3/tally/masters/groups", groupContent, masterCts.Token);
            }
            if (units.Count > 0)
            {
                var unitPayload = new { units };
                using var unitContent = new StringContent(JsonSerializer.Serialize(unitPayload), Encoding.UTF8);
                unitContent.Headers.ContentType = new MediaTypeHeaderValue("application/json");
                await client.PostAsync("/api/v3/tally/masters/units", unitContent, masterCts.Token);
            }

            _log.LogInformation("Synced {L} ledgers, {S} stock items, {V} voucher types, {G} groups, {U} units",
                ledgers.Count, stockItems.Count, voucherTypes.Count, groups.Count, units.Count);
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            _log.LogDebug(ex, "Tally masters sync failed");
        }
    }

    private async Task ProcessQueueAsync(CancellationToken ct)
    {
        while (_queue.Pending > 0 && !ct.IsCancellationRequested)
        {
            var job = await _queue.DequeueAsync(ct);
            if (job == null) break;

            // If network is down, save to offline queue and skip
            if (!_networkMonitor.IsAvailable)
            {
                _log.LogWarning("Network offline — saving invoice #{Id} to offline queue", job.DisplayId);
                _offlineQueue.Enqueue(job.DisplayId.ToString(), job.XmlContent);
                continue;
            }

            var client = _httpFactory.CreateClient("InvoSync");
            _log.LogInformation("Pushing invoice #{Id} to Tally (attempt {N}/{M})",
                job.DisplayId, job.RetryCount + 1, job.MaxRetries);

            _watchdog.RecordActivity();

            // P0 — Idempotency check before push
            try
            {
                var invoiceData = await client.GetFromJsonAsync<InvoicePreview>($"/api/v3/invoices/{job.DisplayId}", ct);
                if (invoiceData != null && !string.IsNullOrEmpty(invoiceData.VendorName))
                {
                    bool isDup = await _idempotencyChecker.IsDuplicateAsync(
                        invoiceData.VendorName,
                        invoiceData.InvoiceNumber ?? "",
                        invoiceData.TotalAmount,
                        invoiceData.InvoiceDate ?? "",
                        ct);
                    if (isDup)
                    {
                        _log.LogWarning("Duplicate detected for invoice #{Id} — skipping push", job.DisplayId);
                        _recentPushes.Add(new RecentPushEntry
                        {
                            Timestamp = DateTime.Now,
                            DisplayId = job.DisplayId,
                            InvoiceNumber = job.InvoiceNumber,
                            Success = false,
                            Error = "Duplicate: already imported",
                        });
                        await ConfirmSuccessAsync(client, job.DisplayId, null, ct);
                        continue;
                    }
                }
            }
            catch (Exception ex)
            {
                _log.LogDebug(ex, "Idempotency check skipped for invoice #{Id}", job.DisplayId);
            }

            // P0 — Dry run validation before push
            var dryRun = await _dryRunValidator.ValidateAsync(_activeCompany, new { job.DisplayId }, ct);
            if (!dryRun.SafeToImport)
            {
                _log.LogWarning("Dry-run failed for invoice #{Id}: {Warnings}",
                    job.DisplayId, string.Join("; ", dryRun.Warnings));
                _recentPushes.Add(new RecentPushEntry
                {
                    Timestamp = DateTime.Now,
                    DisplayId = job.DisplayId,
                    InvoiceNumber = job.InvoiceNumber,
                    Success = false,
                    Error = $"Dry-run failed: {string.Join("; ", dryRun.Warnings)}",
                });
                continue;
            }

            var traceId = Guid.NewGuid().ToString("N")[..12];
            _currentTraceId = traceId;
            var startTime = DateTime.UtcNow;
            var result = await _pusher.PushAsync(job.XmlContent, ct, maxRetries: 3, tallyPassword: _tallyPassword);
            var durationMs = (int)(DateTime.UtcNow - startTime).TotalMilliseconds;
            _watchdog.RecordActivity();

            if (result.Success)
            {
                _log.LogInformation("Tally accepted invoice #{Id} [trace={Trace}]", job.DisplayId, traceId);
                _connectorLogger.TallyPush(job.DisplayId.ToString(), true);
                _recentPushes.Add(new RecentPushEntry
                {
                    Timestamp = DateTime.Now,
                    DisplayId = job.DisplayId,
                    InvoiceNumber = job.InvoiceNumber,
                    Success = true,
                    ConnectorVersion = GetConnectorVersion(),
                    TraceId = traceId,
                    DurationMs = durationMs,
                });

                // Reset consecutive failure counter
                lock (_failLock) { _consecutiveFailures = 0; }

                // P0 — Import report
                var mastersCreated = dryRun.MastersToCreate ?? new List<string>();
                string voucherId = ExtractVoucherId(result.RawResponse);
                _ = _importReporter.ReportAsync(
                    job.DisplayId, true, mastersCreated, voucherId,
                    result.RawResponse ?? "", dryRun.Warnings, "", durationMs, ct);

                await ConfirmSuccessAsync(client, job.DisplayId, traceId, ct);
            }
            else
            {
                _log.LogWarning("Tally rejected invoice #{Id} [trace={Trace}]: {Error}", job.DisplayId, traceId, result.ErrorLine);
                _connectorLogger.TallyPush(job.DisplayId.ToString(), false, result.ErrorLine);
                _recentPushes.Add(new RecentPushEntry
                {
                    Timestamp = DateTime.Now,
                    DisplayId = job.DisplayId,
                    InvoiceNumber = job.InvoiceNumber,
                    Success = false,
                    Error = result.ErrorLine,
                    ConnectorVersion = GetConnectorVersion(),
                    TraceId = traceId,
                    DurationMs = durationMs,
                });

                // P0 — Import report for failures
                _ = _importReporter.ReportAsync(
                    job.DisplayId, false, new List<string>(), "",
                    result.RawResponse ?? "", dryRun.Warnings, result.ErrorLine ?? "Unknown", durationMs, ct);

                // Track consecutive failures → auto-diagnostics
                bool triggerDiag = false;
                lock (_failLock)
                {
                    _consecutiveFailures++;
                    if (_consecutiveFailures >= 5)
                    {
                        triggerDiag = true;
                        _consecutiveFailures = 0;
                    }
                }
                if (triggerDiag)
                {
                    _log.LogWarning("5 consecutive failures — triggering auto-diagnostics [trace={Trace}]", traceId);
                    _ = _diagnosticReporter.GenerateReportAsync();
                }

                job.RetryCount++;
                if (job.RetryCount >= job.MaxRetries)
                {
                    _log.LogError("Invoice #{Id} failed after {N} retries — saving to offline dead letter", job.DisplayId, job.MaxRetries);
                    _offlineQueue.Enqueue(job.DisplayId.ToString(), job.XmlContent);
                    await ReportErrorAsync(client, job.DisplayId, result.ErrorLine ?? "Max retries", ct);
                }
                else
                {
                    _log.LogWarning("Requeueing invoice #{Id} (retry {N}/{M}) [trace={Trace}]", job.DisplayId, job.RetryCount, job.MaxRetries, traceId);
                    _queue.Enqueue(job);
                }
            }
        }
    }

    private static string ExtractVoucherId(string? tallyResponse)
    {
        if (string.IsNullOrEmpty(tallyResponse)) return "";
        var match = System.Text.RegularExpressions.Regex.Match(tallyResponse, @"<VOUCHER[^>]*\bVOUCHERKEY=""([^""]+)""");
        return match.Success ? match.Groups[1].Value : "";
    }

    private class InvoicePreview
    {
        public string VendorName { get; set; } = "";
        public string InvoiceNumber { get; set; } = "";
        public double TotalAmount { get; set; }
        public string InvoiceDate { get; set; } = "";
    }

    private async Task ConfirmSuccessAsync(HttpClient client, int displayId, string? traceId, CancellationToken ct)
    {
        try
        {
            using var req = new HttpRequestMessage(HttpMethod.Post, $"/api/v3/sync/confirm/{displayId}");
            req.Headers.TryAddWithoutValidation("X-Trace-Id", traceId ?? "");
            req.Headers.TryAddWithoutValidation("X-Connector-Version", GetConnectorVersion());
            var confirm = await client.SendAsync(req, ct);
            if (!confirm.IsSuccessStatusCode)
                _log.LogWarning("Confirm #{Id} returned {Status} [trace={Trace}]", displayId, confirm.StatusCode, traceId);
        }
        catch (Exception ex) { _log.LogWarning("Confirm #{Id} failed: {Message} [trace={Trace}]", displayId, ex.Message, traceId); }
    }

    private static string GetConnectorVersion()
    {
        var asm = System.Reflection.Assembly.GetExecutingAssembly();
        var ver = asm.GetName().Version;
        return ver != null ? $"{ver.Major}.{ver.Minor}.{ver.Build}" : "1.0.0";
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
