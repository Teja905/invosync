using System.Diagnostics;
using System.Net.Http.Json;
using System.Text;
using System.Text.Json;
using InvoSync.TallyConnector.Models;
using InvoSync.TallyConnector.Services;

namespace InvoSync.TallyConnector;

public class MainForm : Form
{
    // Services
    private readonly IHttpClientFactory _httpFactory;
    private readonly TallyPusher _pusher;
    private readonly QueueManager _queue;
    private readonly TallyCompanySyncer _companySyncer;
    private readonly ILogger<MainForm> _log;

    // UI Controls
    private ComboBox _companyCombo;
    private Button _refreshBtn;
    private DataGridView _pendingGrid;
    private Button _sendSelectedBtn;
    private Button _sendAllBtn;
    private ListBox _historyBox;
    private Label _statusLabel;
    private NotifyIcon _trayIcon;
    private ContextMenuStrip _trayMenu;
    private System.Windows.Forms.Timer _pollTimer;
    private Label _companyStatusLabel;

    // Data
    private List<InvoiceDto> _pendingInvoices = new();
    private readonly string _crashLog;

    public MainForm(IHttpClientFactory httpFactory, TallyPusher pusher, QueueManager queue,
        TallyCompanySyncer companySyncer, ILogger<MainForm> log)
    {
        _httpFactory = httpFactory;
        _pusher = pusher;
        _queue = queue;
        _companySyncer = companySyncer;
        _log = log;
        _crashLog = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "connector-crash.log");

        InitializeComponent();
        SetupTrayIcon();
        _pollTimer.Start();
        _ = RefreshAllAsync();
    }

    private void InitializeComponent()
    {
        Text = "InvoSync Tally Connector";
        Size = new Size(900, 650);
        MinimumSize = new Size(700, 500);
        StartPosition = FormStartPosition.CenterScreen;
        BackColor = Color.FromArgb(30, 30, 30);
        ForeColor = Color.White;
        Font = new Font("Segoe UI", 10);

        var mainPanel = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            Padding = new Padding(12),
            ColumnCount = 1,
            RowCount = 5,
        };
        mainPanel.RowStyles.Add(new RowStyle(SizeType.Absolute, 40));  // Header
        mainPanel.RowStyles.Add(new RowStyle(SizeType.Absolute, 45));  // Company picker
        mainPanel.RowStyles.Add(new RowStyle(SizeType.Percent, 50));   // Pending grid
        mainPanel.RowStyles.Add(new RowStyle(SizeType.Percent, 35));   // History
        mainPanel.RowStyles.Add(new RowStyle(SizeType.Absolute, 35));  // Status bar

        // Header
        var header = new Label
        {
            Text = "InvoSync Tally Connector",
            Font = new Font("Segoe UI", 14, FontStyle.Bold),
            ForeColor = Color.FromArgb(0, 200, 150),
            Dock = DockStyle.Fill,
            TextAlign = ContentAlignment.MiddleLeft,
        };
        mainPanel.Controls.Add(header, 0, 0);

        // Company picker row
        var companyPanel = new FlowLayoutPanel
        {
            Dock = DockStyle.Fill,
            FlowDirection = FlowDirection.LeftToRight,
            Padding = new Padding(0, 5, 0, 5),
        };

        companyPanel.Controls.Add(new Label
        {
            Text = "Target Tally Company:",
            AutoSize = true,
            Anchor = AnchorStyles.Left,
            ForeColor = Color.LightGray,
        });

        _companyCombo = new ComboBox
        {
            Width = 300,
            DropDownStyle = ComboBoxStyle.DropDownList,
            BackColor = Color.FromArgb(50, 50, 50),
            ForeColor = Color.White,
            FlatStyle = FlatStyle.Flat,
        };
        companyPanel.Controls.Add(_companyCombo);

        _companyStatusLabel = new Label
        {
            Text = "🟡 Checking...",
            AutoSize = true,
            Anchor = AnchorStyles.Left,
            ForeColor = Color.Yellow,
            Margin = new Padding(10, 5, 0, 0),
        };
        companyPanel.Controls.Add(_companyStatusLabel);

        _refreshBtn = new Button
        {
            Text = "⟳ Refresh",
            BackColor = Color.FromArgb(60, 60, 60),
            ForeColor = Color.White,
            FlatStyle = FlatStyle.Flat,
            AutoSize = true,
            Margin = new Padding(10, 2, 0, 2),
            Cursor = Cursors.Hand,
        };
        _refreshBtn.Click += async (_, _) => await RefreshAllAsync();
        companyPanel.Controls.Add(_refreshBtn);

        mainPanel.Controls.Add(companyPanel, 0, 1);

        // Pending invoices section
        var pendingPanel = new Panel { Dock = DockStyle.Fill };
        var pendingLabel = new Label
        {
            Text = "Pending Invoices",
            Font = new Font("Segoe UI", 11, FontStyle.Bold),
            ForeColor = Color.LightGray,
            Dock = DockStyle.Top,
            Height = 25,
        };

        var pendingActions = new FlowLayoutPanel
        {
            Dock = DockStyle.Top,
            Height = 35,
            FlowDirection = FlowDirection.RightToLeft,
        };

        _sendAllBtn = new Button
        {
            Text = "Send All to Tally",
            BackColor = Color.FromArgb(0, 150, 100),
            ForeColor = Color.White,
            FlatStyle = FlatStyle.Flat,
            AutoSize = true,
            Margin = new Padding(5, 3, 0, 3),
            Cursor = Cursors.Hand,
        };
        _sendAllBtn.Click += async (_, _) => await SendAllAsync();
        pendingActions.Controls.Add(_sendAllBtn);

        _sendSelectedBtn = new Button
        {
            Text = "Send Selected",
            BackColor = Color.FromArgb(0, 120, 180),
            ForeColor = Color.White,
            FlatStyle = FlatStyle.Flat,
            AutoSize = true,
            Margin = new Padding(5, 3, 5, 3),
            Cursor = Cursors.Hand,
        };
        _sendSelectedBtn.Click += async (_, _) => await SendSelectedAsync();
        pendingActions.Controls.Add(_sendSelectedBtn);

        _pendingGrid = new DataGridView
        {
            Dock = DockStyle.Fill,
            AllowUserToAddRows = false,
            AllowUserToDeleteRows = false,
            ReadOnly = true,
            RowHeadersVisible = false,
            SelectionMode = DataGridViewSelectionMode.FullRowSelect,
            MultiSelect = true,
            BackgroundColor = Color.FromArgb(40, 40, 40),
            ForeColor = Color.White,
            GridColor = Color.FromArgb(60, 60, 60),
            BorderStyle = BorderStyle.None,
            AutoSizeColumnsMode = DataGridViewAutoSizeColumnsMode.Fill,
        };
        _pendingGrid.Columns.Add("Id", "ID");
        _pendingGrid.Columns.Add("Vendor", "Vendor");
        _pendingGrid.Columns.Add("Number", "Invoice #");
        _pendingGrid.Columns.Add("Type", "Type");
        _pendingGrid.Columns.Add("Amount", "Amount");
        _pendingGrid.Columns[0].Width = 60;
        _pendingGrid.Columns[1].Width = 200;
        _pendingGrid.Columns[2].Width = 130;
        _pendingGrid.Columns[3].Width = 100;
        _pendingGrid.Columns[4].Width = 100;
        _pendingGrid.Columns[4].DefaultCellStyle.Format = "N2";
        _pendingGrid.CellFormatting += (s, e) =>
        {
            if (e.RowIndex >= 0)
            {
                if (_pendingGrid.Rows[e.RowIndex].Tag is InvoiceDto inv)
                {
                    if (inv.Status == "exported")
                        e.CellStyle.BackColor = Color.FromArgb(0, 80, 50);
                    else if (inv.Status == "sync_error")
                        e.CellStyle.BackColor = Color.FromArgb(80, 30, 30);
                }
            }
        };

        pendingPanel.Controls.Add(_pendingGrid);
        pendingPanel.Controls.Add(pendingActions);
        pendingPanel.Controls.Add(pendingLabel);
        mainPanel.Controls.Add(pendingPanel, 0, 2);

        // History section
        var historyPanel = new Panel { Dock = DockStyle.Fill };
        var historyLabel = new Label
        {
            Text = "Import History",
            Font = new Font("Segoe UI", 11, FontStyle.Bold),
            ForeColor = Color.LightGray,
            Dock = DockStyle.Top,
            Height = 25,
        };

        _historyBox = new ListBox
        {
            Dock = DockStyle.Fill,
            BackColor = Color.FromArgb(35, 35, 35),
            ForeColor = Color.FromArgb(200, 200, 200),
            BorderStyle = BorderStyle.None,
            Font = new Font("Consolas", 9),
        };

        historyPanel.Controls.Add(_historyBox);
        historyPanel.Controls.Add(historyLabel);
        mainPanel.Controls.Add(historyPanel, 0, 3);

        // Status bar
        _statusLabel = new Label
        {
            Dock = DockStyle.Fill,
            Text = "Starting...",
            ForeColor = Color.Gray,
            TextAlign = ContentAlignment.MiddleLeft,
        };
        mainPanel.Controls.Add(_statusLabel, 0, 4);

        Controls.Add(mainPanel);

        // Style the grid
        _pendingGrid.ColumnHeadersDefaultCellStyle.BackColor = Color.FromArgb(50, 50, 50);
        _pendingGrid.ColumnHeadersDefaultCellStyle.ForeColor = Color.LightGray;
        _pendingGrid.EnableHeadersVisualStyles = false;
    }

    private void SetupTrayIcon()
    {
        _trayMenu = new ContextMenuStrip();
        _trayMenu.Items.Add("Show InvoSync", null, (_, _) => { Show(); WindowState = FormWindowState.Normal; });
        _trayMenu.Items.Add(new ToolStripSeparator());
        _trayMenu.Items.Add("Exit", null, (_, _) => { _trayIcon.Visible = false; Application.Exit(); });

        _trayIcon = new NotifyIcon
        {
            Icon = SystemIcons.Application,
            Text = "InvoSync Tally Connector",
            Visible = true,
            ContextMenuStrip = _trayMenu,
        };
        _trayIcon.DoubleClick += (_, _) => { Show(); WindowState = FormWindowState.Normal; };

        // Poll timer
        _pollTimer = new System.Windows.Forms.Timer { Interval = 15000 };
        _pollTimer.Tick += async (_, _) => await RefreshAllAsync();
    }

    protected override void OnFormClosing(FormClosingEventArgs e)
    {
        if (e.CloseReason == CloseReason.UserClosing)
        {
            e.Cancel = true;
            WindowState = FormWindowState.Minimized;
            Hide();
            _trayIcon.ShowBalloonTip(2000, "InvoSync", "Still running in background", ToolTipIcon.Info);
        }
    }

    protected override void OnResize(EventArgs e)
    {
        if (WindowState == FormWindowState.Minimized)
        {
            Hide();
            _trayIcon.ShowBalloonTip(2000, "InvoSync", "Still running in background", ToolTipIcon.Info);
        }
    }

    public async Task RefreshAllAsync()
    {
        try
        {
            // Update status
            _statusLabel.Text = "⟳ Refreshing...";

            // Ping Tally
            bool tallyOnline = await _companySyncer.RunStartupDiagnosticCheckAsync(CancellationToken.None);
            _companyStatusLabel.Text = tallyOnline ? "🟢 Connected" : "🔴 Offline";
            _companyStatusLabel.ForeColor = tallyOnline ? Color.LimeGreen : Color.Red;

            // Fetch companies from Tally
            await _companySyncer.SyncOpenCompaniesAsync(CancellationToken.None);

            // Sync ledgers
            await Task.Run(() => _companySyncer.ReportConnectorAliveAsync(tallyOnline, CancellationToken.None));

            // Fetch pending invoices
            var client = _httpFactory.CreateClient("InvoSync");
            var resp = await client.GetAsync("/api/v3/sync/pending");
            if (resp.IsSuccessStatusCode)
            {
                var pending = await resp.Content.ReadFromJsonAsync<PendingResponse>(new JsonSerializerOptions { PropertyNameCaseInsensitive = true });
                _pendingInvoices = pending?.Invoices ?? new List<InvoiceDto>();
                UpdatePendingGrid();
            }

            // Update status
            var pendingCount = _pendingInvoices.Count;
            _statusLabel.Text = $"🟢 Running | {pendingCount} pending | {(tallyOnline ? "Tally Connected" : "Tally Offline")}";
        }
        catch (Exception ex)
        {
            _statusLabel.Text = $"⚠ Error: {ex.Message}";
            _log.LogWarning("Refresh failed: {Message}", ex.Message);
        }
    }

    private void UpdatePendingGrid()
    {
        _pendingGrid.Rows.Clear();
        foreach (var inv in _pendingInvoices)
        {
            var row = new DataGridViewRow();
            row.CreateCells(_pendingGrid);
            row.Cells[0].Value = inv.DisplayId;
            row.Cells[1].Value = inv.VendorName ?? "?";
            row.Cells[2].Value = inv.InvoiceNumber ?? "?";
            row.Cells[3].Value = inv.VoucherType ?? "Purchase";
            row.Cells[4].Value = inv.TotalAmount;
            row.Tag = inv;
            _pendingGrid.Rows.Add(row);
        }
        _sendSelectedBtn.Text = $"Send Selected ({_pendingGrid.SelectedRows.Count})";
    }

    public void AddHistory(string text, bool isError = false)
    {
        var timestamp = DateTime.Now.ToString("HH:mm:ss");
        var prefix = isError ? "✗" : "✓";
        _historyBox.Items.Insert(0, $"[{timestamp}] {prefix} {text}");
        if (_historyBox.Items.Count > 500)
            _historyBox.Items.RemoveAt(_historyBox.Items.Count - 1);
    }

    private async Task SendSelectedAsync()
    {
        if (_pendingGrid.SelectedRows.Count == 0)
        {
            AddHistory("No invoices selected", true);
            return;
        }

        var invs = _pendingGrid.SelectedRows
            .Cast<DataGridViewRow>()
            .Select(r => r.Tag as InvoiceDto)
            .Where(i => i != null && !string.IsNullOrWhiteSpace(i.XmlContent))
            .ToList();

        if (invs.Count == 0)
        {
            AddHistory("Selected invoices have no XML content", true);
            return;
        }

        foreach (var inv in invs)
        {
            await PushInvoiceAsync(inv!);
        }
        await RefreshAllAsync();
    }

    private async Task SendAllAsync()
    {
        var invs = _pendingInvoices.Where(i => !string.IsNullOrWhiteSpace(i.XmlContent)).ToList();
        if (invs.Count == 0)
        {
            AddHistory("No pending invoices to send", true);
            return;
        }

        _sendAllBtn.Enabled = false;
        _sendAllBtn.Text = "Sending...";

        foreach (var inv in invs)
        {
            await PushInvoiceAsync(inv);
        }

        _sendAllBtn.Enabled = true;
        _sendAllBtn.Text = "Send All to Tally";
        await RefreshAllAsync();
    }

    private async Task PushInvoiceAsync(InvoiceDto inv)
    {
        var client = _httpFactory.CreateClient("InvoSync");
        AddHistory($"Pushing #{inv.DisplayId} ({inv.InvoiceNumber})...");

        var result = await _pusher.PushAsync(inv.XmlContent!, CancellationToken.None, maxRetries: 3);

        if (result.Success)
        {
            AddHistory($"#{inv.DisplayId} ✓ Imported to Tally");
            try
            {
                var confirm = await client.PostAsync($"/api/v3/sync/confirm/{inv.DisplayId}", null);
                if (!confirm.IsSuccessStatusCode)
                    AddHistory($"#{inv.DisplayId} Confirm failed: {confirm.StatusCode}", true);
            }
            catch (Exception ex)
            {
                AddHistory($"#{inv.DisplayId} Confirm error: {ex.Message}", true);
            }
        }
        else
        {
            AddHistory($"#{inv.DisplayId} ✗ Failed: {result.ErrorLine ?? "Unknown"}", true);
            try
            {
                var errPayload = JsonContent.Create(new { error = result.ErrorLine ?? "Push failed" });
                await client.PostAsync($"/api/v3/sync/error/{inv.DisplayId}", errPayload);
            }
            catch { }
        }
    }

    private async Task FetchCompaniesFromTallyAsync()
    {
        try
        {
            var companies = await Task.Run(() =>
            {
                var tally = _httpFactory.CreateClient("Tally");
                var xml = @"<ENVELOPE>
<HEADER><VERSION>1</VERSION><TALLYREQUEST>Export</TALLYREQUEST><TYPE>Company</TYPE><ID>List of Companies</ID></HEADER>
<BODY><DESC><STATICVARIABLES></STATICVARIABLES></DESC></BODY>
</ENVELOPE>";
                var content = new StringContent(xml, Encoding.UTF8, "text/xml");
                var resp = tally.PostAsync("", content).Result;
                if (!resp.IsSuccessStatusCode) return new List<string>();
                var body = resp.Content.ReadAsStringAsync().Result;
                return ParseCompanyNames(body);
            });

            _companyCombo.Items.Clear();
            _companyCombo.Items.Add("— Auto-detect (Default) —");
            foreach (var c in companies)
                _companyCombo.Items.Add(c);
            _companyCombo.SelectedIndex = 0;
        }
        catch (Exception ex)
        {
            _companyCombo.Items.Clear();
            _companyCombo.Items.Add("— Tally Offline —");
            _companyCombo.SelectedIndex = 0;
            _log.LogDebug("Could not fetch companies: {Message}", ex.Message);
        }
    }

    private static List<string> ParseCompanyNames(string xml)
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
