using System.Diagnostics;
using System.Net.Http.Json;
using System.Text.Json;
using InvoSync.TallyConnector.Services;

namespace InvoSync.TallyConnector.Forms;

public class SetupWizard : Form
{
    private readonly IHttpClientFactory _httpFactory;
    private readonly ILogger<SetupWizard> _log;
    private readonly CompanyGuard _companyGuard;
    private readonly SessionManager _sessionManager;
    private int _step = 0;
    private Panel _contentPanel;
    private Label _stepTitle;
    private Label _stepDesc;
    private Button _backBtn, _nextBtn;
    private string _sessionToken = "";
    private string _refreshToken = "";
    private string _userEmail = "";
    private string _tallyCompany = "";
    private bool _tallyDetected;

    public SetupWizard(IHttpClientFactory httpFactory, CompanyGuard companyGuard,
        SessionManager sessionManager, ILogger<SetupWizard> log)
    {
        _httpFactory = httpFactory;
        _companyGuard = companyGuard;
        _sessionManager = sessionManager;
        _log = log;
        InitializeForm();
        ShowStep(0);
    }

    private void InitializeForm()
    {
        Text = "InvoSync Setup";
        Size = new Size(560, 420);
        StartPosition = FormStartPosition.CenterScreen;
        FormBorderStyle = FormBorderStyle.FixedDialog;
        MaximizeBox = false;
        MinimizeBox = false;
        BackColor = Color.FromArgb(30, 30, 30);
        ForeColor = Color.White;
        Font = new Font("Segoe UI", 10);

        var mainPanel = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            Padding = new Padding(24),
            ColumnCount = 1,
            RowCount = 4,
        };
        mainPanel.RowStyles.Add(new RowStyle(SizeType.Absolute, 60));
        mainPanel.RowStyles.Add(new RowStyle(SizeType.Absolute, 30));
        mainPanel.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        mainPanel.RowStyles.Add(new RowStyle(SizeType.Absolute, 50));

        var logo = new Label
        {
            Text = "InvoSync Connector",
            Font = new Font("Segoe UI", 18, FontStyle.Bold),
            ForeColor = Color.FromArgb(0, 200, 150),
            Dock = DockStyle.Fill,
            TextAlign = ContentAlignment.MiddleLeft,
        };
        mainPanel.Controls.Add(logo, 0, 0);

        _stepTitle = new Label
        {
            Font = new Font("Segoe UI", 13, FontStyle.Bold),
            ForeColor = Color.White,
            Dock = DockStyle.Fill,
            TextAlign = ContentAlignment.MiddleLeft,
        };
        mainPanel.Controls.Add(_stepTitle, 0, 1);

        _contentPanel = new Panel { Dock = DockStyle.Fill };
        mainPanel.Controls.Add(_contentPanel, 0, 2);

        var btnPanel = new FlowLayoutPanel { Dock = DockStyle.Fill, FlowDirection = FlowDirection.RightToLeft };
        _nextBtn = new Button
        {
            Text = "Next →",
            BackColor = Color.FromArgb(0, 140, 100),
            ForeColor = Color.White,
            FlatStyle = FlatStyle.Flat,
            AutoSize = true,
            Padding = new Padding(16, 6, 16, 6),
            Cursor = Cursors.Hand,
            Font = new Font("Segoe UI", 10, FontStyle.Bold),
        };
        _nextBtn.Click += async (_, _) => await OnNextAsync();
        btnPanel.Controls.Add(_nextBtn);

        _backBtn = new Button
        {
            Text = "← Back",
            BackColor = Color.FromArgb(60, 60, 60),
            ForeColor = Color.White,
            FlatStyle = FlatStyle.Flat,
            AutoSize = true,
            Padding = new Padding(16, 6, 16, 6),
            Cursor = Cursors.Hand,
            Margin = new Padding(0, 0, 8, 0),
        };
        _backBtn.Click += (_, _) =>
        {
            _sessionToken = "";
            _refreshToken = "";
            _step -= 2;
            ShowStep(_step + 1);
        };
        btnPanel.Controls.Add(_backBtn);

        mainPanel.Controls.Add(btnPanel, 0, 3);
        Controls.Add(mainPanel);
    }

    private void ShowStep(int step)
    {
        _step = step;
        _contentPanel.Controls.Clear();

        _backBtn.Visible = step > 0;
        _nextBtn.Text = step == 5 ? "Finish" : "Next →";

        switch (step)
        {
            case 0: ShowWelcome(); break;
            case 1: ShowLogin(); break;
            case 2: ShowDetectTally(); break;
            case 3: ShowConfirmCompany(); break;
            case 4: ShowStartup(); break;
            case 5: ShowDone(); break;
        }
    }

    private void ShowWelcome()
    {
        _stepTitle.Text = "Welcome to InvoSync!";
        var lbl = new Label
        {
            Text = "This wizard will connect your TallyPrime to InvoSync.\n\n" +
                   "Setup takes about 2 minutes.\n\n" +
                   "You'll need:\n" +
                   "  • Your InvoSync login credentials\n" +
                   "  • TallyPrime open on this computer",
            ForeColor = Color.LightGray,
            Dock = DockStyle.Fill,
            TextAlign = ContentAlignment.TopLeft,
        };
        _contentPanel.Controls.Add(lbl);
        _nextBtn.Enabled = true;
    }

    private async Task OnNextAsync()
    {
        if (_step == 5)
        {
            // Persist session only on wizard completion
            _sessionManager.SaveSession(_sessionToken, _refreshToken, _userEmail);
            DialogResult = DialogResult.OK;
            Close();
            return;
        }

        var canProceed = await ValidateStepAsync(_step);
        if (canProceed)
            ShowStep(_step + 1);
    }

    private async Task<bool> ValidateStepAsync(int step)
    {
        switch (step)
        {
            case 1: return await DoLoginAsync();
            case 2: return await DoDetectTallyAsync();
            case 4: DoSaveStartup(); return true;
            default: return true;
        }
    }

    // === Step 1 — Login ===
    private void ShowLogin()
    {
        _stepTitle.Text = "Sign in to InvoSync";
        var panel = new FlowLayoutPanel { Dock = DockStyle.Fill, FlowDirection = FlowDirection.TopDown, Padding = new Padding(0, 12, 0, 0) };

        panel.Controls.Add(new Label { Text = "Email:", ForeColor = Color.LightGray, AutoSize = true });
        var emailBox = new TextBox { Width = 320, BackColor = Color.FromArgb(50, 50, 50), ForeColor = Color.White, BorderStyle = BorderStyle.FixedSingle };
        panel.Controls.Add(emailBox);

        panel.Controls.Add(new Label { Text = "Password:", ForeColor = Color.LightGray, AutoSize = true, Margin = new Padding(0, 8, 0, 0) });
        var passBox = new TextBox { Width = 320, BackColor = Color.FromArgb(50, 50, 50), ForeColor = Color.White, BorderStyle = BorderStyle.FixedSingle, UseSystemPasswordChar = true };
        panel.Controls.Add(passBox);

        var statusLabel = new Label { Text = "", ForeColor = Color.Red, AutoSize = true };
        panel.Controls.Add(statusLabel);

        _contentPanel.Controls.Add(panel);

        emailBox.Tag = "email";
        passBox.Tag = "pass";
        statusLabel.Tag = "status";

        _nextBtn.Enabled = true;
    }

    private async Task<bool> DoLoginAsync()
    {
        var email = FindControl("email")?.Text?.Trim() ?? "";
        var pass = FindControl("pass")?.Text ?? "";

        if (string.IsNullOrEmpty(email) || string.IsNullOrEmpty(pass))
        {
            SetStatus("Enter email and password", Color.Red);
            return false;
        }

        _nextBtn.Enabled = false;
        _nextBtn.Text = "Signing in...";

        try
        {
            var client = _httpFactory.CreateClient("InvoSync");
            var payload = JsonContent.Create(new { email, password = pass });
            var resp = await client.PostAsync("/api/auth/login", payload);

            if (resp.IsSuccessStatusCode)
            {
                var json = await resp.Content.ReadAsStringAsync();
                var data = JsonSerializer.Deserialize<JsonElement>(json);
                _sessionToken = data.TryGetProperty("token", out var t) ? t.GetString() ?? "" : "";
                _refreshToken = data.TryGetProperty("refresh_token", out var rt) ? rt.GetString() ?? "" : "";
                _userEmail = email;

                // Not persisted yet — only on wizard completion
                SetStatus("✓ Login successful", Color.LimeGreen);
                await Task.Delay(500);
                return true;
            }
            else
            {
                SetStatus("✗ Invalid email or password", Color.Red);
                return false;
            }
        }
        catch (Exception ex)
        {
            SetStatus($"✗ Could not reach server: {ex.Message}", Color.Red);
            return false;
        }
        finally
        {
            _nextBtn.Enabled = true;
            _nextBtn.Text = "Next →";
        }
    }

    // === Step 2 — Detect Tally ===
    private void ShowDetectTally()
    {
        _stepTitle.Text = "Detecting TallyPrime";
        var panel = new FlowLayoutPanel { Dock = DockStyle.Fill, FlowDirection = FlowDirection.TopDown, Padding = new Padding(0, 16, 0, 0) };

        var spinner = new Label { Text = "⏳ Checking...", ForeColor = Color.Yellow, AutoSize = true, Font = new Font("Segoe UI", 12) };
        panel.Controls.Add(spinner);

        var statusLabel = new Label { Text = "Make sure TallyPrime is open on this computer", ForeColor = Color.LightGray, AutoSize = true, Margin = new Padding(0, 8, 0, 0) };
        panel.Controls.Add(statusLabel);

        var retryBtn = new Button
        {
            Text = "Retry",
            BackColor = Color.FromArgb(60, 60, 60),
            ForeColor = Color.White,
            FlatStyle = FlatStyle.Flat,
            AutoSize = true,
            Visible = false,
            Margin = new Padding(0, 12, 0, 0),
            Cursor = Cursors.Hand,
        };
        retryBtn.Click += async (_, _) => await DoDetectTallyAsync();
        panel.Controls.Add(retryBtn);

        _contentPanel.Controls.Add(panel);

        spinner.Tag = "spinner";
        statusLabel.Tag = "status";
        retryBtn.Tag = "retry";

        _nextBtn.Enabled = false;
        _ = DoDetectTallyAsync();
    }

    private async Task<bool> DoDetectTallyAsync()
    {
        var spinner = FindControl("spinner");
        var statusLabel = FindControl("status");
        var retryBtn = FindControl("retry");
        bool found = false;

        for (int i = 0; i < 15; i++)
        {
            try
            {
                var health = await _companyGuard.CheckHealthAsync();
                if (health.IsRunning)
                {
                    _tallyCompany = health.ActiveCompany ?? "";
                    _tallyDetected = true;
                    found = true;
                    break;
                }
            }
            catch { }
            await Task.Delay(2000);
        }

        if (found && spinner != null && statusLabel != null)
        {
            spinner.Text = "✓ TallyPrime detected";
            spinner.ForeColor = Color.LimeGreen;
            statusLabel.Text = $"Company: {_tallyCompany}";
            statusLabel.ForeColor = Color.LimeGreen;
            _nextBtn.Enabled = true;
        }
        else
        {
            if (spinner != null)
            {
                spinner.Text = "✗ TallyPrime not found";
                spinner.ForeColor = Color.Red;
            }
            if (statusLabel != null)
                statusLabel.Text = "Open TallyPrime and click Retry";
            if (retryBtn != null) retryBtn.Visible = true;
            _nextBtn.Enabled = false;
        }
        if (retryBtn != null) retryBtn.Visible = !found;
        return found;
    }

    // === Step 3 — Confirm Company ===
    private void ShowConfirmCompany()
    {
        _stepTitle.Text = "Confirm Tally Company";
        var panel = new FlowLayoutPanel { Dock = DockStyle.Fill, FlowDirection = FlowDirection.TopDown, Padding = new Padding(0, 16, 0, 0) };

        panel.Controls.Add(new Label
        {
            Text = $"Push invoices to:",
            ForeColor = Color.LightGray,
            AutoSize = true,
        });

        panel.Controls.Add(new Label
        {
            Text = _tallyCompany,
            Font = new Font("Segoe UI", 16, FontStyle.Bold),
            ForeColor = Color.White,
            AutoSize = true,
            Margin = new Padding(0, 8, 0, 0),
        });

        _contentPanel.Controls.Add(panel);
        _nextBtn.Enabled = true;
    }

    // === Step 4 — Windows Startup ===
    private void ShowStartup()
    {
        _stepTitle.Text = "Start with Windows?";
        var panel = new FlowLayoutPanel { Dock = DockStyle.Fill, FlowDirection = FlowDirection.TopDown, Padding = new Padding(0, 16, 0, 0) };

        var toggle = new CheckBox
        {
            Text = "Start InvoSync automatically when I start Windows (Recommended)",
            ForeColor = Color.LightGray,
            Checked = true,
            AutoSize = true,
            Font = new Font("Segoe UI", 10),
        };
        panel.Controls.Add(toggle);

        panel.Controls.Add(new Label
        {
            Text = "InvoSync will run in the system tray.\nNo need to open it manually.",
            ForeColor = Color.Gray,
            AutoSize = true,
            Margin = new Padding(24, 8, 0, 0),
        });

        _contentPanel.Controls.Add(panel);
        toggle.Tag = "toggle";
        _nextBtn.Enabled = true;
    }

    private void DoSaveStartup()
    {
        var toggle = FindControl("toggle") as CheckBox;
        if (toggle?.Checked == true)
        {
            StartupManager.EnableStartWithWindows();
        }
    }

    // === Step 5 — Done ===
    private void ShowDone()
    {
        _stepTitle.Text = "Setup Complete!";
        var panel = new FlowLayoutPanel { Dock = DockStyle.Fill, FlowDirection = FlowDirection.TopDown, Padding = new Padding(0, 24, 0, 0) };

        panel.Controls.Add(new Label
        {
            Text = "✅",
            Font = new Font("Segoe UI", 36),
            AutoSize = true,
            ForeColor = Color.LimeGreen,
        });

        panel.Controls.Add(new Label
        {
            Text = "Your TallyPrime is now connected to InvoSync",
            ForeColor = Color.White,
            AutoSize = true,
            Font = new Font("Segoe UI", 12),
            Margin = new Padding(0, 12, 0, 0),
        });

        panel.Controls.Add(new Label
        {
            Text = "Invoices will appear in Tally automatically.\nUpload invoices from the InvoSync web app.",
            ForeColor = Color.Gray,
            AutoSize = true,
            Margin = new Padding(0, 8, 0, 0),
        });

        var webBtn = new Button
        {
            Text = "Open InvoSync Web App",
            BackColor = Color.FromArgb(0, 140, 100),
            ForeColor = Color.White,
            FlatStyle = FlatStyle.Flat,
            AutoSize = true,
            Padding = new Padding(20, 8, 20, 8),
            Margin = new Padding(0, 20, 0, 0),
            Cursor = Cursors.Hand,
        };
        webBtn.Click += (_, _) =>
        {
            try
            {
                var psi = new ProcessStartInfo("https://invosync-backend-yjfa.onrender.com") { UseShellExecute = true };
                Process.Start(psi);
            }
            catch { }
        };
        panel.Controls.Add(webBtn);

        _contentPanel.Controls.Add(panel);

        _backBtn.Visible = false;
        _nextBtn.Text = "Finish";
    }

    private Control? FindControl(string tag)
    {
        foreach (Control c in _contentPanel.Controls)
        {
            if (c.Tag?.ToString() == tag) return c;
            foreach (Control child in c.Controls)
                if (child.Tag?.ToString() == tag) return child;
        }
        return null;
    }

    private void SetStatus(string text, Color color)
    {
        var status = FindControl("status");
        if (status != null) { status.Text = text; status.ForeColor = color; }
    }
}
