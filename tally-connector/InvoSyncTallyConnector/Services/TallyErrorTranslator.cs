namespace InvoSync.TallyConnector.Services;

public static class TallyErrorTranslator
{
    private static readonly Dictionary<string, string> Translations = new(StringComparer.OrdinalIgnoreCase)
    {
        ["Object does not exist"] =
            "A ledger is missing in Tally. InvoSync will create it automatically.",

        ["Voucher is already present"] =
            "This invoice was already imported. Skipping to avoid duplicate.",

        ["Invalid date"] =
            "The invoice date was not accepted by Tally. Please check the date on the invoice.",

        ["Amount does not tally"] =
            "The debit and credit amounts do not balance. Please contact InvoSync support.",

        ["Company does not exist"] =
            "Wrong company selected in Settings. Please update company name to match TallyPrime exactly.",

        ["Ledger does not exist"] =
            "Ledger missing in Tally. InvoSync attempted to create it. Please try pushing again.",

        ["Duplicate voucher number"] =
            "A voucher with this number already exists in Tally. This invoice may have been imported before.",

        ["Access denied"] =
            "TallyPrime is locked. Please unlock Tally and try again.",

        ["Invalid TallyPrime License"] =
            "TallyPrime license issue. Please activate TallyPrime and try again.",

        ["Remote access not allowed"] =
            "Remote access is disabled in Tally. Enable it via F12 > Connectivity > Allow Remote Access.",
    };

    private static string _appVersion = "1.0.0";

    public static void SetAppVersion(string version) => _appVersion = version;

    public static string Translate(string rawError)
    {
        if (string.IsNullOrWhiteSpace(rawError))
            return "Unknown error. Please contact support.";

        foreach (var kvp in Translations)
        {
            if (rawError.Contains(kvp.Key, StringComparison.OrdinalIgnoreCase))
                return kvp.Value;
        }

        _ = ReportUnknownError(rawError);

        return $"Tally returned an error. Please contact support with code: {GenerateErrorCode(rawError)}";
    }

    private static string GenerateErrorCode(string error)
    {
        return Math.Abs(error.GetHashCode()).ToString()[..Math.Min(6, error.GetHashCode().ToString().Length)];
    }

    private static async Task ReportUnknownError(string error)
    {
        try
        {
            using var client = new HttpClient { Timeout = TimeSpan.FromSeconds(5) };
            var payload = new { error, version = _appVersion, timestamp = DateTime.UtcNow };
            var json = System.Text.Json.JsonSerializer.Serialize(payload);
            var content = new StringContent(json, System.Text.Encoding.UTF8, "application/json");
            await client.PostAsync(
                "https://invosync-backend-yjfa.onrender.com/api/v3/connector/unknown-error",
                content);
        }
        catch { }
    }
}
