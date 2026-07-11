using InvoSync.TallyConnector.Services;
using InvoSync.TallyConnector.Models;

var builder = Host.CreateApplicationBuilder(args);
builder.Services.AddSingleton<QueueManager>();
builder.Services.AddTransient<TallyPusher>();
builder.Services.AddSingleton<TallyCompanySyncer>();
builder.Services.AddSingleton<TallyLedgerSyncer>();
builder.Services.AddHttpClient("InvoSync", c =>
{
    var cfg = builder.Configuration.GetSection("InvoSync");
    c.BaseAddress = new Uri(cfg["ApiBaseUrl"] ?? "http://localhost:8000");
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
await host.RunAsync();
