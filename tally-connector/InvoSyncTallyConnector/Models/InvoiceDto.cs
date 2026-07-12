using System.Text.Json.Serialization;

namespace InvoSync.TallyConnector.Models;

public class InvoiceDto
{
    [JsonPropertyName("display_id")]
    public int DisplayId { get; set; }

    [JsonPropertyName("client_id")]
    public int ClientId { get; set; }

    [JsonPropertyName("invoice_number")]
    public string? InvoiceNumber { get; set; }

    [JsonPropertyName("vendor_name")]
    public string? VendorName { get; set; }

    [JsonPropertyName("voucher_type")]
    public string? VoucherType { get; set; }

    [JsonPropertyName("total_amount")]
    public decimal TotalAmount { get; set; }

    [JsonPropertyName("created_at")]
    public string? CreatedAt { get; set; }

    [JsonPropertyName("xml_content")]
    public string? XmlContent { get; set; }

    [JsonPropertyName("status")]
    public string? Status { get; set; }
}

public class PendingResponse
{
    [JsonPropertyName("count")]
    public int Count { get; set; }

    [JsonPropertyName("invoices")]
    public List<InvoiceDto> Invoices { get; set; } = new();
}
