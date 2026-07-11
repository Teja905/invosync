using System.Text.Json;
using InvoSync.TallyConnector.Services;

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

// System tray icon — visible desktop presence
using var icon = new NotifyIcon
{
    Icon = SystemIcons.Application,
    Text = "InvoSync Tally Connector",
    Visible = true,
    ContextMenuStrip = new ContextMenuStrip()
};
icon.ContextMenuStrip.Items.Add("Status: Running", null, (s, e) =>
{
    var http = host.Services.GetRequiredService<IHttpClientFactory>().CreateClient("Tally");
    try
    {
        var ping = http.PostAsync("", new StringContent(
            "<ENVELOPE><HEADER><VERSION>1</VERSION><TALLYREQUEST>Export</TALLYREQUEST><TYPE>Company</TYPE><ID>List of Companies</ID></HEADER><BODY><DESC></DESC></BODY></ENVELOPE>",
            System.Text.Encoding.UTF8, "text/xml"),
            cts.Token);
        bool ok = ping.Wait(5000) && ping.Result.IsSuccessStatusCode;
        icon.ShowBalloonTip(3000, "InvoSync Connector", ok ? "Tally Prime: Connected" : "Tally Prime: Offline", ToolTipIcon.Info);
    }
    catch { icon.ShowBalloonTip(3000, "InvoSync Connector", "Tally Prime: Unreachable", ToolTipIcon.Warning); }
});
icon.ContextMenuStrip.Items.Add(new ToolStripSeparator());
icon.ContextMenuStrip.Items.Add("Exit", null, (s, e) => { cts.Cancel(); Application.Exit(); });

Application.Run();
cts.Cancel();
