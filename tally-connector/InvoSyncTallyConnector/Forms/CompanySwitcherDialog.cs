using System.Net.Http.Json;
using System.Text;
using System.Text.Json;

namespace InvoSync.TallyConnector.Forms;

public class CompanySwitcherDialog : Form
{
    private readonly IHttpClientFactory _httpFactory;
    private readonly ILogger _log;
    private ListBox _companyList = null!;
    private Button _switchBtn = null!, _refreshBtn = null!, _cancelBtn = null!;
    private Label _statusLabel = null!;
    private List<string> _companies = new();
    private string _activeCompany = "";

    public string SelectedCompany { get; private set; } = "";

    private static readonly Color BgDark = Color.FromArgb(13, 17, 23);
    private static readonly Color BgCard = Color.FromArgb(22, 27, 34);
    private static readonly Color TextPrimary = Color.FromArgb(230, 237, 243);
    private static readonly Color TextSecondary = Color.FromArgb(139, 148, 158);
    private static readonly Color AccentGreen = Color.FromArgb(0, 200, 150);
    private static readonly Color AccentBlue = Color.FromArgb(88, 166, 255);

    public CompanySwitcherDialog(IHttpClientFactory httpFactory, string currentCompany, ILogger log)
    {
        _httpFactory = httpFactory;
        _activeCompany = currentCompany;
        _log = log;
        InitializeComponent();
        _ = LoadCompaniesAsync();
    }

    private void InitializeComponent()
    {
        Text = "Switch Company";
        Size = new Size(420, 360);
        StartPosition = FormStartPosition.CenterParent;
        FormBorderStyle = FormBorderStyle.FixedDialog;
        MaximizeBox = false;
        MinimizeBox = false;
        BackColor = BgDark;
        ForeColor = TextPrimary;
        Font = new Font("Segoe UI", 10);

        var root = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            RowCount = 4,
            ColumnCount = 1,
            Padding = new Padding(16),
        };
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));

        // Header
        var header = new Label
        {
            Text = $"Current: {_activeCompany}",
            Font = new Font("Segoe UI", 11, FontStyle.Bold),
            ForeColor = AccentGreen,
            AutoSize = true,
            Margin = new Padding(0, 0, 0, 8),
        };
        root.Controls.Add(header, 0, 0);

        // Company list
        _companyList = new ListBox
        {
            Dock = DockStyle.Fill,
            BackColor = BgCard,
            ForeColor = TextPrimary,
            BorderStyle = BorderStyle.FixedSingle,
            Font = new Font("Segoe UI", 10),
            IntegralHeight = false,
        };
        root.Controls.Add(_companyList, 0, 1);

        // Status
        _statusLabel = new Label
        {
            Text = "",
            ForeColor = TextSecondary,
            AutoSize = true,
            Margin = new Padding(0, 6, 0, 6),
        };
        root.Controls.Add(_statusLabel, 0, 2);

        // Buttons
        var btnPanel = new FlowLayoutPanel
        {
            Dock = DockStyle.Fill,
            FlowDirection = FlowDirection.RightToLeft,
            BackColor = Color.Transparent,
        };

        _switchBtn = new Button
        {
            Text = "Switch",
            BackColor = Color.FromArgb(0, 120, 80),
            ForeColor = TextPrimary,
            FlatStyle = FlatStyle.Flat,
            AutoSize = true,
            Height = 32,
            Padding = new Padding(16, 0, 16, 0),
            Cursor = Cursors.Hand,
            Font = new Font("Segoe UI", 10, FontStyle.Bold),
            Enabled = false,
        };
        _switchBtn.FlatAppearance.BorderSize = 0;
        _switchBtn.Click += async (_, _) => await SwitchCompanyAsync();

        _refreshBtn = new Button
        {
            Text = "Refresh",
            BackColor = Color.FromArgb(33, 38, 45),
            ForeColor = TextPrimary,
            FlatStyle = FlatStyle.Flat,
            AutoSize = true,
            Height = 32,
            Padding = new Padding(12, 0, 12, 0),
            Cursor = Cursors.Hand,
            Margin = new Padding(0, 0, 6, 0),
        };
        _refreshBtn.FlatAppearance.BorderSize = 0;
        _refreshBtn.Click += async (_, _) => await LoadCompaniesAsync();

        _cancelBtn = new Button
        {
            Text = "Cancel",
            BackColor = Color.FromArgb(33, 38, 45),
            ForeColor = TextPrimary,
            FlatStyle = FlatStyle.Flat,
            AutoSize = true,
            Height = 32,
            Padding = new Padding(12, 0, 12, 0),
            Cursor = Cursors.Hand,
            Margin = new Padding(0, 0, 6, 0),
        };
        _cancelBtn.FlatAppearance.BorderSize = 0;
        _cancelBtn.Click += (_, _) => Close();

        btnPanel.Controls.AddRange([_switchBtn, _refreshBtn, _cancelBtn]);
        root.Controls.Add(btnPanel, 0, 3);

        _companyList.SelectedIndexChanged += (_, _) =>
        {
            _switchBtn.Enabled = _companyList.SelectedItem != null;
        };

        Controls.Add(root);
    }

    private async Task LoadCompaniesAsync()
    {
        _statusLabel.Text = "Loading companies...";
        _refreshBtn.Enabled = false;

        try
        {
            var invosync = _httpFactory.CreateClient("InvoSync");
            var resp = await invosync.GetAsync("/api/v3/sync/companies");

            if (resp.IsSuccessStatusCode)
            {
                var json = await resp.Content.ReadFromJsonAsync<JsonElement>();
                if (json.TryGetProperty("companies", out var arr))
                {
                    _companies = arr.EnumerateArray().Select(c => c.GetString() ?? "").Where(c => !string.IsNullOrEmpty(c)).ToList();
                }
            }

            // Fallback: fetch from Tally directly
            if (_companies.Count == 0)
            {
                // Try TallyCompanySyncer-style approach
                var tally = _httpFactory.CreateClient("Tally");
                var requestXml = @"<ENVELOPE>
<HEADER><VERSION>1</VERSION><TALLYREQUEST>Export</TALLYREQUEST><TYPE>Company</TYPE><ID>List of Companies</ID></HEADER>
<BODY><DESC><STATICVARIABLES></STATICVARIABLES></DESC></BODY>
</ENVELOPE>";
                var content = new StringContent(requestXml, Encoding.UTF8, "text/xml");
                var tallyResp = await tally.PostAsync("", content);
                if (tallyResp.IsSuccessStatusCode)
                {
                    var xml = await tallyResp.Content.ReadAsStringAsync();
                    _companies = ParseTallyCompanies(xml);
                }
            }
        }
        catch (Exception ex)
        {
            _log?.LogWarning("Failed to load companies: {Message}", ex.Message);
            _statusLabel.Text = "Failed to load companies";
        }

        _companyList.Items.Clear();
        foreach (var c in _companies)
        {
            var display = c == _activeCompany ? $"{c} (current)" : c;
            _companyList.Items.Add(display);
            if (c == _activeCompany)
                _companyList.SelectedIndex = _companyList.Items.Count - 1;
        }

        _statusLabel.Text = $"{_companies.Count} company(ies) found";
        _refreshBtn.Enabled = true;
    }

    private async Task SwitchCompanyAsync()
    {
        var idx = _companyList.SelectedIndex;
        if (idx < 0 || idx >= _companies.Count) return;

        var selected = _companies[idx];
        if (selected == _activeCompany)
        {
            MessageBox.Show("Already on this company.", "Same Company", MessageBoxButtons.OK, MessageBoxIcon.Information);
            return;
        }

        _switchBtn.Enabled = false;
        _switchBtn.Text = "Switching...";

        try
        {
            var invosync = _httpFactory.CreateClient("InvoSync");
            var payload = JsonContent.Create(new { active_company = selected });
            var resp = await invosync.PostAsync("/api/v3/tally/config/company", payload);

            if (resp.IsSuccessStatusCode)
            {
                SelectedCompany = selected;
                _log?.LogInformation("Switched to company: {Company}", selected);
                Close();
            }
            else
            {
                var body = await resp.Content.ReadAsStringAsync();
                _statusLabel.Text = $"Switch failed: {(string.IsNullOrEmpty(body) ? resp.StatusCode.ToString() : body)}";
                _switchBtn.Enabled = true;
                _switchBtn.Text = "Switch";
            }
        }
        catch (Exception ex)
        {
            _log?.LogError(ex, "Company switch failed");
            _statusLabel.Text = $"Error: {ex.Message}";
            _switchBtn.Enabled = true;
            _switchBtn.Text = "Switch";
        }
    }

    private static List<string> ParseTallyCompanies(string xml)
    {
        var companies = new List<string>();
        int idx = 0;
        while ((idx = xml.IndexOf("<NAME>", idx, StringComparison.Ordinal)) != -1)
        {
            int start = idx + 6;
            int end = xml.IndexOf("</NAME>", start, StringComparison.Ordinal);
            if (end == -1) break;
            companies.Add(xml[start..end]);
            idx = end + 7;
        }
        return companies;
    }
}
