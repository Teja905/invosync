using System.Diagnostics;
using InvoSync.TallyConnector;
using InvoSync.TallyConnector.Forms;
using InvoSync.TallyConnector.Services;

// === PRODUCTION SHIELD: never silently crash ===
var crashLog = AppPaths.CrashLogFile;
void WriteCrash(string label, Exception ex)
{
    try
    {
        var msg = $"[{DateTime.Now:yyyy-MM-dd HH:mm:ss}] {label}: {ex.GetType().Name}: {ex.Message}\n{ex.StackTrace}\n---";
        File.AppendAllText(crashLog, msg + Environment.NewLine);
        Console.Error.WriteLine(msg);
    }
    catch { /* best effort */ }
}

AppDomain.CurrentDomain.UnhandledException += (_, e) =>
{
    WriteCrash("UNHANDLED DOMAIN EXCEPTION", (Exception)e.ExceptionObject);
    MessageBox.Show($"InvoSync Connector crashed.\nCheck: {crashLog}\n\nThe app will restart automatically.", "Fatal Error",
        MessageBoxButtons.OK, MessageBoxIcon.Error);
    Thread.Sleep(3000);
    var exe = Environment.ProcessPath;
    if (exe != null) Process.Start(exe);
    Environment.Exit(1);
};

var _log = default(ILogger);
var _host = default(IHost);

TaskScheduler.UnobservedTaskException += (_, e) =>
{
    WriteCrash("UNOBSERVED TASK EXCEPTION", e.Exception);
    e.SetObserved();
};

// === Main startup ===
try
{
    var builder = Host.CreateApplicationBuilder(args);
    builder.Services.AddSingleton<QueueManager>();
    builder.Services.AddSingleton<OfflineQueue>();
    builder.Services.AddSingleton<ConnectionManager>();
    builder.Services.AddSingleton<CompanyGuard>();
    builder.Services.AddTransient<TallyPusher>();
    builder.Services.AddTransient<SmartPusher>();
    builder.Services.AddSingleton<NetworkMonitor>();
    builder.Services.AddSingleton<AutoUpdater>();
    builder.Services.AddSingleton<ConnectorLogger>();
    builder.Services.AddSingleton<DiagnosticReporter>();
    builder.Services.AddSingleton<TallyCompanySyncer>();
    builder.Services.AddSingleton<TallyLedgerSyncer>();
    builder.Services.AddSingleton<TallyRegisterPuller>();
    builder.Services.AddSingleton<TallyMasterReader>();
    builder.Services.AddSingleton<DryRunValidator>();
    builder.Services.AddSingleton<ImportReporter>();
    builder.Services.AddSingleton<IdempotencyChecker>();
    builder.Services.AddSingleton<SessionManager>();
    builder.Services.AddSingleton<AutoRecoveryService>();
    builder.Services.AddSingleton<SyncWatchdog>();
    builder.Services.AddSingleton<RecentPushStore>();
    builder.Services.AddSingleton<UnlimitedBatchPusher>();
    builder.Services.AddTransient<SetupWizard>();
    builder.Services.AddSingleton<XmlPayloadBuilder>();
    builder.Services.AddHttpClient("InvoSync", c =>
    {
        var cfg = builder.Configuration.GetSection("InvoSync");
        c.BaseAddress = new Uri(cfg["ApiBaseUrl"] ?? "https://invosync-backend-yjfa.onrender.com");
        c.DefaultRequestHeaders.Add("X-API-Key", cfg["ApiKey"] ?? "");
    });
    builder.Services.AddHttpClient("Tally", c =>
    {
        var cfg = builder.Configuration.GetSection("Tally");
        var host = cfg["Host"] ?? "localhost";
        var port = cfg.GetValue<int>("Port", 9000);
        c.BaseAddress = new Uri($"http://{host}:{port}");
        c.Timeout = TimeSpan.FromSeconds(cfg.GetValue<int>("TimeoutSeconds", 60));
    });
    builder.Services.AddSingleton<MainForm>(sp =>
    {
        return new MainForm(
            sp.GetRequiredService<IHttpClientFactory>(),
            sp.GetRequiredService<TallyPusher>(),
            sp.GetRequiredService<QueueManager>(),
            sp.GetRequiredService<TallyCompanySyncer>(),
            sp.GetRequiredService<AutoUpdater>(),
            sp.GetRequiredService<AutoRecoveryService>(),
            sp.GetRequiredService<SyncWatchdog>(),
            sp.GetRequiredService<RecentPushStore>(),
            sp.GetRequiredService<ConnectorLogger>(),
            sp.GetRequiredService<DiagnosticReporter>(),
            sp.GetRequiredService<SessionManager>(),
            sp.GetRequiredService<CompanyGuard>(),
            sp.GetRequiredService<OfflineQueue>(),
            sp.GetRequiredService<ILogger<MainForm>>());
    });
    builder.Services.AddHostedService<PollingService>();

    _host = builder.Build();

    // Capture logger for shutdown handler
    _log = _host.Services.GetRequiredService<ILogger<Program>>();

    // Graceful shutdown: allow services to drain
    using var cts = new CancellationTokenSource();
    Console.CancelKeyPress += (_, e) =>
    {
        e.Cancel = true;
        _log?.LogInformation("Shutdown requested — draining pending operations...");
        cts.Cancel();
    };

    // First-run: show setup wizard if no session exists
    var sessionManager = _host.Services.GetRequiredService<SessionManager>();
    if (!sessionManager.IsLoggedIn)
    {
        var wizard = _host.Services.GetRequiredService<SetupWizard>();
        if (wizard.ShowDialog() != DialogResult.OK)
        {
            _log.LogInformation("Setup cancelled by user");
            return;
        }
    }

    // Show main window (minimized if --minimized flag set)
    bool startMinimized = args.Contains("--minimized");
    var form = _host.Services.GetRequiredService<MainForm>();
    if (startMinimized)
    {
        form.WindowState = FormWindowState.Minimized;
        form.Hide();
    }
    Application.Run(form);
    cts.Cancel();
}
catch (Exception ex)
{
    WriteCrash("STARTUP CRASH", ex);
    MessageBox.Show($"InvoSync Connector failed to start.\nCheck: {crashLog}", "Startup Error",
        MessageBoxButtons.OK, MessageBoxIcon.Error);
    throw;
}

// Program class is generated from top-level statements above.
