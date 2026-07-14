using System.Diagnostics;
using System.Net.Http.Json;
using System.Text;
using System.Text.Json;
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

    private Label _connectorDot = null!, _tallyDot = null!, _serverDot = null!;
    private Label _todayStats = null!;
    private Label _pendingStats = null!;
    private Label _failedStats = null!;
    private Label _lastSyncLabel = null!;
    private DataGridView _recentGrid = null!;
    private Button _syncNowBtn = null!, _viewLogsBtn = null!, _settingsBtn = null!;
    private NotifyIcon _trayIcon = null!;
    private ContextMenuStrip _trayMenu = null!;
    private System.Windows.Forms.Timer _refreshTimer = null!;
    private Label _versionLabel = null!;
    private TableLayoutPanel mainPanel = null!;

    private List<InvoiceDto> _pendingInvoices = new();
    private bool _isSyncing;
    private DateTime _lastSyncTime = DateTime.MinValue;

    public MainForm(IHttpClientFactory httpFactory, TallyPusher pusher, QueueManager queue,
        TallyCompanySyncer companySyncer, AutoUpdater autoUpdater,
        AutoRecoveryService autoRecovery, SyncWatchdog watchdog,
        RecentPushStore recentPushes, ConnectorLogger connectorLogger,
        DiagnosticReporter diagnosticReporter, SessionManager sessionManager,
        CompanyGuard companyGuard, ILogger<MainForm> log)
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
        _log = log;

        mainPanel = new TableLayoutPanel { Dock = DockStyle.Fill, RowCount = 6, ColumnCount = 1 };
        mainPanel.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        mainPanel.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        mainPanel.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        mainPanel.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        mainPanel.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        mainPanel.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        mainPanel.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));

        // === Header ===
        var headerPanel = new FlowLayoutPanel { Dock = DockStyle.Fill, FlowDirection = FlowDirection.LeftToRight };
        headerPanel.Controls.Add(new Label
        {
            Text = "InvoSync Connector",
            Font = new Font("Segoe UI", 14, FontStyle.Bold),
            ForeColor = Color.FromArgb(0, 200, 150),
            AutoSize = true,
            TextAlign = ContentAlignment.MiddleLeft,
        });
        _versionLabel = new Label
        {
            Text = "v1.0.0",
            ForeColor = Color.Gray,
            AutoSize = true,
            Margin = new Padding(8, 8, 0, 0),
            TextAlign = ContentAlignment.MiddleLeft,
        };
        headerPanel.Controls.Add(_versionLabel);
        mainPanel.Controls.Add(headerPanel, 0, 0);

        // === Status dots ===
        var statusPanel = new FlowLayoutPanel { Dock = DockStyle.Fill, FlowDirection = FlowDirection.LeftToRight, Padding = new Padding(0, 8, 0, 8) };

        statusPanel.Controls.Add(MakeStatusDot("Connector", ref _connectorDot));
        statusPanel.Controls.Add(MakeStatusDot("Tally", ref _tallyDot));
        statusPanel.Controls.Add(MakeStatusDot("InvoSync", ref _serverDot));

        mainPanel.Controls.Add(statusPanel, 0, 1);

        // === Stats row ===
        var statsPanel = new FlowLayoutPanel { Dock = DockStyle.Fill, FlowDirection = FlowDirection.LeftToRight, Padding = new Padding(0, 4, 0, 4) };
        _todayStats = MakeStatLabel("Today: —", Color.FromArgb(0, 200, 150));
        _pendingStats = MakeStatLabel("Pending: —", Color.FromArgb(100, 180, 255));
        _failedStats = MakeStatLabel("Failed: —", Color.FromArgb(255, 120, 100));
        _lastSyncLabel = MakeStatLabel("Last sync: Never", Color.Gray);
        statsPanel.Controls.Add(_todayStats);
        statsPanel.Controls.Add(_pendingStats);
        statsPanel.Controls.Add(_failedStats);
        statsPanel.Controls.Add(_lastSyncLabel);
        mainPanel.Controls.Add(statsPanel, 0, 2);

        // === Recent pushes grid ===
        var gridPanel = new Panel { Dock = DockStyle.Fill };
        var gridHeader = new Label
        {
            Text = "Recent Activity",
            Font = new Font("Segoe UI", 11, FontStyle.Bold),
            ForeColor = Color.LightGray,
            Dock = DockStyle.Top,
            Height = 24,
        };

        _recentGrid = new DataGridView
        {
            Dock = DockStyle.Fill,
            AllowUserToAddRows = false,
            AllowUserToDeleteRows = false,
            ReadOnly = true,
            RowHeadersVisible = false,
            SelectionMode = DataGridViewSelectionMode.FullRowSelect,
            BackgroundColor = Color.FromArgb(40, 40, 40),
            ForeColor = Color.White,
            GridColor = Color.FromArgb(60, 60, 60),
            BorderStyle = BorderStyle.None,
            AutoSizeColumnsMode = DataGridViewAutoSizeColumnsMode.Fill,
        };
        _recentGrid.Columns.Add("Time", "Time");
        _recentGrid.Columns.Add("Invoice", "Invoice #");
        _recentGrid.Columns.Add("Status", "Status");
        _recentGrid.Columns.Add("Error", "Error");
        _recentGrid.Columns[0].Width = 80;
        _recentGrid.Columns[1].Width = 120;
        _recentGrid.Columns[2].Width = 80;
        _recentGrid.Columns[3].AutoSizeMode = DataGridViewAutoSizeColumnMode.Fill;
        _recentGrid.ColumnHeadersDefaultCellStyle.BackColor = Color.FromArgb(50, 50, 50);
        _recentGrid.ColumnHeadersDefaultCellStyle.ForeColor = Color.LightGray;
        _recentGrid.EnableHeadersVisualStyles = false;
        _recentGrid.CellFormatting += (s, e) =>
        {
            if (e.RowIndex >= 0 && e.ColumnIndex == 2)
            {
                var val = _recentGrid.Rows[e.RowIndex].Cells[2].Value?.ToString();
                if (val == "✓ Success")
                    e.CellStyle.ForeColor = Color.FromArgb(0, 200, 150);
                else if (val == "✗ Failed")
                    e.CellStyle.ForeColor = Color.FromArgb(255, 120, 100);
            }
        };

        gridPanel.Controls.Add(gridHeader);
        gridPanel.Controls.Add(_recentGrid);

        mainPanel.Controls.Add(gridPanel, 0, 3);

        // === Action buttons ===
        var btnPanel = new FlowLayoutPanel { Dock = DockStyle.Fill, FlowDirection = FlowDirection.RightToLeft, Padding = new Padding(0, 6, 0, 6) };

        _settingsBtn = new Button
        {
            Text = "⚙ Settings",
            BackColor = Color.FromArgb(60, 60, 60),
            ForeColor = Color.White,
            FlatStyle = FlatStyle.Flat,
            AutoSize = true,
            Margin = new Padding(4, 0, 0, 0),
            Cursor = Cursors.Hand,
        };
        _settingsBtn.Click += (_, _) => ShowSettings();
        btnPanel.Controls.Add(_settingsBtn);

        _viewLogsBtn = new Button
        {
            Text = "📄 View Logs",
            BackColor = Color.FromArgb(60, 60, 60),
            ForeColor = Color.White,
            FlatStyle = FlatStyle.Flat,
            AutoSize = true,
            Margin = new Padding(4, 0, 0, 0),
            Cursor = Cursors.Hand,
        };
        _viewLogsBtn.Click += (_, _) => ViewLogs();
        btnPanel.Controls.Add(_viewLogsBtn);

        _syncNowBtn = new Button
        {
            Text = "▶ Sync Now",
            BackColor = Color.FromArgb(0, 140, 100),
            ForeColor = Color.White,
            FlatStyle = FlatStyle.Flat,
            AutoSize = true,
            Margin = new Padding(4, 0, 0, 0),
            Cursor = Cursors.Hand,
            Font = new Font("Segoe UI", 10, FontStyle.Bold),
        };
        _syncNowBtn.Click += async (_, _) => await SyncNowAsync();
        btnPanel.Controls.Add(_syncNowBtn);

        mainPanel.Controls.Add(btnPanel, 0, 4);

        // === Footer ===
        var footerLabel = new Label
        {
            Dock = DockStyle.Fill,
            Text = "",
            ForeColor = Color.Gray,
            TextAlign = ContentAlignment.MiddleLeft,
            Font = new Font("Segoe UI", 8),
        };
        mainPanel.Controls.Add(footerLabel, 0, 5);

        Controls.Add(mainPanel);

        SetupTrayIcon();
    }

    private static FlowLayoutPanel MakeStatusDot(string label, ref Label dotRef)
    {
        var panel = new FlowLayoutPanel { AutoSize = true, Margin = new Padding(0, 0, 20, 0) };
        dotRef = new Label
        {
            Text = "●",
            ForeColor = Color.Gray,
            AutoSize = true,
            Font = new Font("Segoe UI", 12),
            Margin = new Padding(0, 0, 4, 0),
        };
        panel.Controls.Add(dotRef);
        panel.Controls.Add(new Label { Text = label, AutoSize = true, ForeColor = Color.LightGray });
        return panel;
    }

    private static Label MakeStatLabel(string text, Color color)
    {
        return new Label
        {
            Text = text,
            AutoSize = true,
            ForeColor = color,
            Font = new Font("Segoe UI", 12, FontStyle.Bold),
            Margin = new Padding(0, 0, 24, 0),
        };
    }

    private void SetupTrayIcon()
    {
        _trayMenu = new ContextMenuStrip();
        _trayMenu.Items.Add("Show InvoSync", null, (_, _) => { Show(); WindowState = FormWindowState.Normal; });
        _trayMenu.Items.Add("Sync Now", null, async (_, _) => await SyncNowAsync());
        _trayMenu.Items.Add("View Pending", null, async (_, _) => { Show(); WindowState = FormWindowState.Normal; });
        _trayMenu.Items.Add(new ToolStripSeparator());
        _trayMenu.Items.Add("Open Web App", null, async (_, _) =>
        {
            try { Process.Start(new ProcessStartInfo("https://invosync-backend-yjfa.onrender.com") { UseShellExecute = true }); }
            catch { }
        });
        _trayMenu.Items.Add("Check for Updates", null, async (_, _) => await CheckUpdateAsync());
        _trayMenu.Items.Add(new ToolStripSeparator());
        _trayMenu.Items.Add("About", null, (_, _) => MessageBox.Show("InvoSync Tally Connector v1.0.0", "About", MessageBoxButtons.OK, MessageBoxIcon.Information));
        _trayMenu.Items.Add("Exit", null, (_, _) => { _trayIcon.Visible = false; Application.Exit(); });

        _trayIcon = new NotifyIcon
        {
            Icon = TrayIconProvider.GetIcon(ConnectorState.AllConnected),
            Text = "InvoSync Connector",
            Visible = true,
            ContextMenuStrip = _trayMenu,
        };
        _trayIcon.DoubleClick += (_, _) => { Show(); WindowState = FormWindowState.Normal; };

        _refreshTimer = new System.Windows.Forms.Timer { Interval = 15000 };
        _refreshTimer.Tick += async (_, _) =>
        {
            try { await RefreshAllAsync(); }
            catch (Exception ex) { _log?.LogError(ex, "Refresh timer error"); }
        };
        _refreshTimer.Start();
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
        if (InvokeRequired)
        {
            BeginInvoke(new Action(async () => await RefreshAllAsync()));
            return;
        }

        try
        {
            UpdateDots(_connectorDot, Color.Yellow);
            UpdateDots(_tallyDot, Color.Gray);
            UpdateDots(_serverDot, Color.Gray);

            int pendingCount = 0;
            bool tallyOnline = false;
            bool serverOnline = false;

            try
            {
                var client = _httpFactory.CreateClient("InvoSync");
                using var cts = new CancellationTokenSource(TimeSpan.FromSeconds(10));
                var ping = await client.GetAsync("/health", cts.Token);
                serverOnline = ping.IsSuccessStatusCode;
            }
            catch (OperationCanceledException)
            {
                _log?.LogWarning("Backend health check timed out");
            }
            catch (Exception ex)
            {
                _log?.LogDebug(ex, "Backend health check failed");
            }

            try
            {
                tallyOnline = await _companySyncer.RunStartupDiagnosticCheckAsync(CancellationToken.None);
            }
            catch (Exception ex)
            {
                _log?.LogDebug(ex, "Tally diagnostic failed");
            }

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
            catch (OperationCanceledException)
            {
                _log?.LogWarning("Pending invoices fetch timed out");
            }
            catch (Exception ex)
            {
                _log?.LogDebug(ex, "Pending invoices fetch failed");
            }

            var connectorState = serverOnline && tallyOnline
                ? ConnectorState.AllConnected
                : !tallyOnline ? ConnectorState.TallyClosed : ConnectorState.ServerDisconnected;

            UpdateDots(_connectorDot, connectorState == ConnectorState.AllConnected ? Color.LimeGreen : connectorState == ConnectorState.TallyClosed ? Color.Orange : Color.Red);
            UpdateDots(_tallyDot, tallyOnline ? Color.LimeGreen : Color.Red);
            UpdateDots(_serverDot, serverOnline ? Color.LimeGreen : Color.Red);

            _trayIcon.Icon = TrayIconProvider.GetIcon(_isSyncing ? ConnectorState.Syncing : connectorState);
            _trayIcon.Text = TrayIconProvider.GetText(connectorState, pendingCount);

            UpdateStats(pendingCount);
            UpdateRecentGrid();
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
        _todayStats.Text = $"Today: {pushed} ✓";
        _pendingStats.Text = $"Pending: {pendingCount}";
        _failedStats.Text = $"Failed: {failed}";
        _lastSyncLabel.Text = _lastSyncTime == DateTime.MinValue
            ? "Last sync: Never"
            : $"Last sync: {GetTimeAgo(_lastSyncTime)}";
    }

    private static string GetTimeAgo(DateTime time)
    {
        var diff = DateTime.Now - time;
        if (diff.TotalSeconds < 60) return "just now";
        if (diff.TotalMinutes < 60) return $"{(int)diff.TotalMinutes}m ago";
        if (diff.TotalHours < 24) return $"{(int)diff.TotalHours}h ago";
        return time.ToString("dd MMM HH:mm");
    }

    private void UpdateRecentGrid()
    {
        if (_recentGrid == null || _recentPushes == null) return;
        _recentGrid.Rows.Clear();
        foreach (var entry in _recentPushes.GetRecent(50))
        {
            _recentGrid.Rows.Add(
                entry.Timestamp.ToString("HH:mm:ss"),
                $"#{entry.DisplayId}",
                entry.Success ? "✓ Success" : "✗ Failed",
                entry.Error ?? "");
        }
    }

    private static void UpdateDots(Label dot, Color color)
    {
        if (dot != null) dot.ForeColor = color;
    }

    private async Task SyncNowAsync()
    {
        if (_isSyncing) return;
        _isSyncing = true;
        _syncNowBtn.Text = "⟳ Syncing...";
        _syncNowBtn.Enabled = false;
        _trayIcon.Icon = TrayIconProvider.GetIcon(ConnectorState.Syncing);

        try
        {
            var invs = _pendingInvoices?.Where(i => !string.IsNullOrWhiteSpace(i.XmlContent)).ToList() ?? new List<InvoiceDto>();
            if (invs.Count == 0)
            {
                _trayIcon.ShowBalloonTip(2000, "InvoSync", "No pending invoices to sync", ToolTipIcon.Info);
                return;
            }

            foreach (var inv in invs)
            {
                var client = _httpFactory.CreateClient("InvoSync");
                using var cts = new CancellationTokenSource(TimeSpan.FromSeconds(120));
                var result = await _pusher.PushAsync(inv.XmlContent!, cts.Token, maxRetries: 3);

                if (result.Success)
                {
                    _recentPushes?.Add(new RecentPushEntry
                    {
                        Timestamp = DateTime.Now,
                        DisplayId = inv.DisplayId,
                        InvoiceNumber = inv.InvoiceNumber ?? "?",
                        VendorName = inv.VendorName ?? "?",
                        Amount = inv.TotalAmount,
                        Success = true,
                    });
                    _connectorLogger?.TallyPush(inv.DisplayId.ToString(), true);
                    try
                    {
                        using var postCts = new CancellationTokenSource(TimeSpan.FromSeconds(10));
                        await client.PostAsync($"/api/v3/sync/confirm/{inv.DisplayId}", null, postCts.Token);
                    }
                    catch (Exception ex)
                    {
                        _log?.LogDebug(ex, "Confirm endpoint failed for invoice {Id}", inv.DisplayId);
                    }
                }
                else
                {
                    _recentPushes?.Add(new RecentPushEntry
                    {
                        Timestamp = DateTime.Now,
                        DisplayId = inv.DisplayId,
                        InvoiceNumber = inv.InvoiceNumber ?? "?",
                        Success = false,
                        Error = result.ErrorLine,
                    });
                    _connectorLogger?.TallyPush(inv.DisplayId.ToString(), false, result.ErrorLine);
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
            _syncNowBtn.Text = "▶ Sync Now";
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
        catch (Exception ex)
        {
            _log?.LogError(ex, "Update check failed");
        }
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
        catch (Exception ex)
        {
            MessageBox.Show($"Could not open logs: {ex.Message}", "Error", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }

    private void ShowSettings()
    {
        var settingsForm = new Form
        {
            Text = "Settings",
            Size = new Size(480, 400),
            StartPosition = FormStartPosition.CenterParent,
            FormBorderStyle = FormBorderStyle.FixedDialog,
            MaximizeBox = false,
            MinimizeBox = false,
            BackColor = Color.FromArgb(30, 30, 30),
            ForeColor = Color.White,
            Font = new Font("Segoe UI", 10),
        };

        var panel = new FlowLayoutPanel { Dock = DockStyle.Fill, Padding = new Padding(20), FlowDirection = FlowDirection.TopDown };

        panel.Controls.Add(new Label { Text = "Tally Connection", Font = new Font("Segoe UI", 12, FontStyle.Bold), ForeColor = Color.White, AutoSize = true });

        var portPanel = new FlowLayoutPanel { AutoSize = true, Margin = new Padding(0, 8, 0, 0) };
        portPanel.Controls.Add(new Label { Text = "Port:", ForeColor = Color.LightGray, AutoSize = true, Margin = new Padding(0, 4, 8, 0) });
        var portBox = new TextBox { Text = "9000", Width = 80, BackColor = Color.FromArgb(50, 50, 50), ForeColor = Color.White, BorderStyle = BorderStyle.FixedSingle };
        portPanel.Controls.Add(portBox);
        var portStatus = new Label { Text = "", AutoSize = true, Margin = new Padding(8, 4, 0, 0) };
        portPanel.Controls.Add(portStatus);

        var testBtn = new Button
        {
            Text = "Test Connection",
            BackColor = Color.FromArgb(60, 60, 60),
            ForeColor = Color.White,
            FlatStyle = FlatStyle.Flat,
            AutoSize = true,
            Margin = new Padding(0, 4, 0, 0),
            Cursor = Cursors.Hand,
        };
        testBtn.Click += async (_, _) =>
        {
            testBtn.Enabled = false;
            testBtn.Text = "Testing...";
            portStatus.Text = "";
            try
            {
                if (_companyGuard == null)
                {
                    portStatus.Text = "✗ CompanyGuard not initialized";
                    portStatus.ForeColor = Color.Red;
                    return;
                }
                var health = await _companyGuard.CheckHealthAsync();
                if (health.IsRunning)
                {
                    portStatus.Text = $"✓ Connected — {health.ActiveCompany}";
                    portStatus.ForeColor = Color.LimeGreen;
                }
                else
                {
                    portStatus.Text = "✗ Tally not responding. Is it open?";
                    portStatus.ForeColor = Color.Red;
                }
            }
            catch (Exception ex)
            {
                portStatus.Text = $"✗ {ex.Message}";
                portStatus.ForeColor = Color.Red;
            }
            testBtn.Enabled = true;
            testBtn.Text = "Test Connection";
        };
        panel.Controls.Add(testBtn);
        panel.Controls.Add(portPanel);

        panel.Controls.Add(new Label { Text = "", Height = 12 });

        var startupToggle = new CheckBox
        {
            Text = "Start with Windows (Recommended)",
            ForeColor = Color.LightGray,
            Checked = StartupManager.IsStartupEnabled(),
            AutoSize = true,
        };
        startupToggle.CheckedChanged += (_, _) =>
        {
            if (startupToggle.Checked) StartupManager.EnableStartWithWindows();
            else StartupManager.DisableStartWithWindows();
        };
        panel.Controls.Add(startupToggle);

        panel.Controls.Add(new Label { Text = "", Height = 12 });

        panel.Controls.Add(new Label { Text = "Session", Font = new Font("Segoe UI", 12, FontStyle.Bold), ForeColor = Color.White, AutoSize = true });
        var sessionLabel = new Label
        {
            Text = _sessionManager?.IsLoggedIn == true ? "✓ Logged in" : "✗ Not logged in",
            ForeColor = _sessionManager?.IsLoggedIn == true ? Color.LimeGreen : Color.Red,
            AutoSize = true,
        };
        panel.Controls.Add(sessionLabel);

        panel.Controls.Add(new Label { Text = "", Height = 8 });

        var diagBtn = new Button
        {
            Text = "🔍 Generate Diagnostic Report",
            BackColor = Color.FromArgb(100, 80, 60),
            ForeColor = Color.White,
            FlatStyle = FlatStyle.Flat,
            AutoSize = true,
            Cursor = Cursors.Hand,
        };
        diagBtn.Click += async (_, _) =>
        {
            diagBtn.Enabled = false;
            diagBtn.Text = "Generating...";
            try
            {
                if (_diagnosticReporter == null)
                {
                    MessageBox.Show("Diagnostic reporter not initialized.", "Error", MessageBoxButtons.OK, MessageBoxIcon.Error);
                    return;
                }
                var path = await _diagnosticReporter.GenerateReportAsync();
                Process.Start(new ProcessStartInfo("explorer.exe", $"/select,\"{path}\"") { UseShellExecute = true });
                MessageBox.Show($"Diagnostic report saved:\n{path}", "Done", MessageBoxButtons.OK, MessageBoxIcon.Information);
            }
            catch (Exception ex)
            {
                MessageBox.Show($"Diagnostic failed: {ex.Message}", "Error", MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
            diagBtn.Enabled = true;
            diagBtn.Text = "🔍 Generate Diagnostic Report";
        };
        panel.Controls.Add(diagBtn);

        panel.Controls.Add(new Label { Text = "", Height = 8 });

        var closeBtn = new Button
        {
            Text = "Close",
            BackColor = Color.FromArgb(60, 60, 60),
            ForeColor = Color.White,
            FlatStyle = FlatStyle.Flat,
            AutoSize = true,
            Cursor = Cursors.Hand,
        };
        closeBtn.Click += (_, _) => settingsForm.Close();
        panel.Controls.Add(closeBtn);

        settingsForm.Controls.Add(panel);
        settingsForm.ShowDialog(this);
    }
}
