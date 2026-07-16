using System.Diagnostics;
using System.Drawing.Drawing2D;
using System.Net.Http.Json;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.Json;
using InvoSync.TallyConnector.Forms;
using InvoSync.TallyConnector.Models;
using InvoSync.TallyConnector.Services;

namespace InvoSync.TallyConnector;

public class MainForm : Form
{
    private readonly IHttpClientFactory _httpFactory;
    private readonly TallyPusher _pusher;
    private readonly QueueManager _queue;
    private readonly TallyCompanySyncer _companySyncer;
    private readonly AutoUpdater _autoUpdater;
    private readonly AutoRecoveryService _autoRecovery;
    private readonly SyncWatchdog _watchdog;
    private readonly RecentPushStore _recentPushes;
    private readonly ConnectorLogger _connectorLogger;
    private readonly DiagnosticReporter _diagnosticReporter;
    private readonly SessionManager _sessionManager;
    private readonly CompanyGuard _companyGuard;
    private readonly ILogger<MainForm> _log;

    // Header
    private Panel _titleBar = null!;
    private Button _minBtn = null!, _closeBtn = null!;

    // Status cards
    private Panel _cardConnector = null!, _cardTally = null!, _cardServer = null!;
    private Label _cardConnectorStatus = null!, _cardTallyStatus = null!, _cardServerStatus = null!;
    private Label _cardConnectorLabel = null!, _cardTallyLabel = null!, _cardServerLabel = null!;
    private Panel _cardConnectorDot = null!, _cardTallyDot = null!, _cardServerDot = null!;

    // Company bar
    private Label _companyLabel = null!;

    // Stats
    private Label _statPushed = null!, _statPending = null!, _statFailed = null!, _statQueued = null!;

    // Activity grid
    private DataGridView _recentGrid = null!;
    private DataGridViewButtonColumn _undoCol = null!;
    private DataGridViewButtonColumn _retryCol = null!;

    // Sync animation
    private Panel _syncIndicator = null!;
    private System.Windows.Forms.Timer _syncPulseTimer = null!;
    private bool _pulseOn;
    private int _pulseCount;

    // Action bar
    private Button _syncNowBtn = null!, _viewLogsBtn = null!, _diagnosticBtn = null!;
    private Button _settingsBtn = null!, _helpBtn = null!;

    private NotifyIcon _trayIcon = null!;
    private ContextMenuStrip _trayMenu = null!;
    private ToolStripMenuItem _trayPendingCount = null!;
    private System.Windows.Forms.Timer _refreshTimer = null!;

    private List<InvoiceDto> _pendingInvoices = new();
    private bool _isSyncing;
    private DateTime _lastSyncTime = DateTime.MinValue;
    private string _activeCompany = "";
    private ConnectorState _currentState = ConnectorState.ServerDisconnected;
    private readonly OfflineQueue _offlineQueue;

    // Dark theme palette
    private static readonly Color BgDark = Color.FromArgb(13, 17, 23);
    private static readonly Color BgCard = Color.FromArgb(22, 27, 34);
    private static readonly Color BorderColor = Color.FromArgb(48, 54, 61);
    private static readonly Color TextPrimary = Color.FromArgb(230, 237, 243);
    private static readonly Color TextSecondary = Color.FromArgb(139, 148, 158);
    private static readonly Color AccentGreen = Color.FromArgb(0, 200, 150);
    private static readonly Color AccentRed = Color.FromArgb(233, 69, 96);
    private static readonly Color AccentBlue = Color.FromArgb(88, 166, 255);
    private static readonly Color AccentYellow = Color.FromArgb(210, 153, 34);
    private static readonly Color BtnBg = Color.FromArgb(33, 38, 45);
    private static readonly Color BtnBgHover = Color.FromArgb(48, 54, 61);
    private static readonly Color CardSuccess = Color.FromArgb(0, 80, 60);
    private static readonly Color CardWarning = Color.FromArgb(80, 60, 20);
    private static readonly Color CardDanger = Color.FromArgb(80, 20, 20);

    public MainForm(IHttpClientFactory httpFactory, TallyPusher pusher, QueueManager queue,
        TallyCompanySyncer companySyncer, AutoUpdater autoUpdater,
        AutoRecoveryService autoRecovery, SyncWatchdog watchdog,
        RecentPushStore recentPushes, ConnectorLogger connectorLogger,
        DiagnosticReporter diagnosticReporter, SessionManager sessionManager,
        CompanyGuard companyGuard, OfflineQueue offlineQueue,
        ILogger<MainForm> log)
    {
        _httpFactory = httpFactory;
        _pusher = pusher;
        _queue = queue;
        _companySyncer = companySyncer;
        _autoUpdater = autoUpdater;
        _autoRecovery = autoRecovery;
        _watchdog = watchdog;
        _recentPushes = recentPushes;
        _connectorLogger = connectorLogger;
        _diagnosticReporter = diagnosticReporter;
        _sessionManager = sessionManager;
        _companyGuard = companyGuard;
        _offlineQueue = offlineQueue;
        _log = log;

        InitializeComponent();
        SetupTrayIcon();
        SetupSyncAnimation();
    }

    private void InitializeComponent()
    {
        Text = "InvoSync Tally Connector";
        Size = new Size(960, 680);
        MinimumSize = new Size(720, 520);
        StartPosition = FormStartPosition.CenterScreen;
        BackColor = BgDark;
        ForeColor = TextPrimary;
        Font = new Font("Segoe UI", 10);
        FormBorderStyle = FormBorderStyle.None;

        var root = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            RowCount = 6,
            ColumnCount = 1,
            BackColor = BgDark,
        };
        root.RowStyles.Add(new RowStyle(SizeType.Absolute, 48F));
        root.RowStyles.Add(new RowStyle(SizeType.Absolute, 72F));
        root.RowStyles.Add(new RowStyle(SizeType.Absolute, 36F));
        root.RowStyles.Add(new RowStyle(SizeType.Absolute, 52F));
        root.RowStyles.Add(new RowStyle(SizeType.Percent, 100F));
        root.RowStyles.Add(new RowStyle(SizeType.Absolute, 48F));

        root.Controls.Add(BuildTitleBar(), 0, 0);
        root.Controls.Add(BuildStatusCards(), 0, 1);
        root.Controls.Add(BuildCompanyBar(), 0, 2);
        root.Controls.Add(BuildStatsRow(), 0, 3);
        root.Controls.Add(BuildActivityPanel(), 0, 4);
        root.Controls.Add(BuildActionBar(), 0, 5);

        Controls.Add(root);
    }

    private Panel BuildTitleBar()
    {
        _titleBar = new Panel
        {
            Height = 48,
            Dock = DockStyle.Fill,
            BackColor = BgCard,
        };

        // App icon + title
        var logo = new Label
        {
            Text = "⬡ InvoSync",
            Font = new Font("Segoe UI", 14, FontStyle.Bold),
            ForeColor = AccentGreen,
            Location = new Point(16, 10),
            AutoSize = true,
        };

        var version = new Label
        {
            Text = $"v{GetConnectorVersion()}",
            ForeColor = TextSecondary,
            Font = new Font("Segoe UI", 9),
            Location = new Point(logo.Right + 8, 15),
            AutoSize = true,
        };

        // Status badge
        _syncIndicator = new Panel
        {
            Size = new Size(10, 10),
            BackColor = AccentGreen,
            Location = new Point(version.Right + 16, 19),
            Visible = true,
        };
        MakeRoundPanel(_syncIndicator);

        // Window control buttons
        _minBtn = WinBtn("—", 8, 10);
        _minBtn.Click += (_, _) => WindowState = FormWindowState.Minimized;

        _closeBtn = WinBtn("✕", _titleBar.Width - 36, 10);
        _closeBtn.Click += (_, _) => { _trayIcon.Visible = false; Application.Exit(); };

        _titleBar.Resize += (_, _) =>
        {
            _minBtn.Location = new Point(_titleBar.Width - 72, 10);
            _closeBtn.Location = new Point(_titleBar.Width - 40, 10);
        };

        // Drag to move
        _titleBar.MouseDown += (_, e) =>
        {
            if (e.Button == MouseButtons.Left)
            {
                ReleaseCapture();
                SendMessage(Handle, WM_NCLBUTTONDOWN, HT_CAPTION, 0);
            }
        };

        _titleBar.Controls.AddRange([logo, version, _syncIndicator, _minBtn, _closeBtn]);
        return _titleBar;
    }

    private Panel BuildStatusCards()
    {
        var panel = new Panel { Dock = DockStyle.Fill, BackColor = BgDark, Padding = new Padding(12, 8, 12, 4) };

        var layout = new FlowLayoutPanel
        {
            Dock = DockStyle.Fill,
            FlowDirection = FlowDirection.LeftToRight,
            WrapContents = false,
            BackColor = Color.Transparent,
        };

        _cardConnector = StatusCard("Connector", ref _cardConnectorDot, ref _cardConnectorLabel, ref _cardConnectorStatus, "Checking...", Color.Gray);
        _cardTally = StatusCard("Tally Prime", ref _cardTallyDot, ref _cardTallyLabel, ref _cardTallyStatus, "Checking...", Color.Gray);
        _cardServer = StatusCard("InvoSync", ref _cardServerDot, ref _cardServerLabel, ref _cardServerStatus, "Checking...", Color.Gray);

        layout.Controls.AddRange([_cardConnector, _cardTally, _cardServer]);
        panel.Controls.Add(layout);
        return panel;
    }

    private static Panel StatusCard(string title, ref Panel dotRef, ref Label labelRef, ref Label statusRef, string initialText, Color initialColor)
    {
        var card = new Panel
        {
            Size = new Size(290, 58),
            BackColor = BgCard,
            Margin = new Padding(0, 0, 12, 0),
        };
        card.Paint += (_, e) =>
        {
            using var pen = new Pen(BorderColor, 1);
            var rect = new Rectangle(0, 0, card.Width - 1, card.Height - 1);
            e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
            using var path = RoundedRect(rect, 6);
            e.Graphics.DrawPath(pen, path);
        };

        dotRef = new Panel
        {
            Size = new Size(12, 12),
            BackColor = initialColor,
            Location = new Point(16, 12),
        };
        MakeRoundPanel(dotRef);

        labelRef = new Label
        {
            Text = title,
            Font = new Font("Segoe UI", 9, FontStyle.Bold),
            ForeColor = TextSecondary,
            Location = new Point(36, 10),
            AutoSize = true,
        };

        statusRef = new Label
        {
            Text = initialText,
            Font = new Font("Segoe UI", 11, FontStyle.Bold),
            ForeColor = initialColor,
            Location = new Point(36, 28),
            AutoSize = true,
        };

        card.Controls.AddRange([dotRef, labelRef, statusRef]);
        return card;
    }

    private Panel BuildCompanyBar()
    {
        var panel = new Panel { Dock = DockStyle.Fill, BackColor = BgCard, Padding = new Padding(16, 2, 16, 2), Cursor = Cursors.Hand };

        _companyLabel = new Label
        {
            Text = "No company selected",
            Font = new Font("Segoe UI", 10),
            ForeColor = TextSecondary,
            Dock = DockStyle.Fill,
            TextAlign = ContentAlignment.MiddleLeft,
            AutoSize = false,
        };

        var switchHint = new Label
        {
            Text = "\u25BC Switch",
            ForeColor = AccentBlue,
            Font = new Font("Segoe UI", 8),
            Dock = DockStyle.Right,
            TextAlign = ContentAlignment.MiddleRight,
            AutoSize = false,
            Width = 80,
        };

        panel.Click += (_, _) => ShowCompanySwitcher();
        _companyLabel.Click += (_, _) => ShowCompanySwitcher();
        switchHint.Click += (_, _) => ShowCompanySwitcher();

        panel.Controls.Add(switchHint);
        panel.Controls.Add(_companyLabel);
        return panel;
    }

    private Panel BuildStatsRow()
    {
        var panel = new Panel { Dock = DockStyle.Fill, BackColor = BgDark, Padding = new Padding(12, 0, 12, 4) };

        var layout = new FlowLayoutPanel
        {
            Dock = DockStyle.Fill,
            FlowDirection = FlowDirection.LeftToRight,
            WrapContents = false,
            BackColor = Color.Transparent,
        };

        _statPushed = StatBox("Pushed Today", "0", AccentGreen);
        _statPending = StatBox("Pending", "0", AccentYellow);
        _statFailed = StatBox("Failed", "0", AccentRed);
        _statQueued = StatBox("Offline Queue", "0", AccentBlue);

        layout.Controls.AddRange([_statPushed, _statPending, _statFailed, _statQueued]);
        panel.Controls.Add(layout);
        return panel;
    }

    private static Label StatBox(string title, string initial, Color color)
    {
        return new Label
        {
            Text = $"{title}\n{initial}",
            Font = new Font("Segoe UI", 10, FontStyle.Bold),
            ForeColor = color,
            BackColor = BgCard,
            Size = new Size(170, 44),
            Margin = new Padding(0, 0, 8, 0),
            Padding = new Padding(8, 4, 8, 4),
            TextAlign = ContentAlignment.MiddleLeft,
        };
    }

    private Panel BuildActivityPanel()
    {
        var panel = new Panel { Dock = DockStyle.Fill, BackColor = BgCard, Padding = new Padding(0, 0, 0, 0) };

        var header = new Label
        {
            Text = "Recent Activity",
            Font = new Font("Segoe UI", 11, FontStyle.Bold),
            ForeColor = TextPrimary,
            Dock = DockStyle.Top,
            Height = 28,
            Padding = new Padding(12, 4, 0, 0),
            BackColor = BgDark,
        };

        _recentGrid = new DataGridView
        {
            Dock = DockStyle.Fill,
            AllowUserToAddRows = false,
            AllowUserToDeleteRows = false,
            ReadOnly = true,
            RowHeadersVisible = false,
            SelectionMode = DataGridViewSelectionMode.FullRowSelect,
            BackgroundColor = BgDark,
            ForeColor = TextPrimary,
            GridColor = BorderColor,
            BorderStyle = BorderStyle.None,
            AutoSizeColumnsMode = DataGridViewAutoSizeColumnsMode.Fill,
            RowTemplate = new DataGridViewRow { Height = 28 },
        };

        // Columns
        _recentGrid.Columns.Add("Time", "Time");
        _recentGrid.Columns.Add("Invoice", "Invoice #");
        _recentGrid.Columns.Add("Vendor", "Vendor");
        _recentGrid.Columns.Add("Amount", "Amount");
        _recentGrid.Columns.Add("Status", "Status");
        _recentGrid.Columns.Add("Duration", "Duration");
        _recentGrid.Columns.Add("TraceId", "Trace ID");

        _undoCol = new DataGridViewButtonColumn { HeaderText = "", Text = "↩ Undo", Width = 60, UseColumnTextForButtonValue = false };
        _retryCol = new DataGridViewButtonColumn { HeaderText = "", Text = "⟳ Retry", Width = 60, UseColumnTextForButtonValue = false };
        _recentGrid.Columns.Add(_undoCol);
        _recentGrid.Columns.Add(_retryCol);

        _recentGrid.Columns[0].Width = 70;
        _recentGrid.Columns[1].Width = 90;
        _recentGrid.Columns[2].AutoSizeMode = DataGridViewAutoSizeColumnMode.Fill;
        _recentGrid.Columns[3].Width = 80;
        _recentGrid.Columns[3].DefaultCellStyle.Format = "N2";
        _recentGrid.Columns[4].Width = 70;
        _recentGrid.Columns[5].Width = 60;
        _recentGrid.Columns[6].Width = 80;
        _recentGrid.Columns[6].Visible = false;

        _recentGrid.ColumnHeadersDefaultCellStyle.BackColor = BgCard;
        _recentGrid.ColumnHeadersDefaultCellStyle.ForeColor = TextSecondary;
        _recentGrid.ColumnHeadersHeight = 28;
        _recentGrid.EnableHeadersVisualStyles = false;

        _recentGrid.CellFormatting += (s, e) =>
        {
            if (e.RowIndex >= 0 && e.ColumnIndex == 4)
            {
                var val = _recentGrid.Rows[e.RowIndex].Cells[4].Value?.ToString();
                e.CellStyle.ForeColor = val == "✓" ? AccentGreen : val == "✗" ? AccentRed : TextPrimary;
                e.CellStyle.Font = new Font("Segoe UI", 10, FontStyle.Bold);
            }
        };

        _recentGrid.CellClick += OnGridCellClick;

        panel.Controls.Add(_recentGrid);
        panel.Controls.Add(header);
        return panel;
    }

    private Panel BuildActionBar()
    {
        var panel = new Panel { Dock = DockStyle.Fill, BackColor = BgCard, Padding = new Padding(12, 6, 12, 6) };

        var layout = new FlowLayoutPanel
        {
            Dock = DockStyle.Right,
            FlowDirection = FlowDirection.LeftToRight,
            WrapContents = false,
            BackColor = Color.Transparent,
        };

        _helpBtn = ActionBtn("?", "Help", () => ShowHelp());
        _settingsBtn = ActionBtn("\u2699", "Settings", () => ShowSettings());
        _diagnosticBtn = ActionBtn("\u2699\uFE0F", "Diagnostics", () => _ = RunDiagnosticAsync());
        _viewLogsBtn = ActionBtn("\uD83D\uDCC4", "View Logs", () => ViewLogs());
        _syncNowBtn = ActionBtn("\u25B6", "Sync Now", async () => await SyncNowAsync(), isPrimary: true);

        layout.Controls.AddRange([_helpBtn, _settingsBtn, _diagnosticBtn, _viewLogsBtn, _syncNowBtn]);

        // Last sync label on the left
        var lastSyncPanel = new Panel { Dock = DockStyle.Left, BackColor = Color.Transparent, AutoSize = true };
        _lastSyncLabelRef = new Label
        {
            Text = "Last sync: Never",
            ForeColor = TextSecondary,
            Font = new Font("Segoe UI", 9),
            Dock = DockStyle.Fill,
            TextAlign = ContentAlignment.MiddleLeft,
        };
        lastSyncPanel.Controls.Add(_lastSyncLabelRef);

        panel.Controls.Add(layout);
        panel.Controls.Add(lastSyncPanel);
        return panel;
    }

    private Label _lastSyncLabelRef = null!;

    private static Button ActionBtn(string icon, string tooltip, Action action, bool isPrimary = false)
    {
        var btn = new Button
        {
            Text = $"{icon} {tooltip}",
            BackColor = isPrimary ? Color.FromArgb(0, 120, 80) : BtnBg,
            ForeColor = TextPrimary,
            FlatStyle = FlatStyle.Flat,
            AutoSize = true,
            Height = 32,
            Margin = new Padding(4, 0, 0, 0),
            Cursor = Cursors.Hand,
            Font = new Font("Segoe UI", 9, isPrimary ? FontStyle.Bold : FontStyle.Regular),
            Padding = new Padding(10, 0, 10, 0),
            TextAlign = ContentAlignment.MiddleCenter,
        };
        btn.FlatAppearance.BorderSize = 0;
        btn.MouseEnter += (_, _) => btn.BackColor = isPrimary ? Color.FromArgb(0, 140, 100) : BtnBgHover;
        btn.MouseLeave += (_, _) => btn.BackColor = isPrimary ? Color.FromArgb(0, 120, 80) : BtnBg;
        btn.Click += (_, _) => action();
        return btn;
    }

    private static Button WinBtn(string text, int x, int y)
    {
        return new Button
        {
            Text = text,
            Location = new Point(x, y),
            Size = new Size(28, 28),
            FlatStyle = FlatStyle.Flat,
            BackColor = Color.Transparent,
            ForeColor = TextSecondary,
            FlatAppearance = { BorderSize = 0, MouseOverBackColor = BtnBgHover },
            Font = new Font("Segoe UI", 11),
            Cursor = Cursors.Hand,
        };
    }

    // ==================== SYNC ANIMATION ====================

    private void SetupSyncAnimation()
    {
        _syncPulseTimer = new System.Windows.Forms.Timer { Interval = 600 };
        _syncPulseTimer.Tick += (_, _) =>
        {
            if (_isSyncing)
            {
                _pulseCount++;
                _pulseOn = !_pulseOn;
                _syncIndicator.BackColor = _pulseOn ? AccentBlue : AccentGreen;
                _syncIndicator.Size = _pulseOn ? new Size(14, 14) : new Size(10, 10);
                MakeRoundPanel(_syncIndicator);

                // Rotate tray icon on every other pulse
                if (_pulseCount % 2 == 0)
                    _trayIcon.Icon = TrayIconProvider.GetIcon(ConnectorState.Syncing);
            }
            else
            {
                _syncIndicator.BackColor = _currentState == ConnectorState.AllConnected ? AccentGreen : AccentYellow;
                _syncIndicator.Size = new Size(10, 10);
                MakeRoundPanel(_syncIndicator);
            }
        };
    }

    // ==================== TRAY ====================

    private void SetupTrayIcon()
    {
        _trayPendingCount = new ToolStripMenuItem("Pending: 0") { Enabled = false };

        _trayMenu = new ContextMenuStrip();
        _trayMenu.Items.Add("Show InvoSync", null, (_, _) => RestoreFromTray());
        _trayMenu.Items.Add("Sync Now", null, async (_, _) => await SyncNowAsync());
        _trayMenu.Items.Add(_trayPendingCount);
        _trayMenu.Items.Add(new ToolStripSeparator());
        _trayMenu.Items.Add("Open Web App", null, async (_, _) =>
        {
            try { Process.Start(new ProcessStartInfo("https://invosync-backend-yjfa.onrender.com") { UseShellExecute = true }); }
            catch { }
        });
        _trayMenu.Items.Add("Check Updates", null, async (_, _) => await CheckUpdateAsync());
        _trayMenu.Items.Add(new ToolStripSeparator());
        _trayMenu.Items.Add("About", null, (_, _) => MessageBox.Show($"InvoSync Tally Connector v{GetConnectorVersion()}", "About", MessageBoxButtons.OK, MessageBoxIcon.Information));
        _trayMenu.Items.Add("Exit", null, (_, _) => { _trayIcon.Visible = false; Application.Exit(); });

        _trayIcon = new NotifyIcon
        {
            Icon = TrayIconProvider.GetIcon(ConnectorState.AllConnected),
            Text = "InvoSync Connector",
            Visible = true,
            ContextMenuStrip = _trayMenu,
        };
        _trayIcon.DoubleClick += (_, _) => RestoreFromTray();
        _trayIcon.BalloonTipClicked += (_, _) => RestoreFromTray();

        _refreshTimer = new System.Windows.Forms.Timer { Interval = 15000 };
        _refreshTimer.Tick += async (_, _) =>
        {
            try { await RefreshAllAsync(); }
            catch (Exception ex) { _log?.LogError(ex, "Refresh timer error"); }
        };
        _refreshTimer.Start();
    }

    private void RestoreFromTray()
    {
        Show();
        WindowState = FormWindowState.Normal;
        BringToFront();
    }

    // ==================== WINDOW EVENTS ====================

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

    protected override void OnLoad(EventArgs e)
    {
        base.OnLoad(e);
        _ = RefreshAllAsync();
    }

    // ==================== REFRESH ====================

    public async Task RefreshAllAsync()
    {
        if (InvokeRequired)
        {
            BeginInvoke(new Action(async () => await RefreshAllAsync()));
            return;
        }

        try
        {
            UpdateCard(_cardConnectorDot, _cardConnectorStatus, "Checking...", Color.Yellow, Color.Yellow);

            var pendingCount = 0;
            var tallyOnline = false;
            var serverOnline = false;

            try
            {
                var client = _httpFactory.CreateClient("InvoSync");
                using var cts = new CancellationTokenSource(TimeSpan.FromSeconds(10));
                var ping = await client.GetAsync("/health", cts.Token);
                serverOnline = ping.IsSuccessStatusCode;
            }
            catch (OperationCanceledException) { _log?.LogWarning("Backend health check timed out"); }
            catch (Exception ex) { _log?.LogDebug(ex, "Backend health check failed"); }

            try { tallyOnline = await _companySyncer.RunStartupDiagnosticCheckAsync(CancellationToken.None); }
            catch (Exception ex) { _log?.LogDebug(ex, "Tally diagnostic failed"); }

            try
            {
                var client = _httpFactory.CreateClient("InvoSync");
                using var cts = new CancellationTokenSource(TimeSpan.FromSeconds(15));
                var resp = await client.GetAsync("/api/v3/sync/pending", cts.Token);
                if (resp.IsSuccessStatusCode)
                {
                    var pending = await resp.Content.ReadFromJsonAsync<PendingResponse>(
                        new JsonSerializerOptions { PropertyNameCaseInsensitive = true });
                    pendingCount = pending?.Invoices?.Count ?? 0;
                    _pendingInvoices = pending?.Invoices ?? new List<InvoiceDto>();
                }
            }
            catch (OperationCanceledException) { _log?.LogWarning("Pending invoices fetch timed out"); }
            catch (Exception ex) { _log?.LogDebug(ex, "Pending invoices fetch failed"); }

            _currentState = serverOnline && tallyOnline
                ? ConnectorState.AllConnected
                : !tallyOnline ? ConnectorState.TallyClosed : ConnectorState.ServerDisconnected;

            UpdateCard(_cardConnectorDot, _cardConnectorStatus, _currentState == ConnectorState.AllConnected ? "All Systems Go" : _currentState == ConnectorState.TallyClosed ? "Tally Offline" : "Server Issue",
                _currentState == ConnectorState.AllConnected ? AccentGreen : _currentState == ConnectorState.TallyClosed ? AccentYellow : AccentRed,
                _currentState == ConnectorState.AllConnected ? Color.FromArgb(0, 60, 40) : _currentState == ConnectorState.TallyClosed ? CardWarning : CardDanger);
            UpdateCard(_cardTallyDot, _cardTallyStatus, tallyOnline ? "Online" : "Offline", tallyOnline ? AccentGreen : AccentRed,
                tallyOnline ? CardSuccess : CardDanger);
            UpdateCard(_cardServerDot, _cardServerStatus, serverOnline ? "Connected" : "Disconnected", serverOnline ? AccentGreen : AccentRed,
                serverOnline ? CardSuccess : CardDanger);

            _trayIcon.Icon = TrayIconProvider.GetIcon(_isSyncing ? ConnectorState.Syncing : _currentState);
            _trayIcon.Text = TrayIconProvider.GetText(_currentState, pendingCount);
            _trayPendingCount.Text = $"Pending: {pendingCount}";

            UpdateStats(pendingCount);
            UpdateRecentGrid();

            // Company sync on first load
            if (string.IsNullOrEmpty(_activeCompany))
            {
                try
                {
                    var client = _httpFactory.CreateClient("InvoSync");
                    var resp = await client.GetAsync("/api/v3/tally/config");
                    if (resp.IsSuccessStatusCode)
                    {
                        var cfg = await resp.Content.ReadFromJsonAsync<JsonElement>();
                        if (cfg.TryGetProperty("active_company", out var ac))
                            _activeCompany = ac.GetString() ?? "";
                    }
                }
                catch { }
                _companyLabel.Text = string.IsNullOrEmpty(_activeCompany) ? "No company selected" : _activeCompany;
            }
        }
        catch (Exception ex)
        {
            _log?.LogError(ex, "Refresh failed");
        }
    }

    private void UpdateStats(int pendingCount)
    {
        var pushed = _recentPushes?.TodayPushCount ?? 0;
        var failed = _recentPushes?.TodayFailCount ?? 0;
        var queued = _offlineQueue?.GetPendingCount() ?? 0;

        _statPushed.Text = $"Pushed Today\n{pushed}";
        _statPending.Text = $"Pending\n{pendingCount}";
        _statFailed.Text = $"Failed\n{failed}";
        _statQueued.Text = $"Offline Queue\n{queued}";

        _lastSyncLabelRef.Text = _lastSyncTime == DateTime.MinValue
            ? "Last sync: Never"
            : $"Last sync: {GetTimeAgo(_lastSyncTime)}";
    }

    private void UpdateRecentGrid()
    {
        if (_recentGrid == null || _recentPushes == null) return;
        _recentGrid.SuspendLayout();
        _recentGrid.Rows.Clear();
        foreach (var entry in _recentPushes.GetRecent(100))
        {
            var rowIdx = _recentGrid.Rows.Add(
                entry.Timestamp.ToString("HH:mm"),
                $"#{entry.DisplayId}",
                entry.VendorName,
                entry.Amount.ToString("N2"),
                entry.Success ? "\u2713" : "\u2717",
                entry.DurationMs > 0 ? $"{entry.DurationMs}ms" : "",
                entry.TraceId ?? "");

            if (entry.Success)
            {
                _recentGrid.Rows[rowIdx].Cells[4].Style.ForeColor = AccentGreen;
                _recentGrid.Rows[rowIdx].Cells[7] = new DataGridViewButtonCell { Value = "↩ Undo", Style = { BackColor = BtnBg, ForeColor = AccentYellow } };
            }
            else
            {
                _recentGrid.Rows[rowIdx].Cells[4].Style.ForeColor = AccentRed;
                _recentGrid.Rows[rowIdx].Cells[8] = new DataGridViewButtonCell { Value = "⟳ Retry", Style = { BackColor = BtnBg, ForeColor = AccentBlue } };
            }
        }
        _recentGrid.ResumeLayout();
    }

    private async void OnGridCellClick(object? sender, DataGridViewCellEventArgs e)
    {
        if (e.RowIndex < 0) return;
        var entries = _recentPushes.GetRecent(100).ToList();
        if (e.RowIndex >= entries.Count) return;
        var entry = entries[e.RowIndex];

        if (e.ColumnIndex == 7 && entry.Success)
        {
            // Undo
            var confirm = MessageBox.Show($"Undo push of invoice #{entry.DisplayId} ({entry.InvoiceNumber})?", "Confirm Undo",
                MessageBoxButtons.YesNo, MessageBoxIcon.Question);
            if (confirm != DialogResult.Yes) return;

            try
            {
                using var cts = new CancellationTokenSource(TimeSpan.FromSeconds(30));
                var result = await _pusher.UndoLastPushAsync(entry.InvoiceNumber, "Purchase",
                    entry.Timestamp.ToString("yyyyMMdd"), null, cts.Token);
                if (result.Success)
                    _trayIcon.ShowBalloonTip(2000, "Undo", $"Invoice #{entry.DisplayId} removed from Tally", ToolTipIcon.Info);
                else
                    _trayIcon.ShowBalloonTip(3000, "Undo Failed", result.ErrorLine ?? "Unknown error", ToolTipIcon.Error);
            }
            catch (Exception ex)
            {
                _log?.LogError(ex, "Undo failed for #{Id}", entry.DisplayId);
            }
        }
        else if (e.ColumnIndex == 8 && !entry.Success)
        {
            // Retry
            _trayIcon.ShowBalloonTip(2000, "Retry", $"Re-pushing invoice #{entry.DisplayId}...", ToolTipIcon.Info);
            await SyncNowAsync();
        }
    }

    // ==================== ACTIONS ====================

    private void ShowCompanySwitcher()
    {
        var dialog = new CompanySwitcherDialog(_httpFactory, _activeCompany,
            _log ?? throw new InvalidOperationException("Logger not initialized"));
        if (dialog.ShowDialog(this) == DialogResult.OK || !string.IsNullOrEmpty(dialog.SelectedCompany))
        {
            _activeCompany = dialog.SelectedCompany;
            _companyLabel.Text = _activeCompany;
            _log?.LogInformation("Company switched to: {Company}", _activeCompany);
            _ = RefreshAllAsync();
        }
    }

    private async Task SyncNowAsync()
    {
        if (_isSyncing) return;

        // Show sync preview dialog
        var previewInvs = _pendingInvoices?.Where(i => !string.IsNullOrWhiteSpace(i.XmlContent)).ToList() ?? new List<InvoiceDto>();
        if (previewInvs.Count == 0)
        {
            _trayIcon.ShowBalloonTip(2000, "InvoSync", "No pending invoices to sync", ToolTipIcon.Info);
            return;
        }

        var preview = new SyncPreviewDialog(previewInvs, _httpFactory,
            _log ?? throw new InvalidOperationException("Logger not initialized"));
        if (preview.ShowDialog(this) != DialogResult.OK && !preview.Confirmed)
            return;

        var selected = preview.SelectedInvoices;
        if (selected.Count == 0) return;

        _isSyncing = true;
        _syncNowBtn.Text = "\u25B6 Syncing...";
        _syncNowBtn.Enabled = false;
        _syncPulseTimer.Start();
        _trayIcon.Icon = TrayIconProvider.GetIcon(ConnectorState.Syncing);

        try
        {
            foreach (var inv in selected)
            {
                var client = _httpFactory.CreateClient("InvoSync");
                using var cts = new CancellationTokenSource(TimeSpan.FromSeconds(120));
                var traceId = Guid.NewGuid().ToString("N")[..12];
                var result = await _pusher.PushAsync(inv.XmlContent!, cts.Token, maxRetries: 3);

                _recentPushes?.Add(new RecentPushEntry
                {
                    Timestamp = DateTime.Now,
                    DisplayId = inv.DisplayId,
                    InvoiceNumber = inv.InvoiceNumber ?? "?",
                    VendorName = inv.VendorName ?? "?",
                    Amount = inv.TotalAmount,
                    Success = result.Success,
                    Error = result.ErrorLine,
                    ConnectorVersion = GetConnectorVersion(),
                    TraceId = traceId,
                    DurationMs = 0,
                });
                _connectorLogger?.TallyPush(inv.DisplayId.ToString(), result.Success, result.ErrorLine);

                if (result.Success)
                {
                    try
                    {
                        using var postCts = new CancellationTokenSource(TimeSpan.FromSeconds(10));
                        using var req = new HttpRequestMessage(HttpMethod.Post, $"/api/v3/sync/confirm/{inv.DisplayId}");
                        req.Headers.TryAddWithoutValidation("X-Trace-Id", traceId);
                        await client.SendAsync(req, postCts.Token);
                    }
                    catch (Exception ex) { _log?.LogDebug(ex, "Confirm failed for #{Id}", inv.DisplayId); }
                }
            }

            _lastSyncTime = DateTime.Now;
            var pushed = _recentPushes?.TodayPushCount ?? 0;
            var failed = _recentPushes?.TodayFailCount ?? 0;
            _trayIcon.ShowBalloonTip(3000, "Sync Complete",
                $"{pushed} invoices pushed | {failed} failed", ToolTipIcon.Info);

            await RefreshAllAsync();
        }
        catch (Exception ex)
        {
            _log?.LogError(ex, "Sync failed");
            _trayIcon.ShowBalloonTip(3000, "Sync Failed", ex.Message, ToolTipIcon.Error);
        }
        finally
        {
            _isSyncing = false;
            _syncPulseTimer.Stop();
            _syncIndicator.BackColor = _currentState == ConnectorState.AllConnected ? AccentGreen : AccentYellow;
            _syncNowBtn.Text = "\u25B6 Sync Now";
            _syncNowBtn.Enabled = true;
        }
    }

    private async Task CheckUpdateAsync()
    {
        if (_autoUpdater == null) return;
        try
        {
            var update = await _autoUpdater.CheckForUpdatesAsync();
            if (update == null)
            {
                MessageBox.Show("You're on the latest version.", "Up to Date", MessageBoxButtons.OK, MessageBoxIcon.Information);
                return;
            }

            var result = MessageBox.Show(
                $"InvoSync Connector {update.LatestVersion} is ready.\n\n{update.ReleaseNotes}\n\nRestart now to apply?",
                "Update Available", MessageBoxButtons.YesNo, MessageBoxIcon.Information);

            if (result == DialogResult.Yes)
            {
                var path = await _autoUpdater.DownloadUpdateAsync(update.DownloadUrl);
                if (path != null)
                    _autoUpdater.ApplyUpdateAndRestart(path);
            }
        }
        catch (Exception ex) { _log?.LogError(ex, "Update check failed"); }
    }

    private void ViewLogs()
    {
        try
        {
            if (_connectorLogger == null)
            {
                MessageBox.Show("Logger not initialized.", "Logs", MessageBoxButtons.OK, MessageBoxIcon.Information);
                return;
            }
            var logPath = _connectorLogger.TodayLogPath;
            if (File.Exists(logPath))
                Process.Start(new ProcessStartInfo(logPath) { UseShellExecute = true });
            else
                MessageBox.Show("No logs for today yet.", "Logs", MessageBoxButtons.OK, MessageBoxIcon.Information);
        }
        catch (Exception ex) { MessageBox.Show($"Could not open logs: {ex.Message}", "Error", MessageBoxButtons.OK, MessageBoxIcon.Error); }
    }

    private async Task RunDiagnosticAsync()
    {
        try
        {
            var path = await _diagnosticReporter.GenerateReportAsync();
            Process.Start(new ProcessStartInfo("notepad.exe", path) { UseShellExecute = true });
            _trayIcon.ShowBalloonTip(2000, "Diagnostics", $"Report saved\n{path}", ToolTipIcon.Info);
        }
        catch (Exception ex) { MessageBox.Show($"Diagnostic failed: {ex.Message}", "Error", MessageBoxButtons.OK, MessageBoxIcon.Error); }
    }

    private void ShowSettings()
    {
        var settingsForm = new Form
        {
            Text = "Settings",
            Size = new Size(520, 460),
            StartPosition = FormStartPosition.CenterParent,
            FormBorderStyle = FormBorderStyle.FixedDialog,
            MaximizeBox = false,
            MinimizeBox = false,
            BackColor = BgDark,
            ForeColor = TextPrimary,
            Font = new Font("Segoe UI", 10),
        };

        var panel = new FlowLayoutPanel { Dock = DockStyle.Fill, Padding = new Padding(20), FlowDirection = FlowDirection.TopDown, BackColor = BgDark, AutoScroll = true };

        // Tally Connection
        panel.Controls.Add(SectionLabel("Tally Connection"));

        var portPanel = new FlowLayoutPanel { AutoSize = true, Margin = new Padding(0, 6, 0, 0) };
        portPanel.Controls.Add(new Label { Text = "Port:", ForeColor = TextSecondary, AutoSize = true, Margin = new Padding(0, 4, 8, 0) });
        var portBox = new TextBox { Text = "9000", Width = 80, BackColor = BgCard, ForeColor = TextPrimary, BorderStyle = BorderStyle.FixedSingle };
        portPanel.Controls.Add(portBox);
        var portStatus = new Label { Text = "", AutoSize = true, Margin = new Padding(8, 4, 0, 0) };
        portPanel.Controls.Add(portStatus);

        var testBtn = FlatBtn("Test Connection");
        testBtn.Click += async (_, _) =>
        {
            testBtn.Enabled = false;
            testBtn.Text = "Testing...";
            portStatus.Text = "";
            try
            {
                var health = await _companyGuard.CheckHealthAsync();
                portStatus.Text = health.IsRunning ? $"\u2713 Connected — {health.ActiveCompany}" : "\u2717 Tally not responding";
                portStatus.ForeColor = health.IsRunning ? AccentGreen : AccentRed;
            }
            catch (Exception ex) { portStatus.Text = $"\u2717 {ex.Message}"; portStatus.ForeColor = AccentRed; }
            testBtn.Enabled = true;
            testBtn.Text = "Test Connection";
        };
        panel.Controls.Add(portPanel);
        panel.Controls.Add(testBtn);

        panel.Controls.Add(Space(8));

        // Startup
        panel.Controls.Add(SectionLabel("General"));
        var startupToggle = new CheckBox
        {
            Text = "Start with Windows (Recommended)",
            ForeColor = TextSecondary,
            Checked = StartupManager.IsStartupEnabled(),
            AutoSize = true,
        };
        startupToggle.CheckedChanged += (_, _) =>
        {
            if (startupToggle.Checked) StartupManager.EnableStartWithWindows();
            else StartupManager.DisableStartWithWindows();
        };
        panel.Controls.Add(startupToggle);

        panel.Controls.Add(Space(8));

        // Session
        panel.Controls.Add(SectionLabel("Session"));
        var sessionLabel = new Label
        {
            Text = _sessionManager?.IsLoggedIn == true ? "\u2713 Logged in" : "\u2717 Not logged in",
            ForeColor = _sessionManager?.IsLoggedIn == true ? AccentGreen : AccentRed,
            AutoSize = true,
        };
        panel.Controls.Add(sessionLabel);

        panel.Controls.Add(Space(8));

        // Diagnostics button
        var diagBtn = FlatBtn("Generate Diagnostic Report");
        diagBtn.Click += async (_, _) => await RunDiagnosticAsync();
        panel.Controls.Add(diagBtn);

        panel.Controls.Add(Space(8));

        // Close
        panel.Controls.Add(FlatBtn("Close", () => settingsForm.Close()));

        settingsForm.Controls.Add(panel);
        settingsForm.ShowDialog(this);
    }

    private static void ShowHelp()
    {
        MessageBox.Show(
            "InvoSync Tally Connector\n\n" +
            "1. Keep Tally Prime open on port 9000\n" +
            "2. The connector auto-syncs every 30s\n" +
            "3. Click Sync Now for immediate sync\n" +
            "4. Use Undo to revert a push\n" +
            "5. Check logs for troubleshooting\n" +
            "6. Run diagnostics for support issues\n\n" +
            $"Version: {GetConnectorVersion()}",
            "Help", MessageBoxButtons.OK, MessageBoxIcon.Information);
    }

    // ==================== HELPERS ====================

    private static string GetConnectorVersion()
    {
        var asm = System.Reflection.Assembly.GetExecutingAssembly();
        var ver = asm.GetName().Version;
        return ver != null ? $"{ver.Major}.{ver.Minor}.{ver.Build}" : "1.0.0";
    }

    private static string GetTimeAgo(DateTime time)
    {
        var diff = DateTime.Now - time;
        if (diff.TotalSeconds < 60) return "just now";
        if (diff.TotalMinutes < 60) return $"{(int)diff.TotalMinutes}m ago";
        if (diff.TotalHours < 24) return $"{(int)diff.TotalHours}h ago";
        return time.ToString("dd MMM HH:mm");
    }

    private static void UpdateCard(Panel dot, Label status, string text, Color dotColor, Color cardTint)
    {
        if (dot != null) dot.BackColor = dotColor;
        if (status != null)
        {
            status.Text = text;
            status.ForeColor = dotColor;
        }
    }

    private static void MakeRoundPanel(Panel p)
    {
        var path = new GraphicsPath();
        path.AddEllipse(0, 0, p.Width - 1, p.Height - 1);
        p.Region = new Region(path);
    }

    private static GraphicsPath RoundedRect(Rectangle r, int radius)
    {
        var path = new GraphicsPath();
        path.AddArc(r.X, r.Y, radius * 2, radius * 2, 180, 90);
        path.AddArc(r.Right - radius * 2, r.Y, radius * 2, radius * 2, 270, 90);
        path.AddArc(r.Right - radius * 2, r.Bottom - radius * 2, radius * 2, radius * 2, 0, 90);
        path.AddArc(r.X, r.Bottom - radius * 2, radius * 2, radius * 2, 90, 90);
        path.CloseFigure();
        return path;
    }

    private static Label SectionLabel(string text) => new()
    {
        Text = text,
        Font = new Font("Segoe UI", 11, FontStyle.Bold),
        ForeColor = TextPrimary,
        AutoSize = true,
    };

    private static Panel Space(int h) => new() { Height = h, Width = 1, BackColor = Color.Transparent };

    private static Button FlatBtn(string text, Action? click = null)
    {
        var btn = new Button
        {
            Text = text,
            BackColor = BtnBg,
            ForeColor = TextPrimary,
            FlatStyle = FlatStyle.Flat,
            AutoSize = true,
            Height = 30,
            Cursor = Cursors.Hand,
            Padding = new Padding(12, 0, 12, 0),
        };
        btn.FlatAppearance.BorderSize = 0;
        if (click != null) btn.Click += (_, _) => click();
        return btn;
    }

    // ==================== WIN32 API FOR DRAG ====================

    [DllImport("user32.dll")]
    private static extern bool ReleaseCapture();

    [DllImport("user32.dll")]
    private static extern nint SendMessage(nint hWnd, int msg, nint wParam, nint lParam);

    private const int WM_NCLBUTTONDOWN = 0xA1;
    private const int HT_CAPTION = 0x2;
}
