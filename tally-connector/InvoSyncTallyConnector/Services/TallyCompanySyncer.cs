using System.Text;
using System.Text.Json;

namespace InvoSync.TallyConnector.Services;

public class TallyCompanySyncer
{
    private readonly IHttpClientFactory _httpFactory;
    private readonly ILogger<TallyCompanySyncer> _log;

    public TallyCompanySyncer(IHttpClientFactory httpFactory, ILogger<TallyCompanySyncer> log)
    {
        _httpFactory = httpFactory;
        _log = log;
    }

    /// <summary>Pings Tally port 9000 with a harmless list-companies request.</summary>
    public async Task<bool> RunStartupDiagnosticCheckAsync(CancellationToken ct)
    {
        string pingXml = @"<ENVELOPE>
<HEADER><VERSION>1</VERSION><TALLYREQUEST>Export Data</TALLYREQUEST><TYPE>Company</TYPE><ID>List of Companies</ID></HEADER>
<BODY><DESC></DESC></BODY>
</ENVELOPE>";

        try
        {
            var tally = _httpFactory.CreateClient("Tally");
            var content = new StringContent(pingXml, Encoding.UTF8, "text/xml");
            using var cts = CancellationTokenSource.CreateLinkedTokenSource(ct);
            cts.CancelAfter(TimeSpan.FromSeconds(5));
            var response = await tally.PostAsync("", content, cts.Token);

            if (response.IsSuccessStatusCode)
            {
                var body = await response.Content.ReadAsStringAsync(ct);
                if (body.Contains("<ENVELOPE>"))
                {
                    _log.LogInformation("Tally Prime port 9000 diagnostic: CONNECTED");
                    return true;
                }
            }
            _log.LogWarning("Tally Prime port 9000 diagnostic: unexpected response");
            return false;
        }
        catch (OperationCanceledException)
        {
            _log.LogWarning("Tally Prime port 9000 diagnostic: TIMEOUT (5s) — Tally unresponsive");
            return false;
        }
        catch (Exception ex)
        {
            _log.LogWarning("Tally Prime port 9000 diagnostic: FAILED — {Message}", ex.Message);
            return false;
        }
    }

    /// <summary>Reports connector liveness to backend, even when Tally is offline.</summary>
    public async Task ReportConnectorAliveAsync(bool tallyReachable, CancellationToken ct, List<string>? companies = null)
    {
        try
        {
            var payload = JsonSerializer.Serialize(new
            {
                tally_reachable = tallyReachable,
                companies = companies ?? new List<string>(),
                connector_version = "1.0.0",
            });
            var jsonContent = new StringContent(payload, Encoding.UTF8, "application/json");
            var invosync = _httpFactory.CreateClient("InvoSync");
            var resp = await invosync.PostAsync("/api/v3/sync/companies", jsonContent, ct);
            if (resp.IsSuccessStatusCode)
                _log.LogDebug("Connector health reported (tally={R})", tallyReachable);
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            _log.LogDebug("Health report failed: {Message}", ex.Message);
        }
    }

    public async Task SyncOpenCompaniesAsync(CancellationToken ct)
    {
        var tally = _httpFactory.CreateClient("Tally");
        var requestXml = @"<ENVELOPE>
<HEADER><VERSION>1</VERSION><TALLYREQUEST>Export Data</TALLYREQUEST><TYPE>Company</TYPE><ID>List of Companies</ID></HEADER>
<BODY><DESC><STATICVARIABLES></STATICVARIABLES></DESC></BODY>
</ENVELOPE>";

        try
        {
            var content = new StringContent(requestXml, Encoding.UTF8, "text/xml");
            var resp = await tally.PostAsync("", content, ct);
            if (!resp.IsSuccessStatusCode)
            {
                _log.LogWarning("Tally company list request failed: {Status}", resp.StatusCode);
                return;
            }

            var xml = await resp.Content.ReadAsStringAsync(ct);
            var companies = ParseTallyCompanies(xml);

            if (companies.Count == 0)
            {
                _log.LogDebug("No companies found in Tally response");
                return;
            }

            var payload = JsonSerializer.Serialize(new { companies });
            var jsonContent = new StringContent(payload, Encoding.UTF8, "application/json");
            var invosync = _httpFactory.CreateClient("InvoSync");
            var syncResp = await invosync.PostAsync("/api/v3/sync/companies", jsonContent, ct);

            if (syncResp.IsSuccessStatusCode)
                _log.LogInformation("Synced {Count} Tally companies to InvoSync", companies.Count);
            else
                _log.LogWarning("Company sync rejected: {Status}", syncResp.StatusCode);
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            _log.LogDebug("Tally offline: {Message}", ex.Message);
        }
    }

    private static List<string> ParseTallyCompanies(string xml)
    {
        var companies = new List<string>();
        int idx = 0;
        while ((idx = xml.IndexOf("<NAME>", idx, StringComparison.Ordinal)) != -1)
        {
            int start = idx + 6;
            int end = xml.IndexOf("</NAME>", start, StringComparison.Ordinal);
            if (end == -1) break;
            companies.Add(xml[start..end]);
            idx = end + 7;
        }
        return companies;
    }
}
