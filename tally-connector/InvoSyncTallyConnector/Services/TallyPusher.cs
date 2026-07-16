using System.Text;
using System.Text.RegularExpressions;
using System.Xml.Linq;
using InvoSync.TallyConnector.Models;

namespace InvoSync.TallyConnector.Services;

public partial class TallyPusher
{
    private readonly IHttpClientFactory _httpFactory;
    private readonly ILogger<TallyPusher> _log;
    private readonly SemaphoreSlim _pushGate = new(1, 1);
    private Task? _activePush;
    private static readonly Regex _xmlDecl = XmlDeclRegex();
    private static readonly string _connectorVersion;
    private static readonly Regex _headerVersionTag = HeaderVersionTagRegex();

    [GeneratedRegex(@"^<\?xml\s+.*?\?>", RegexOptions.Compiled)]
    private static partial Regex XmlDeclRegex();

    [GeneratedRegex(@"(<VERSION>\d+</VERSION>)", RegexOptions.Compiled)]
    private static partial Regex HeaderVersionTagRegex();

    public TallyPusher(IHttpClientFactory httpFactory, ILogger<TallyPusher> log)
    {
        _httpFactory = httpFactory;
        _log = log;
    }

    static TallyPusher()
    {
        var asm = System.Reflection.Assembly.GetExecutingAssembly();
        var ver = asm.GetName().Version;
        _connectorVersion = ver != null
            ? $"{ver.Major}.{ver.Minor}.{ver.Build}"
            : "1.0.0";
    }

    /// <summary>Waits for the current push (if any) to complete, up to the given timeout.</summary>
    public async Task WaitForCurrentPushAsync(TimeSpan timeout)
    {
        if (_activePush == null || _activePush.IsCompleted) return;
        try { await _activePush.WaitAsync(timeout).ConfigureAwait(false); }
        catch (TimeoutException) { _log.LogWarning("Timed out waiting for in-flight push"); }
    }

    /// <summary>
    /// Pushes XML to Tally with retry (exponential backoff: 5s, 15s, 45s).
    /// If tallyPassword is provided, injects &lt;PASSWORD&gt; into the &lt;HEADER&gt;.
    /// Returns the result of the last attempt. Ensures only one push at a time.
    /// </summary>
    public async Task<TallyImportResult> PushAsync(string xml, CancellationToken ct, int maxRetries = 3, string? tallyPassword = null)
    {
        await _pushGate.WaitAsync(ct).ConfigureAwait(false);
        try
        {
            var pushTask = InternalPushAsync(xml, ct, maxRetries, tallyPassword);
            _activePush = pushTask;
            return await pushTask.ConfigureAwait(false);
        }
        finally
        {
            _pushGate.Release();
        }
    }

    private async Task<TallyImportResult> InternalPushAsync(string xml, CancellationToken ct, int maxRetries, string? tallyPassword)
    {
        var cleanXml = _xmlDecl.Replace(xml, "").Trim();
        cleanXml = InjectVersionTag(cleanXml);
        if (!string.IsNullOrEmpty(tallyPassword))
            cleanXml = InjectPassword(cleanXml, tallyPassword);
        var http = _httpFactory.CreateClient("Tally");

        for (int attempt = 1; attempt <= maxRetries; attempt++)
        {
            var content = new StringContent(cleanXml, Encoding.UTF8, "text/xml");
            try
            {
                var resp = await http.PostAsync("", content, ct).ConfigureAwait(false);
                var body = await resp.Content.ReadAsStringAsync(ct).ConfigureAwait(false);

                if (!resp.IsSuccessStatusCode)
                {
                    _log.LogWarning("Tally returned HTTP {Status} (attempt {A}/{M})", resp.StatusCode, attempt, maxRetries);
                    if (attempt < maxRetries) { await Backoff(attempt, ct); continue; }
                    return new TallyImportResult { Success = false, ErrorLine = $"HTTP {resp.StatusCode}" };
                }

                var error = ParseErrorLine(body);
                if (error == null)
                    return new TallyImportResult { Success = true, RawResponse = body };

                _log.LogWarning("Tally LINEERROR (attempt {A}/{M}): {Error}", attempt, maxRetries, error);
                if (attempt < maxRetries) { await Backoff(attempt, ct); continue; }
                return new TallyImportResult { Success = false, ErrorLine = error, RawResponse = body };
            }
            catch (Exception ex) when (ex is not OperationCanceledException)
            {
                _log.LogError(ex, "Tally push failed (attempt {A}/{M})", attempt, maxRetries);
                if (attempt < maxRetries) { await Backoff(attempt, ct); continue; }
                return new TallyImportResult { Success = false, ErrorLine = ex.Message };
            }
        }

        return new TallyImportResult { Success = false, ErrorLine = "Max retries exceeded" };
    }

    private static async Task Backoff(int attempt, CancellationToken ct)
    {
        var delay = TimeSpan.FromSeconds(Math.Pow(3, attempt - 1) * 5); // 5s, 15s, 45s
        await Task.Delay(delay, ct).ConfigureAwait(false);
    }

    private static string? ParseErrorLine(string xml)
    {
        try
        {
            var doc = XDocument.Parse(xml);
            return doc.Descendants("LINEERROR").FirstOrDefault()?.Value;
        }
        catch
        {
            return null;
        }
    }

    /// <summary>Deletes a voucher from Tally by voucher number and type.</summary>
    public async Task<TallyImportResult> UndoLastPushAsync(
        string voucherNumber, string voucherType, string date, string? tallyPassword, CancellationToken ct)
    {
        var deleteXml = $@"<ENVELOPE>
<HEADER><VERSION>1</VERSION>{(string.IsNullOrEmpty(tallyPassword) ? "" : $"<PASSWORD>{tallyPassword}</PASSWORD>")}<TALLYREQUEST>Import Data</TALLYREQUEST><TYPE>Data</TYPE></HEADER>
<BODY>
<IMPORTDATA>
<REQUESTDESC><REPORTNAME>Vouchers</REPORTNAME></REQUESTDESC>
<REQUESTDATA>
<TALLYMESSAGE xmlns:UDF=""TallyUDF"">
<VOUCHER VCHTYPE=""{EscapeXml(voucherType)}"" ACTION=""Delete"" OBJVIEW=""Invoice Voucher View"">
<DATE>{EscapeXml(date)}</DATE>
<VOUCHERNUMBER>{EscapeXml(voucherNumber)}</VOUCHERNUMBER>
</VOUCHER>
</TALLYMESSAGE>
</REQUESTDATA>
</IMPORTDATA>
</BODY>
</ENVELOPE>";
        return await PushAsync(deleteXml, ct, maxRetries: 2, tallyPassword: tallyPassword);
    }

    private static string EscapeXml(string s) =>
        s.Replace("&", "&amp;").Replace("<", "&lt;").Replace(">", "&gt;").Replace("\"", "&quot;").Replace("'", "&apos;");

    /// <summary>
    /// Injects &lt;CONNECTORVERSION&gt;xxx&lt;/CONNECTORVERSION&gt; after the &lt;VERSION&gt; tag.
    /// </summary>
    private static string InjectVersionTag(string xml)
    {
        var match = _headerVersionTag.Match(xml);
        if (match.Success)
        {
            var insertAt = match.Index + match.Length;
            return xml[..insertAt] + $"<CONNECTORVERSION>{_connectorVersion}</CONNECTORVERSION>" + xml[insertAt..];
        }
        return xml;
    }

    /// <summary>
    /// Injects &lt;PASSWORD&gt;xxx&lt;/PASSWORD&gt; into the &lt;HEADER&gt; of a Tally XML envelope.
    /// </summary>
    private static string InjectPassword(string xml, string password)
    {
        // Insert <PASSWORD> after <VERSION>...</VERSION> inside <HEADER>
        var versionEnd = "</VERSION>";
        var versionIdx = xml.IndexOf(versionEnd, StringComparison.Ordinal);
        if (versionIdx >= 0)
        {
            var insertAt = versionIdx + versionEnd.Length;
            return xml[..insertAt] + $"<PASSWORD>{password}</PASSWORD>" + xml[insertAt..];
        }
        // Fallback: insert after <HEADER>
        var headerStart = "<HEADER>";
        var headerIdx = xml.IndexOf(headerStart, StringComparison.Ordinal);
        if (headerIdx >= 0)
        {
            var insertAt = headerIdx + headerStart.Length;
            return xml[..insertAt] + $"<PASSWORD>{password}</PASSWORD>" + xml[insertAt..];
        }
        return xml;
    }
}
