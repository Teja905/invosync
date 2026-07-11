using System.Text;
using System.Text.Json;

namespace InvoSync.TallyConnector.Services;

public class TallyLedgerSyncer
{
    private readonly IHttpClientFactory _httpFactory;
    private readonly ILogger<TallyLedgerSyncer> _log;

    public TallyLedgerSyncer(IHttpClientFactory httpFactory, ILogger<TallyLedgerSyncer> log)
    {
        _httpFactory = httpFactory;
        _log = log;
    }

    public async Task SyncLedgerListAsync(CancellationToken ct)
    {
        var tally = _httpFactory.CreateClient("Tally");
        var requestXml = @"<ENVELOPE>
<HEADER><VERSION>1</VERSION><TALLYREQUEST>Export</TALLYREQUEST><TYPE>Object</TYPE><DESC>
<STATICVARIABLES>
<SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>
</STATICVARIABLES>
</DESC></HEADER>
<BODY>
<DESC><TALLYREQUEST>Export Collection</TALLYREQUEST><TYPE>Ledger</TYPE></DESC>
</BODY>
</ENVELOPE>";

        try
        {
            var content = new StringContent(requestXml, Encoding.UTF8, "text/xml");
            var resp = await tally.PostAsync("", content, ct);
            if (!resp.IsSuccessStatusCode) return;

            var xml = await resp.Content.ReadAsStringAsync(ct);
            var ledgers = ParseLedgerNames(xml);

            if (ledgers.Count == 0) return;

            var payload = JsonSerializer.Serialize(new { ledgers });
            var jsonContent = new StringContent(payload, Encoding.UTF8, "application/json");
            var invosync = _httpFactory.CreateClient("InvoSync");
            var syncResp = await invosync.PostAsync("/api/v3/sync/ledgers", jsonContent, ct);

            if (syncResp.IsSuccessStatusCode)
                _log.LogInformation("Synced {Count} Tally ledgers to InvoSync", ledgers.Count);
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            _log.LogDebug("Ledger sync skipped: {Message}", ex.Message);
        }
    }

    private static List<string> ParseLedgerNames(string xml)
    {
        var ledgers = new List<string>();
        int idx = 0;
        while ((idx = xml.IndexOf("<NAME>", idx, StringComparison.Ordinal)) != -1)
        {
            int start = idx + 6;
            int end = xml.IndexOf("</NAME>", start, StringComparison.Ordinal);
            if (end == -1) break;
            var name = xml[start..end];
            // Skip system groups
            if (!name.StartsWith("!")) ledgers.Add(name);
            idx = end + 7;
        }
        return ledgers;
    }
}
