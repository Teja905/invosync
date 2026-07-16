using System.Text;
using System.Text.Json;

namespace InvoSync.TallyConnector.Services;

public class TallyLedgerSyncer
{
    private readonly IHttpClientFactory _httpFactory;
    private readonly ILogger<TallyLedgerSyncer> _log;
    private readonly TallyMasterReader _masterReader;

    public TallyLedgerSyncer(IHttpClientFactory httpFactory, ILogger<TallyLedgerSyncer> log, TallyMasterReader masterReader)
    {
        _httpFactory = httpFactory;
        _log = log;
        _masterReader = masterReader;
    }

    public async Task SyncLedgerListAsync(CancellationToken ct)
    {
        _log.LogInformation("SyncLedgerListAsync started");
        var invosync = _httpFactory.CreateClient("InvoSync");
        string companyName = "";
        try
        {
            _log.LogDebug("Fetching active company from /api/v3/tally/status");
            var statusResp = await invosync.GetAsync("/api/v3/tally/status", ct);
            if (!statusResp.IsSuccessStatusCode)
            {
                _log.LogWarning("Tally status API returned {StatusCode}", statusResp.StatusCode);
            }
            else
            {
                var json = await statusResp.Content.ReadAsStringAsync(ct);
                using var doc = JsonDocument.Parse(json);
                companyName = doc.RootElement.GetProperty("active_company").GetString() ?? "";
                _log.LogInformation("Active company from backend: '{Company}'", companyName);
            }
        }
        catch (Exception ex)
        {
            _log.LogWarning(ex, "Failed to fetch active company from backend");
        }

        if (string.IsNullOrEmpty(companyName))
        {
            _log.LogInformation("No active company set — skipping enriched ledger sync. " +
                "User must set active company in Settings or via connector first sync.");
            // Fallback: try reading ledgers without company filter (Tally will use default)
            try
            {
                _log.LogInformation("Attempting fallback: ledger names only (no parent/GST)");
                var invosync2 = _httpFactory.CreateClient("InvoSync");
                var tally = _httpFactory.CreateClient("Tally");
                var fallbackXml = @"<ENVELOPE>
<HEADER><VERSION>1</VERSION><TALLYREQUEST>Export</TALLYREQUEST><TYPE>Object</TYPE><DESC>
<STATICVARIABLES>
<SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>
</STATICVARIABLES>
</DESC></HEADER>
<BODY>
<DESC><TALLYREQUEST>Export Collection</TALLYREQUEST><TYPE>Ledger</TYPE></DESC>
</BODY>
</ENVELOPE>";
                var fallbackContent = new StringContent(fallbackXml, Encoding.UTF8, "text/xml");
                var fallbackResp = await tally.PostAsync("", fallbackContent, ct);
                if (fallbackResp.IsSuccessStatusCode)
                {
                    var fallbackXmlBody = await fallbackResp.Content.ReadAsStringAsync(ct);
                    var fallbackNames = ParseSimpleLedgerNames(fallbackXmlBody);
                    if (fallbackNames.Count > 0)
                    {
                        var fallbackPayload = JsonSerializer.Serialize(new { ledgers = fallbackNames.Select(n => new { name = n, parent = "", gst_type = "" }) });
                        var fallbackJson = new StringContent(fallbackPayload, Encoding.UTF8, "application/json");
                        var syncResp = await invosync2.PostAsync("/api/v3/sync/ledgers", fallbackJson, ct);
                        if (syncResp.IsSuccessStatusCode)
                            _log.LogInformation("Fallback: synced {Count} ledger names (no parent/GST) to InvoSync", fallbackNames.Count);
                    }
                }
            }
            catch (Exception fallbackEx)
            {
                _log.LogWarning(fallbackEx, "Fallback ledger sync also failed");
            }
            return;
        }

        try
        {
            _log.LogInformation("Fetching ledgers with details from Tally for company: {Company}", companyName);
            var ledgerDetails = await _masterReader.GetLedgersWithDetailsAsync(companyName, ct);
            if (ledgerDetails.Count == 0)
            {
                _log.LogWarning("Tally returned 0 ledgers for company: {Company}", companyName);
                return;
            }

            var payload = JsonSerializer.Serialize(new { ledgers = ledgerDetails.Select(l => new { l.Name, l.Parent, l.GstType }) });
            _log.LogDebug("Serialized {Count} ledger details, payload size: {Size} bytes", ledgerDetails.Count, payload.Length);
            var jsonContent = new StringContent(payload, Encoding.UTF8, "application/json");
            var syncResp = await invosync.PostAsync("/api/v3/sync/ledgers", jsonContent, ct);

            if (syncResp.IsSuccessStatusCode)
            {
                _log.LogInformation("✓ Synced {Count} Tally ledgers (with parent/GST type) to InvoSync", ledgerDetails.Count);
            }
            else
            {
                var errorBody = await syncResp.Content.ReadAsStringAsync(ct);
                _log.LogWarning("Backend rejected ledger sync: {Status} {Body}", syncResp.StatusCode, errorBody);
            }
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            _log.LogError(ex, "Ledger sync failed with exception");
        }
    }

    private static List<string> ParseSimpleLedgerNames(string xml)
    {
        var names = new List<string>();
        int idx = 0;
        while ((idx = xml.IndexOf("<NAME>", idx, StringComparison.Ordinal)) != -1)
        {
            int start = idx + 6;
            int end = xml.IndexOf("</NAME>", start, StringComparison.Ordinal);
            if (end == -1) break;
            var name = xml[start..end];
            if (!name.StartsWith("!")) names.Add(name);
            idx = end + 7;
        }
        return names;
    }
}
