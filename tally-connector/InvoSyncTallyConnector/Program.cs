using System.Diagnostics;
using InvoSync.TallyConnector;
using InvoSync.TallyConnector.Services;

// === PRODUCTION SHIELD: never silently crash ===
var crashLog = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "connector-crash.log");
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
    builder.Services.AddTransient<TallyPusher>();
    builder.Services.AddSingleton<TallyCompanySyncer>();
    builder.Services.AddSingleton<TallyLedgerSyncer>();
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
    builder.Services.AddSingleton<MainForm>();
    builder.Services.AddHostedService<PollingService>();

    var host = builder.Build();

    // Start background services
    var cts = new CancellationTokenSource();
    _ = host.RunAsync(cts.Token);

    // Show main window
    var form = host.Services.GetRequiredService<MainForm>();
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
