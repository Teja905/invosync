using System.Text;

namespace InvoSync.TallyConnector.Services;

public class TallyHealth
{
    public bool IsRunning { get; set; }
    public string ActiveCompany { get; set; } = "";
    public string Version { get; set; } = "";
    public string Error { get; set; } = "";
}

public class CompanyGuard
{
    private readonly IHttpClientFactory _httpFactory;
    private readonly ILogger<CompanyGuard> _log;
    private string _registeredCompany = "";

    public CompanyGuard(IHttpClientFactory httpFactory, ILogger<CompanyGuard> log)
    {
        _httpFactory = httpFactory;
        _log = log;
    }

    public void SetRegisteredCompany(string companyName)
    {
        _registeredCompany = companyName;
        _log.LogInformation("Registered company set to: {Company}", companyName);
    }

    public async Task<TallyHealth> CheckHealthAsync()
    {
        try
        {
            var xml = @"<ENVELOPE>
<HEADER><VERSION>1</VERSION><TALLYREQUEST>Export</TALLYREQUEST><TYPE>Company</TYPE><ID>List of Companies</ID></HEADER>
<BODY><DESC><STATICVARIABLES></STATICVARIABLES></DESC></BODY>
</ENVELOPE>";

            var tally = _httpFactory.CreateClient("Tally");
            var content = new StringContent(xml, Encoding.UTF8, "text/xml");
            using var cts = new CancellationTokenSource(TimeSpan.FromSeconds(5));
            var resp = await tally.PostAsync("", content, cts.Token);

            if (!resp.IsSuccessStatusCode)
                return new TallyHealth { IsRunning = false, Error = $"HTTP {resp.StatusCode}" };

            var body = await resp.Content.ReadAsStringAsync(cts.Token);
            var company = ParseActiveCompany(body);
            var version = ParseVersion(body);

            return new TallyHealth { IsRunning = true, ActiveCompany = company, Version = version };
        }
        catch (TaskCanceledException)
        {
            return new TallyHealth { IsRunning = false, Error = "Tally not responding" };
        }
        catch (HttpRequestException ex)
        {
            return new TallyHealth { IsRunning = false, Error = $"TallyPrime is not open: {ex.Message}" };
        }
        catch (Exception ex)
        {
            return new TallyHealth { IsRunning = false, Error = ex.Message };
        }
    }

    public async Task<bool> IsCorrectCompanyActiveAsync()
    {
        if (string.IsNullOrEmpty(_registeredCompany))
            return true;

        var health = await CheckHealthAsync();
        if (!health.IsRunning)
            return false;

        if (!CompanyNamesMatch(health.ActiveCompany, _registeredCompany))
        {
            _log.LogWarning("Company mismatch: expected '{Expected}', active '{Active}'",
                _registeredCompany, health.ActiveCompany);
            return false;
        }

        return true;
    }

    private static bool CompanyNamesMatch(string tallyName, string registeredName)
    {
        string Normalize(string s) =>
            System.Text.RegularExpressions.Regex.Replace(
                s.Trim().ToLowerInvariant(), @"\s+", " ");
        return Normalize(tallyName) == Normalize(registeredName);
    }

    private static string ParseActiveCompany(string xml)
    {
        var tag = "<ACTIVECOMPANY>";
        var start = xml.IndexOf(tag, StringComparison.Ordinal);
        if (start < 0) return "";
        start += tag.Length;
        var end = xml.IndexOf("</ACTIVECOMPANY>", start, StringComparison.Ordinal);
        return end < 0 ? "" : xml[start..end].Trim();
    }

    private static string ParseVersion(string xml)
    {
        var tag = "<VERSION>";
        var start = xml.IndexOf(tag, StringComparison.Ordinal);
        if (start < 0) return "";
        start += tag.Length;
        var end = xml.IndexOf("</VERSION>", start, StringComparison.Ordinal);
        return end < 0 ? "" : xml[start..end].Trim();
    }
}
