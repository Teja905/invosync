using System.Diagnostics;
using System.Text;
using System.Text.Json;
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
    // Give user time to read, then restart
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

// === Main startup — wrapped in global try/catch ===
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
builder.Services.AddHostedService<PollingService>();

var host = builder.Build();
var cts = new CancellationTokenSource();
_ = host.RunAsync(cts.Token);

var logFactory = host.Services.GetRequiredService<ILoggerFactory>();
var logger = logFactory.CreateLogger("Program");

// System tray icon — visible desktop presence
using var icon = new NotifyIcon
{
    Icon = SystemIcons.Application,
    Text = "InvoSync Tally Connector",
    Visible = true,
    ContextMenuStrip = new ContextMenuStrip()
};

// Status indicator (updated periodically)
var statusItem = new ToolStripMenuItem("Starting...") { Enabled = false };
icon.ContextMenuStrip.Items.Add(statusItem);
icon.ContextMenuStrip.Items.Add(new ToolStripSeparator());

icon.ContextMenuStrip.Items.Add("Ping Tally", null, (s, e) =>
{
    var http = host.Services.GetRequiredService<IHttpClientFactory>().CreateClient("Tally");
    try
    {
        var ping = http.PostAsync("", new StringContent(
            "<ENVELOPE><HEADER><VERSION>1</VERSION><TALLYREQUEST>Export</TALLYREQUEST><TYPE>Company</TYPE><ID>List of Companies</ID></HEADER><BODY><DESC></DESC></BODY></ENVELOPE>",
            Encoding.UTF8, "text/xml"), cts.Token);
        bool ok = ping.Wait(5000) && ping.Result.IsSuccessStatusCode;
        icon.ShowBalloonTip(3000, "InvoSync Connector", ok ? "Tally Prime: Connected" : "Tally Prime: Offline", ToolTipIcon.Info);
    }
    catch { icon.ShowBalloonTip(3000, "InvoSync Connector", "Tally Prime: Unreachable", ToolTipIcon.Warning); }
});

// Show dead-letter count
icon.ContextMenuStrip.Items.Add("Show Failed Imports", null, (s, e) =>
{
    var queue = host.Services.GetRequiredService<QueueManager>();
    int dead = queue.DeadLetterCount;
    if (dead == 0)
        icon.ShowBalloonTip(3000, "InvoSync Connector", "No failed imports", ToolTipIcon.Info);
    else
        icon.ShowBalloonTip(5000, "InvoSync Connector", $"{dead} invoice(s) in dead-letter queue — check logs", ToolTipIcon.Warning);
});

// Open crash log
icon.ContextMenuStrip.Items.Add("View Crash Log", null, (_, _) =>
{
    try { Process.Start("notepad.exe", crashLog); }
    catch { MessageBox.Show($"Crash log at: {crashLog}"); }
});

icon.ContextMenuStrip.Items.Add(new ToolStripSeparator());
icon.ContextMenuStrip.Items.Add("Exit", null, (s, e) => { cts.Cancel(); Application.Exit(); });

// Update status periodically
_ = Task.Run(async () =>
{
    while (!cts.Token.IsCancellationRequested)
    {
        try
        {
            var tally = host.Services.GetRequiredService<IHttpClientFactory>().CreateClient("Tally");
            var ping = new StringContent(
                "<ENVELOPE><HEADER><VERSION>1</VERSION><TALLYREQUEST>Export</TALLYREQUEST><TYPE>Company</TYPE><ID>List of Companies</ID></HEADER><BODY><DESC></DESC></BODY></ENVELOPE>",
                Encoding.UTF8, "text/xml");
            var resp = await tally.PostAsync("", ping, cts.Token);
            bool connected = resp.IsSuccessStatusCode;
            statusItem.Text = connected ? "Tally: Connected" : "Tally: Offline";

            var queue = host.Services.GetRequiredService<QueueManager>();
            if (queue.DeadLetterCount > 0)
                statusItem.Text += $" | {queue.DeadLetterCount} failed";

            icon.Text = statusItem.Text.Length > 63
                ? statusItem.Text[..63]
                : statusItem.Text;
        }
        catch
        {
            statusItem.Text = "Tally: Unreachable";
        }
        await Task.Delay(30000, cts.Token);
    }
}, cts.Token);

Application.Run();
cts.Cancel();
}
catch (Exception ex)
{
    WriteCrash("STARTUP CRASH", ex);
    MessageBox.Show($"InvoSync Connector failed to start.\nCheck: {crashLog}", "Startup Error",
        MessageBoxButtons.OK, MessageBoxIcon.Error);
    throw;
}
