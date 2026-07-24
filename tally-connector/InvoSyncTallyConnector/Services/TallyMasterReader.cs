using System.Net.Http.Json;
using System.Text;
using System.Text.Json;

namespace InvoSync.TallyConnector.Services;

public record LedgerDetail(string Name, string Parent, string GstType);

public class TallyMasterReader
{
    private readonly IHttpClientFactory _httpFactory;
    private readonly ILogger<TallyMasterReader> _log;

    public TallyMasterReader(IHttpClientFactory httpFactory, ILogger<TallyMasterReader> log)
    {
        _httpFactory = httpFactory;
        _log = log;
    }

    public async Task<List<string>> GetLedgersAsync(string companyName, CancellationToken ct)
    {
        var tally = _httpFactory.CreateClient("Tally");
        var xml = $@"<ENVELOPE>
<HEADER><VERSION>1</VERSION><TALLYREQUEST>Export</TALLYREQUEST><TYPE>Object</TYPE><DESC>
<STATICVARIABLES>
<SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>
<SVCURRENTCOMPANY>{EscapeXml(companyName)}</SVCURRENTCOMPANY>
</STATICVARIABLES>
</DESC></HEADER>
<BODY>
<DESC><TALLYREQUEST>Export Collection</TALLYREQUEST><TYPE>Ledger</TYPE></DESC>
</BODY>
</ENVELOPE>";

        try
        {
            var content = new StringContent(xml, Encoding.UTF8, "text/xml");
            var resp = await tally.PostAsync("", content, ct);
            if (!resp.IsSuccessStatusCode) return new List<string>();
            var body = await resp.Content.ReadAsStringAsync(ct);
            return ParseNames(body);
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            _log.LogDebug(ex, "Failed to read ledgers from Tally");
            return new List<string>();
        }
    }

    public async Task<List<LedgerDetail>> GetLedgersWithDetailsAsync(string companyName, CancellationToken ct)
    {
        var tally = _httpFactory.CreateClient("Tally");
        var xml = $@"<ENVELOPE>
<HEADER><VERSION>1</VERSION><TALLYREQUEST>Export</TALLYREQUEST><TYPE>Object</TYPE><DESC>
<STATICVARIABLES>
<SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>
<SVCURRENTCOMPANY>{EscapeXml(companyName)}</SVCURRENTCOMPANY>
</STATICVARIABLES>
</DESC></HEADER>
<BODY>
<DESC><TALLYREQUEST>Export Collection</TALLYREQUEST><TYPE>Ledger</TYPE></DESC>
</BODY>
</ENVELOPE>";

        try
        {
            var content = new StringContent(xml, Encoding.UTF8, "text/xml");
            var resp = await tally.PostAsync("", content, ct);
            if (!resp.IsSuccessStatusCode) return new List<LedgerDetail>();
            var body = await resp.Content.ReadAsStringAsync(ct);
            return ParseLedgerDetails(body);
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            _log.LogDebug(ex, "Failed to read ledger details from Tally");
            return new List<LedgerDetail>();
        }
    }

    public async Task<List<string>> GetStockItemsAsync(string companyName, CancellationToken ct)
    {
        var tally = _httpFactory.CreateClient("Tally");
        var xml = $@"<ENVELOPE>
<HEADER><VERSION>1</VERSION><TALLYREQUEST>Export</TALLYREQUEST><TYPE>Object</TYPE><DESC>
<STATICVARIABLES>
<SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>
<SVCURRENTCOMPANY>{EscapeXml(companyName)}</SVCURRENTCOMPANY>
</STATICVARIABLES>
</DESC></HEADER>
<BODY>
<DESC><TALLYREQUEST>Export Collection</TALLYREQUEST><TYPE>Stock Item</TYPE></DESC>
</BODY>
</ENVELOPE>";

        try
        {
            var content = new StringContent(xml, Encoding.UTF8, "text/xml");
            var resp = await tally.PostAsync("", content, ct);
            if (!resp.IsSuccessStatusCode) return new List<string>();
            var body = await resp.Content.ReadAsStringAsync(ct);
            return ParseNames(body);
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            _log.LogDebug(ex, "Failed to read stock items from Tally");
            return new List<string>();
        }
    }

    public async Task<List<string>> GetVoucherTypesAsync(string companyName, CancellationToken ct)
    {
        var tally = _httpFactory.CreateClient("Tally");
        var xml = $@"<ENVELOPE>
<HEADER><VERSION>1</VERSION><TALLYREQUEST>Export</TALLYREQUEST><TYPE>Object</TYPE><DESC>
<STATICVARIABLES>
<SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>
<SVCURRENTCOMPANY>{EscapeXml(companyName)}</SVCURRENTCOMPANY>
</STATICVARIABLES>
</DESC></HEADER>
<BODY>
<DESC><TALLYREQUEST>Export Collection</TALLYREQUEST><TYPE>VoucherType</TYPE></DESC>
</BODY>
</ENVELOPE>";

        try
        {
            var content = new StringContent(xml, Encoding.UTF8, "text/xml");
            var resp = await tally.PostAsync("", content, ct);
            if (!resp.IsSuccessStatusCode) return new List<string>();
            var body = await resp.Content.ReadAsStringAsync(ct);
            return ParseNames(body);
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            _log.LogDebug(ex, "Failed to read voucher types from Tally");
            return new List<string>();
        }
    }

    public async Task<List<string>> GetGroupsAsync(string companyName, CancellationToken ct)
    {
        var tally = _httpFactory.CreateClient("Tally");
        var xml = $@"<ENVELOPE>
<HEADER><VERSION>1</VERSION><TALLYREQUEST>Export</TALLYREQUEST><TYPE>Object</TYPE><DESC>
<STATICVARIABLES>
<SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>
<SVCURRENTCOMPANY>{EscapeXml(companyName)}</SVCURRENTCOMPANY>
</STATICVARIABLES>
</DESC></HEADER>
<BODY>
<DESC><TALLYREQUEST>Export Collection</TALLYREQUEST><TYPE>Group</TYPE></DESC>
</BODY>
</ENVELOPE>";

        try
        {
            var content = new StringContent(xml, Encoding.UTF8, "text/xml");
            var resp = await tally.PostAsync("", content, ct);
            if (!resp.IsSuccessStatusCode) return new List<string>();
            var body = await resp.Content.ReadAsStringAsync(ct);
            return ParseNames(body);
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            _log.LogDebug(ex, "Failed to read groups from Tally");
            return new List<string>();
        }
    }

    public async Task<List<string>> GetUnitsAsync(string companyName, CancellationToken ct)
    {
        var tally = _httpFactory.CreateClient("Tally");
        var xml = $@"<ENVELOPE>
<HEADER><VERSION>1</VERSION><TALLYREQUEST>Export</TALLYREQUEST><TYPE>Object</TYPE><DESC>
<STATICVARIABLES>
<SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>
<SVCURRENTCOMPANY>{EscapeXml(companyName)}</SVCURRENTCOMPANY>
</STATICVARIABLES>
</DESC></HEADER>
<BODY>
<DESC><TALLYREQUEST>Export Collection</TALLYREQUEST><TYPE>Unit</TYPE></DESC>
</BODY>
</ENVELOPE>";

        try
        {
            var content = new StringContent(xml, Encoding.UTF8, "text/xml");
            var resp = await tally.PostAsync("", content, ct);
            if (!resp.IsSuccessStatusCode) return new List<string>();
            var body = await resp.Content.ReadAsStringAsync(ct);
            return ParseNames(body);
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            _log.LogDebug(ex, "Failed to read units from Tally");
            return new List<string>();
        }
    }

    private static List<string> ParseNames(string xml)
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

    private static List<LedgerDetail> ParseLedgerDetails(string xml)
    {
        var ledgers = new List<LedgerDetail>();
        int ledgerIdx = 0;
        while ((ledgerIdx = xml.IndexOf("<LEDGER>", ledgerIdx, StringComparison.Ordinal)) != -1)
        {
            int ledgerEnd = xml.IndexOf("</LEDGER>", ledgerIdx, StringComparison.Ordinal);
            if (ledgerEnd == -1) break;

            var block = xml.Substring(ledgerIdx, ledgerEnd - ledgerIdx + 9);
            var name = ExtractTag(block, "NAME");
            var parent = ExtractTag(block, "PARENT");
            var gstType = ExtractTag(block, "GSTTAXTYPE");

            if (!string.IsNullOrEmpty(name) && !name.StartsWith("!"))
                ledgers.Add(new LedgerDetail(name, parent ?? "", gstType ?? ""));
            ledgerIdx = ledgerEnd + 9;
        }
        return ledgers;
    }

    private static string? ExtractTag(string xml, string tag)
    {
        var open = $"<{tag}>";
        var close = $"</{tag}>";
        int start = xml.IndexOf(open, StringComparison.Ordinal);
        if (start == -1) return null;
        start += open.Length;
        int end = xml.IndexOf(close, start, StringComparison.Ordinal);
        if (end == -1) return null;
        return xml[start..end];
    }

    private static string EscapeXml(string s) =>
        s.Replace("&", "&amp;")
         .Replace("<", "&lt;")
         .Replace(">", "&gt;")
         .Replace("\"", "&quot;");
}
