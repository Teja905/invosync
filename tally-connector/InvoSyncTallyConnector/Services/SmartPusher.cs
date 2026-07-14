using System.Text;
using System.Text.RegularExpressions;

namespace InvoSync.TallyConnector.Services;

public class InvoiceXmlParts
{
    public string VoucherTypesXml { get; set; } = "";
    public string MastersXml { get; set; } = "";
    public string VoucherXml { get; set; } = "";
}

public partial class SmartPusher
{
    private readonly IHttpClientFactory _httpFactory;
    private readonly CompanyGuard _companyGuard;
    private readonly ILogger<SmartPusher> _log;
    private readonly IHttpClientFactory _httpClientFactory;
    private static readonly Regex _xmlDecl = XmlDeclRegex();

    [GeneratedRegex(@"^<\?xml\s+.*?\?>", RegexOptions.Compiled)]
    private static partial Regex XmlDeclRegex();

    public SmartPusher(IHttpClientFactory httpFactory, CompanyGuard companyGuard, ILogger<SmartPusher> log)
    {
        _httpFactory = httpFactory;
        _httpClientFactory = httpFactory;
        _companyGuard = companyGuard;
        _log = log;
    }

    public async Task<SmartPushResult> PushInvoiceAsync(InvoiceXmlParts parts, string? tallyPassword, CancellationToken ct)
    {
        // Step 1: Verify Tally health
        _log.LogInformation("Step 1: Checking Tally health...");
        var health = await _companyGuard.CheckHealthAsync();
        if (!health.IsRunning)
            return Fail("TallyPrime is not open or not responding", health.Error);

        // Step 2: Verify correct company
        _log.LogInformation("Step 2: Verifying company...");
        if (!await _companyGuard.IsCorrectCompanyActiveAsync())
            return Fail("Wrong company active in Tally",
                $"Expected company is not active. Active: {health.ActiveCompany}");

        // Step 3: Push voucher types
        if (!string.IsNullOrWhiteSpace(parts.VoucherTypesXml))
        {
            _log.LogInformation("Step 3: Pushing voucher types...");
            var vtResult = await PushXmlAsync(parts.VoucherTypesXml, tallyPassword, ct);
            if (!vtResult.Success)
                return Fail("Voucher type creation failed", vtResult.Error ?? "unknown");
            await Task.Delay(500, ct);
        }

        // Step 4: Push masters + verify each ledger committed
        if (!string.IsNullOrWhiteSpace(parts.MastersXml))
        {
            _log.LogInformation("Step 4: Pushing masters...");
            var mResult = await PushXmlAsync(parts.MastersXml, tallyPassword, ct);
            if (!mResult.Success)
                return Fail("Master creation failed", mResult.Error ?? "unknown");

            // Verify at least one known ledger committed before proceeding
            var verified = await VerifyTallyCommit("Purchase", 3000);
            if (!verified)
                _log.LogWarning("Master verification timed out — proceeding anyway");
            await Task.Delay(500, ct);
        }

        // Step 5: Push voucher
        _log.LogInformation("Step 5: Pushing voucher...");
        var vResult = await PushXmlAsync(parts.VoucherXml, tallyPassword, ct);
        if (vResult.Success)
        {
            _log.LogInformation("Invoice pushed successfully");
            return new SmartPushResult { Success = true };
        }

        var translated = TallyErrorTranslator.Translate(vResult.Error ?? "");
        return Fail("Voucher push failed", translated);
    }

    private async Task<SmartPushResult> PushXmlAsync(string xml, string? tallyPassword, CancellationToken ct)
    {
        var cleanXml = _xmlDecl.Replace(xml, "").Trim();
        if (!string.IsNullOrEmpty(tallyPassword))
            cleanXml = InjectPassword(cleanXml, tallyPassword);

        var http = _httpFactory.CreateClient("Tally");
        var content = new StringContent(cleanXml, Encoding.UTF8, "text/xml");

        try
        {
            var resp = await http.PostAsync("", content, ct);
            var body = await resp.Content.ReadAsStringAsync(ct);

            if (!resp.IsSuccessStatusCode)
                return new SmartPushResult { Success = false, Error = $"HTTP {resp.StatusCode}" };

            var lineError = ParseLineError(body);
            if (lineError != null)
                return new SmartPushResult { Success = false, Error = lineError };

            return new SmartPushResult { Success = true };
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            return new SmartPushResult { Success = false, Error = ex.Message };
        }
    }

    private static string? ParseLineError(string xml)
    {
        try
        {
            var start = xml.IndexOf("<LINEERROR>", StringComparison.Ordinal);
            if (start < 0) return null;
            start += 11;
            var end = xml.IndexOf("</LINEERROR>", start, StringComparison.Ordinal);
            return end < 0 ? null : xml[start..end].Trim();
        }
        catch
        {
            return null;
        }
    }

    private static string InjectPassword(string xml, string password)
    {
        var versionEnd = "</VERSION>";
        var idx = xml.IndexOf(versionEnd, StringComparison.Ordinal);
        if (idx >= 0)
            return xml[..(idx + versionEnd.Length)] + $"<PASSWORD>{password}</PASSWORD>" + xml[(idx + versionEnd.Length)..];
        var headerStart = "<HEADER>";
        var hIdx = xml.IndexOf(headerStart, StringComparison.Ordinal);
        if (hIdx >= 0)
            return xml[..(hIdx + headerStart.Length)] + $"<PASSWORD>{password}</PASSWORD>" + xml[(hIdx + headerStart.Length)..];
        return xml;
    }

    private async Task<bool> VerifyTallyCommit(string ledgerName, int maxWaitMs = 3000)
    {
        var start = DateTime.Now;
        while ((DateTime.Now - start).TotalMilliseconds < maxWaitMs)
        {
            if (await LedgerExistsInTally(ledgerName))
                return true;
            await Task.Delay(500, CancellationToken.None);
        }
        return false;
    }

    private async Task<bool> LedgerExistsInTally(string ledgerName)
    {
        try
        {
            var exportXml = @"<ENVELOPE>
<HEADER><TALLYREQUEST>Export Data</TALLYREQUEST></HEADER>
<BODY><EXPORTDATA><REQUESTDESC>
<REPORTNAME>List of Accounts</REPORTNAME>
<STATICVARIABLES>
<SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>
</STATICVARIABLES>
</REQUESTDESC></EXPORTDATA></BODY>
</ENVELOPE>";
            var tally = _httpClientFactory.CreateClient("Tally");
            var content = new StringContent(exportXml, Encoding.UTF8, "text/xml");
            using var cts = new CancellationTokenSource(TimeSpan.FromSeconds(5));
            var resp = await tally.PostAsync("", content, cts.Token).ConfigureAwait(false);
            if (!resp.IsSuccessStatusCode) return false;
            var body = await resp.Content.ReadAsStringAsync().ConfigureAwait(false);
            return body.Contains(ledgerName, StringComparison.OrdinalIgnoreCase);
        }
        catch { return false; }
    }

    private static SmartPushResult Fail(string stage, string detail)
    {
        return new SmartPushResult { Success = false, Error = $"{stage}: {detail}" };
    }
}

public class SmartPushResult
{
    public bool Success { get; set; }
    public string? Error { get; set; }

    public static SmartPushResult SuccessResult() => new() { Success = true };
    public static SmartPushResult Failed(string error) => new() { Success = false, Error = error };
}
