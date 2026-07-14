using System.Net.Http.Json;
using System.Text;
using System.Text.Json;

namespace InvoSync.TallyConnector.Services;

/// <summary>
/// Pulls voucher data from Tally Prime via XML export request and
/// forwards extracted invoices to the InvoSync backend.
/// Uses the same Object/Export pattern as TallyLedgerSyncer.
/// </summary>
public class TallyRegisterPuller
{
    private readonly IHttpClientFactory _httpFactory;
    private readonly ILogger<TallyRegisterPuller> _log;

    public TallyRegisterPuller(IHttpClientFactory httpFactory, ILogger<TallyRegisterPuller> log)
    {
        _httpFactory = httpFactory;
        _log = log;
    }

    /// <summary>Pulls vouchers from Tally and posts them to the backend.</summary>
    public async Task<(int pulled, int posted)> PullAndSendAsync(
        string companyName, string? tallyPassword, CancellationToken ct,
        DateTime? fromDate = null, DateTime? toDate = null)
    {
        var tally = _httpFactory.CreateClient("Tally");

        var fromDateStr = fromDate.HasValue ? fromDate.Value.ToString("yyyyMMdd") : "";
        var toDateStr = toDate.HasValue ? toDate.Value.ToString("yyyyMMdd") : "";
        var dateXml = "";
        if (!string.IsNullOrEmpty(fromDateStr))
        {
            dateXml = $@"
<SVFROMDATE>{fromDateStr}</SVFROMDATE>
<SVTODATE>{(string.IsNullOrEmpty(toDateStr) ? fromDateStr : toDateStr)}</SVTODATE>";
        }

        // Build XML request — export voucher objects (no TDL needed)
        var requestXml = $@"<ENVELOPE>
<HEADER><VERSION>1</VERSION>{(string.IsNullOrEmpty(tallyPassword) ? "" : $"<PASSWORD>{tallyPassword}</PASSWORD>")}<TALLYREQUEST>Export</TALLYREQUEST><TYPE>Object</TYPE><DESC>
<STATICVARIABLES>
<SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>
<SVCURRENTCOMPANY>{EscapeXml(companyName)}</SVCURRENTCOMPANY>{dateXml}
</STATICVARIABLES>
</DESC></HEADER>
<BODY>
<DESC><TALLYREQUEST>Export Collection</TALLYREQUEST><TYPE>Voucher</TYPE></DESC>
</BODY>
</ENVELOPE>";

        try
        {
            var content = new StringContent(requestXml, Encoding.UTF8, "text/xml");
            var resp = await tally.PostAsync("", content, ct);
            if (!resp.IsSuccessStatusCode)
            {
                _log.LogWarning("Tally voucher pull returned {Status}", resp.StatusCode);
                return (0, 0);
            }

            var xml = await resp.Content.ReadAsStringAsync(ct);
            var vouchers = ParseVouchers(xml);
            _log.LogInformation("Pulled {Count} vouchers from Tally", vouchers.Count);
            if (vouchers.Count == 0) return (0, 0);

            // Post to backend
            var invosync = _httpFactory.CreateClient("InvoSync");
            var payload = JsonSerializer.Serialize(new { import_source = "tally_pull", vouchers });
            var jsonContent = new StringContent(payload, Encoding.UTF8, "application/json");
            var syncResp = await invosync.PostAsync("/api/v3/sync/import-from-tally", jsonContent, ct);

            if (syncResp.IsSuccessStatusCode)
            {
                var result = await syncResp.Content.ReadFromJsonAsync<JsonElement>(ct);
                var imported = result.TryGetProperty("imported", out var val) ? val.GetInt32() : 0;
                _log.LogInformation("Posted {Count} vouchers from Tally — {Imported} imported",
                    vouchers.Count, imported);
                return (vouchers.Count, imported);
            }

            _log.LogWarning("Backend rejected import: {Status}", syncResp.StatusCode);
            return (vouchers.Count, 0);
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            _log.LogDebug("Tally pull failed: {Message}", ex.Message);
            return (0, 0);
        }
    }

    private static List<Dictionary<string, object>> ParseVouchers(string xml)
    {
        var vouchers = new List<Dictionary<string, object>>();

        // Find each VOUCHER block using simple string parsing
        int idx = 0;
        while (true)
        {
            var vStart = xml.IndexOf("<VOUCHER", idx, StringComparison.Ordinal);
            if (vStart < 0) break;

            var vCloseTag = "</VOUCHER>";
            var vEnd = xml.IndexOf(vCloseTag, vStart, StringComparison.Ordinal);
            if (vEnd < 0) break;

            var block = xml[vStart..(vEnd + vCloseTag.Length)];

            var voucher = new Dictionary<string, object>
            {
                ["voucher_number"] = ExtractField(block, "VOUCHERNUMBER") ?? "",
                ["date"] = ExtractField(block, "DATE") ?? "",
                ["party_name"] = ExtractField(block, "PARTYNAME") ?? "",
                ["party_ledger"] = ExtractField(block, "PARTYLEDGERNAME") ?? "",
                ["amount"] = ParseDecimal(ExtractField(block, "VOUCHERTOTALAMOUNT") ?? "0"),
                ["voucher_type"] = ExtractField(block, "VOUCHERTYPENAME") ?? "Purchase",
                ["gstin"] = ExtractField(block, "PARTYGSTIN") ?? "",
            };

            vouchers.Add(voucher);
            idx = vEnd + vCloseTag.Length;
        }

        return vouchers;
    }

    private static string? ExtractField(string xml, string tag)
    {
        var open = $"<{tag}>";
        var close = $"</{tag}>";
        var start = xml.IndexOf(open, StringComparison.Ordinal);
        if (start < 0)
        {
            // Try with namespace
            open = $"<{tag} ";
            start = xml.IndexOf(open, StringComparison.Ordinal);
            if (start < 0) return null;
            start = xml.IndexOf(">", start, StringComparison.Ordinal);
            if (start < 0) return null;
            start++;
        }
        else
        {
            start += open.Length;
        }

        var end = xml.IndexOf(close, start, StringComparison.Ordinal);
        if (end < 0) return null;

        var val = xml[start..end].Trim();
        return val;
    }

    private static decimal ParseDecimal(string val)
    {
        if (decimal.TryParse(val, System.Globalization.NumberStyles.Any,
            System.Globalization.CultureInfo.InvariantCulture, out var d))
            return d;
        return 0;
    }

    private static string EscapeXml(string text)
    {
        if (string.IsNullOrEmpty(text)) return text;
        return text.Replace("&", "&amp;").Replace("<", "&lt;").Replace(">", "&gt;").Replace("\"", "&quot;");
    }
}
