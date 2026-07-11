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

    /// <summary>
    /// Pushes XML to Tally with retry (exponential backoff: 5s, 15s, 45s).
    /// Returns the result of the last attempt.
    /// </summary>
    public async Task<TallyImportResult> PushAsync(string xml, CancellationToken ct, int maxRetries = 3)
    {
        var cleanXml = _xmlDecl.Replace(xml, "").Trim();
        var http = _httpFactory.CreateClient("Tally");

        for (int attempt = 1; attempt <= maxRetries; attempt++)
        {
            var content = new StringContent(cleanXml, Encoding.UTF8, "text/xml");
            try
            {
                var resp = await http.PostAsync("", content, ct);
                var body = await resp.Content.ReadAsStringAsync(ct);

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
        await Task.Delay(delay, ct);
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
