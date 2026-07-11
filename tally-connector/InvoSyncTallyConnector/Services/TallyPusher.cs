using System.Text;
using System.Text.RegularExpressions;
using System.Xml.Linq;
using InvoSync.TallyConnector.Models;

namespace InvoSync.TallyConnector.Services;

public partial class TallyPusher
{
    private readonly IHttpClientFactory _httpFactory;
    private readonly ILogger<TallyPusher> _log;

    private static readonly Regex _xmlDecl = XmlDeclRegex();

    [GeneratedRegex(@"^<\?xml\s+.*?\?>", RegexOptions.Compiled)]
    private static partial Regex XmlDeclRegex();

    public TallyPusher(IHttpClientFactory httpFactory, ILogger<TallyPusher> log)
    {
        _httpFactory = httpFactory;
        _log = log;
    }

    public async Task<TallyImportResult> PushAsync(string xml, CancellationToken ct)
    {
        // Strip XML declaration — Tally's parser doesn't handle it
        var cleanXml = _xmlDecl.Replace(xml, "").Trim();

        // The backend already returns fully-formed <ENVELOPE> block(s).
        // Tally accepts one or more concatenated <ENVELOPE> blocks in a single POST.
        // Do NOT wrap in another <ENVELOPE>.
        var http = _httpFactory.CreateClient("Tally");
        var content = new StringContent(cleanXml, Encoding.UTF8, "text/xml");

        try
        {
            var resp = await http.PostAsync("", content, ct);
            var body = await resp.Content.ReadAsStringAsync(ct);

            if (!resp.IsSuccessStatusCode)
            {
                _log.LogWarning("Tally returned HTTP {Status}: {Body}", resp.StatusCode, body[..Math.Min(body.Length, 500)]);
                return new TallyImportResult { Success = false, ErrorLine = $"HTTP {resp.StatusCode}" };
            }

            var error = ParseErrorLine(body);
            return new TallyImportResult
            {
                Success = error == null,
                ErrorLine = error,
                RawResponse = body,
            };
        }
        catch (Exception ex)
        {
            _log.LogError(ex, "Tally push failed — is Tally Prime running on port 9000?");
            return new TallyImportResult { Success = false, ErrorLine = ex.Message };
        }
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
}
