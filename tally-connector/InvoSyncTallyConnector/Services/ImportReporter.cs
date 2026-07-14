using System.Net.Http.Json;
using System.Text;
using System.Text.Json;

namespace InvoSync.TallyConnector.Services;

public class ImportReporter
{
    private readonly IHttpClientFactory _httpFactory;
    private readonly ILogger<ImportReporter> _log;

    public ImportReporter(IHttpClientFactory httpFactory, ILogger<ImportReporter> log)
    {
        _httpFactory = httpFactory;
        _log = log;
    }

    public async Task ReportAsync(int invoiceDisplayId, bool success, List<string> mastersCreated,
        string voucherId, string tallyResponse, List<string> warnings, string error, int durationMs, CancellationToken ct)
    {
        try
        {
            var payload = new ImportReportPayload
            {
                InvoiceDisplayId = invoiceDisplayId,
                Success = success,
                MastersCreated = mastersCreated,
                VoucherId = voucherId,
                TallyResponse = tallyResponse,
                Warnings = warnings,
                Error = error,
                ImportDurationMs = durationMs,
            };

            var json = JsonSerializer.Serialize(payload);
            using var content = new StringContent(json, Encoding.UTF8, "application/json");
            var client = _httpFactory.CreateClient("InvoSync");
            using var cts = CancellationTokenSource.CreateLinkedTokenSource(ct);
            cts.CancelAfter(TimeSpan.FromSeconds(10));
            var resp = await client.PostAsync("/api/v3/sync/import-report", content, cts.Token);
            if (!resp.IsSuccessStatusCode)
            {
                _log.LogWarning("Failed to report import result: HTTP {Status}", resp.StatusCode);
            }
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            _log.LogDebug(ex, "Import report failed");
        }
    }
}

public class ImportReportPayload
{
    public int InvoiceDisplayId { get; set; }
    public bool Success { get; set; }
    public List<string> MastersCreated { get; set; } = new();
    public string VoucherId { get; set; } = "";
    public string TallyResponse { get; set; } = "";
    public List<string> Warnings { get; set; } = new();
    public string Error { get; set; } = "";
    public int ImportDurationMs { get; set; }
}
