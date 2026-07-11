namespace InvoSync.TallyConnector.Models;

public class TallyImportResult
{
    public bool Success { get; set; }
    public string? ErrorLine { get; set; }
    public string? RawResponse { get; set; }
}
