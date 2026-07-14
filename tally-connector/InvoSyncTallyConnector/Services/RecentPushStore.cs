using System.Collections.Concurrent;
using System.Text.Json;

namespace InvoSync.TallyConnector.Services;

public class RecentPushEntry
{
    public DateTime Timestamp { get; set; }
    public int DisplayId { get; set; }
    public string InvoiceNumber { get; set; } = "";
    public string VendorName { get; set; } = "";
    public decimal Amount { get; set; }
    public bool Success { get; set; }
    public string? Error { get; set; }
}

public class DailyCounters
{
    public DateTime Date { get; set; }
    public int Pushed { get; set; }
    public int Failed { get; set; }
}

public class RecentPushStore
{
    private readonly ConcurrentQueue<RecentPushEntry> _entries = new();
    private const int MaxEntries = 200;
    private readonly string _countersFile;
    private readonly ILogger<RecentPushStore> _log;
    private DailyCounters _today;

    public RecentPushStore(ILogger<RecentPushStore> log)
    {
        _log = log;
        _countersFile = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
            "InvoSync", "daily_counters.json");
        _today = new DailyCounters { Date = DateTime.Today };
        LoadCounters();
    }

    public void Add(RecentPushEntry entry)
    {
        _entries.Enqueue(entry);
        while (_entries.Count > MaxEntries)
            _entries.TryDequeue(out _);

        if (_today.Date != DateTime.Today)
            _today = new DailyCounters { Date = DateTime.Today };
        if (entry.Success) _today.Pushed++;
        else _today.Failed++;
        SaveCounters();
    }

    public IReadOnlyList<RecentPushEntry> GetRecent(int count = 50)
    {
        return _entries.Reverse().Take(count).ToList();
    }

    public int TodayPushCount => _today.Pushed;
    public int TodayFailCount => _today.Failed;

    private void SaveCounters()
    {
        try
        {
            var dir = Path.GetDirectoryName(_countersFile);
            if (dir != null) Directory.CreateDirectory(dir);
            File.WriteAllText(_countersFile, JsonSerializer.Serialize(_today));
        }
        catch { }
    }

    private void LoadCounters()
    {
        try
        {
            if (!File.Exists(_countersFile)) return;
            var loaded = JsonSerializer.Deserialize<DailyCounters>(File.ReadAllText(_countersFile));
            if (loaded?.Date == DateTime.Today)
                _today = loaded;
        }
        catch { }
    }
}
