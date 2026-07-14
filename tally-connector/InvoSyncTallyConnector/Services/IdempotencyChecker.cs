using System.Net.Http.Json;
using System.Text;
using System.Text.Json;

namespace InvoSync.TallyConnector.Services;

public class IdempotencyChecker
{
    private readonly IHttpClientFactory _httpFactory;
    private readonly ILogger<IdempotencyChecker> _log;

    public IdempotencyChecker(IHttpClientFactory httpFactory, ILogger<IdempotencyChecker> log)
    {
        _httpFactory = httpFactory;
        _log = log;
    }

    public async Task<bool> IsDuplicateAsync(string vendorName, string invoiceNumber, double totalAmount, string invoiceDate, CancellationToken ct)
    {
        try
        {
            var payload = new
            {
                vendor_name = vendorName,
                invoice_number = invoiceNumber,
                total_amount = totalAmount,
                invoice_date = invoiceDate,
            };

            var json = JsonSerializer.Serialize(payload);
            using var content = new StringContent(json, Encoding.UTF8, "application/json");
            var client = _httpFactory.CreateClient("InvoSync");
            using var cts = CancellationTokenSource.CreateLinkedTokenSource(ct);
            cts.CancelAfter(TimeSpan.FromSeconds(10));
            var resp = await client.PostAsync("/api/v3/sync/check-duplicate", content, cts.Token);
            if (!resp.IsSuccessStatusCode) return false;

            var body = await resp.Content.ReadFromJsonAsync<DuplicateResponse>(cancellationToken: ct);
            return body?.Duplicate ?? false;
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            _log.LogDebug(ex, "Duplicate check failed");
            return false;
        }
    }
}

public class DuplicateResponse
{
    public bool Duplicate { get; set; }
    public int? InvoiceId { get; set; }
    public string Message { get; set; } = "";
}
