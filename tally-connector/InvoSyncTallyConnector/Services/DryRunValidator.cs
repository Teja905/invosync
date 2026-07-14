using System.Net.Http.Json;
using System.Text;
using System.Text.Json;

namespace InvoSync.TallyConnector.Services;

public class DryRunValidator
{
    private readonly IHttpClientFactory _httpFactory;
    private readonly ILogger<DryRunValidator> _log;

    public DryRunValidator(IHttpClientFactory httpFactory, ILogger<DryRunValidator> log)
    {
        _httpFactory = httpFactory;
        _log = log;
    }

    public async Task<DryRunResult> ValidateAsync(string companyName, object invoiceData, CancellationToken ct)
    {
        var result = new DryRunResult
        {
            SafeToImport = true,
            Checks = new List<DryRunCheck>(),
            Warnings = new List<string>(),
            MastersToCreate = new List<string>(),
            ExistingMasters = new List<string>(),
        };

        var json = JsonSerializer.Serialize(invoiceData);
        using var content = new StringContent(json, Encoding.UTF8, "application/json");
        var client = _httpFactory.CreateClient("InvoSync");

        try
        {
            using var cts = CancellationTokenSource.CreateLinkedTokenSource(ct);
            cts.CancelAfter(TimeSpan.FromSeconds(15));
            var resp = await client.PostAsync("/api/v3/sync/dry-run", content, cts.Token);
            if (!resp.IsSuccessStatusCode)
            {
                result.Checks.Add(new DryRunCheck { Passed = false, Message = $"Backend dry-run failed: HTTP {(int)resp.StatusCode}" });
                result.SafeToImport = false;
                return result;
            }

            var body = await resp.Content.ReadFromJsonAsync<DryRunResponse>(cancellationToken: ct);
            if (body == null)
            {
                result.Checks.Add(new DryRunCheck { Passed = false, Message = "Invalid response from backend" });
                result.SafeToImport = false;
                return result;
            }

            result.SafeToImport = body.SafeToImport;
            result.DuplicateFound = body.DuplicateFound;
            result.DuplicateInvoiceId = body.DuplicateInvoiceId;
            result.MastersToCreate = body.MastersToCreate ?? new List<string>();
            result.ExistingMasters = body.ExistingMasters ?? new List<string>();
            result.Warnings = body.Warnings ?? new List<string>();

            foreach (var c in body.Checks ?? new List<DryRunCheck>())
            {
                result.Checks.Add(new DryRunCheck { Passed = c.Passed, Message = c.Message });
                if (!c.Passed) result.SafeToImport = false;
            }

            return result;
        }
        catch (OperationCanceledException)
        {
            result.Checks.Add(new DryRunCheck { Passed = false, Message = "Dry-run timed out" });
            result.SafeToImport = false;
            return result;
        }
        catch (Exception ex)
        {
            _log.LogError(ex, "Dry-run validation failed");
            result.Checks.Add(new DryRunCheck { Passed = false, Message = $"Dry-run error: {ex.Message}" });
            result.SafeToImport = false;
            return result;
        }
    }
}

public class DryRunResult
{
    public bool SafeToImport { get; set; }
    public List<DryRunCheck> Checks { get; set; }
    public List<string> Warnings { get; set; }
    public List<string> MastersToCreate { get; set; }
    public List<string> ExistingMasters { get; set; }
    public bool DuplicateFound { get; set; }
    public int? DuplicateInvoiceId { get; set; }
}

public class DryRunCheck
{
    public bool Passed { get; set; }
    public string Message { get; set; } = "";
}

public class DryRunResponse
{
    public bool SafeToImport { get; set; }
    public List<DryRunCheck> Checks { get; set; } = new();
    public List<string> Warnings { get; set; } = new();
    public List<string> MastersToCreate { get; set; } = new();
    public List<string> ExistingMasters { get; set; } = new();
    public bool DuplicateFound { get; set; }
    public int? DuplicateInvoiceId { get; set; }
}
