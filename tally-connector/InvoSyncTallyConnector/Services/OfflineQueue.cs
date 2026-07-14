using Microsoft.Data.Sqlite;

namespace InvoSync.TallyConnector.Services;

public class PendingInvoice
{
    public string Id { get; set; } = "";
    public string InvoiceId { get; set; } = "";
    public string XmlContent { get; set; } = "";
    public int AttemptCount { get; set; }
    public string CreatedAt { get; set; } = "";
    public string? LastAttempted { get; set; }
    public string Status { get; set; } = "pending";
}

public class OfflineQueue
{
    private readonly string _dbPath;
    private readonly ILogger<OfflineQueue> _log;

    public OfflineQueue(ILogger<OfflineQueue> log)
    {
        _log = log;
        _dbPath = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "offline_queue.db");
        InitializeDatabase();
    }

    private void InitializeDatabase()
    {
        try
        {
            using var conn = NewConnection();
            using var cmd = conn.CreateCommand();
            cmd.CommandText = @"
                CREATE TABLE IF NOT EXISTS pending_invoices (
                    id TEXT PRIMARY KEY,
                    invoice_id TEXT NOT NULL,
                    xml_content TEXT NOT NULL,
                    attempt_count INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL,
                    last_attempted TEXT,
                    status TEXT DEFAULT 'pending'
                )";
            cmd.ExecuteNonQuery();
        }
        catch (Exception ex)
        {
            _log.LogError(ex, "Failed to initialize offline queue database");
        }
    }

    private SqliteConnection NewConnection()
    {
        var conn = new SqliteConnection($"Data Source={_dbPath}");
        conn.Open();
        using var wal = conn.CreateCommand();
        wal.CommandText = "PRAGMA journal_mode=WAL;";
        wal.ExecuteNonQuery();
        using var sync = conn.CreateCommand();
        sync.CommandText = "PRAGMA synchronous=NORMAL;";
        sync.ExecuteNonQuery();
        return conn;
    }

    public bool IsQueueHealthy()
    {
        try
        {
            using var conn = NewConnection();
            using var cmd = conn.CreateCommand();
            cmd.CommandText = "PRAGMA integrity_check;";
            var result = cmd.ExecuteScalar()?.ToString();
            return result == "ok";
        }
        catch
        {
            BackupCorruptedQueue();
            RecreateQueue();
            return false;
        }
    }

    private void BackupCorruptedQueue()
    {
        try
        {
            var backup = _dbPath + $".corrupt.{DateTime.Now:yyyyMMddHHmmss}";
            if (File.Exists(_dbPath))
                File.Move(_dbPath, backup);
            _log.LogWarning("Queue corrupted — backed up to {Backup}", backup);
        }
        catch (Exception ex)
        {
            _log.LogError(ex, "Failed to backup corrupted queue");
        }
    }

    private void RecreateQueue()
    {
        try
        {
            if (File.Exists(_dbPath))
            {
                try { File.Delete(_dbPath); }
                catch { }
            }
            InitializeDatabase();
            _log.LogInformation("Queue recreated");
        }
        catch (Exception ex)
        {
            _log.LogError(ex, "Failed to recreate queue");
        }
    }

    public void Enqueue(string invoiceId, string xml)
    {
        try
        {
            using var conn = NewConnection();
            using var cmd = conn.CreateCommand();
            cmd.CommandText = @"
                INSERT OR REPLACE INTO pending_invoices
                (id, invoice_id, xml_content, created_at, status)
                VALUES (@id, @invoiceId, @xml, @now, 'pending')";
            cmd.Parameters.AddWithValue("@id", Guid.NewGuid().ToString());
            cmd.Parameters.AddWithValue("@invoiceId", invoiceId);
            cmd.Parameters.AddWithValue("@xml", xml);
            cmd.Parameters.AddWithValue("@now", DateTime.UtcNow.ToString("O"));
            cmd.ExecuteNonQuery();
            _log.LogInformation("Queued invoice #{Id} offline", invoiceId);
        }
        catch (Exception ex)
        {
            _log.LogError(ex, "Failed to enqueue invoice #{Id} offline", invoiceId);
        }
    }

    public List<PendingInvoice> GetPending(int limit = 10)
    {
        try
        {
            using var conn = NewConnection();
            using var cmd = conn.CreateCommand();
            cmd.CommandText = @"
                SELECT * FROM pending_invoices
                WHERE status = 'pending'
                AND attempt_count < 5
                ORDER BY created_at ASC
                LIMIT @limit";
            cmd.Parameters.AddWithValue("@limit", limit);
            var results = new List<PendingInvoice>();
            using var reader = cmd.ExecuteReader();
            while (reader.Read())
            {
                results.Add(new PendingInvoice
                {
                    Id = reader.GetString(0),
                    InvoiceId = reader.GetString(1),
                    XmlContent = reader.GetString(2),
                    AttemptCount = reader.GetInt32(3),
                    CreatedAt = reader.GetString(4),
                    LastAttempted = reader.IsDBNull(5) ? null : reader.GetString(5),
                    Status = reader.GetString(6),
                });
            }
            return results;
        }
        catch (Exception ex)
        {
            _log.LogError(ex, "Failed to fetch pending offline queue");
            return new List<PendingInvoice>();
        }
    }

    public void MarkSuccess(string id)
    {
        try
        {
            using var conn = NewConnection();
            using var cmd = conn.CreateCommand();
            cmd.CommandText = "UPDATE pending_invoices SET status = 'completed' WHERE id = @id";
            cmd.Parameters.AddWithValue("@id", id);
            cmd.ExecuteNonQuery();
        }
        catch (Exception ex)
        {
            _log.LogError(ex, "Failed to mark invoice {Id} as completed", id);
        }
    }

    public void MarkFailed(string id)
    {
        try
        {
            using var conn = NewConnection();
            using var cmd = conn.CreateCommand();
            cmd.CommandText = @"
                UPDATE pending_invoices
                SET attempt_count = attempt_count + 1,
                    last_attempted = @now,
                    status = CASE WHEN attempt_count >= 4 THEN 'dead_letter' ELSE 'pending' END
                WHERE id = @id";
            cmd.Parameters.AddWithValue("@id", id);
            cmd.Parameters.AddWithValue("@now", DateTime.UtcNow.ToString("O"));
            cmd.ExecuteNonQuery();
        }
        catch (Exception ex)
        {
            _log.LogError(ex, "Failed to mark invoice {Id} as failed", id);
        }
    }

    public int GetPendingCount()
    {
        try
        {
            using var conn = NewConnection();
            using var cmd = conn.CreateCommand();
            cmd.CommandText = "SELECT COUNT(*) FROM pending_invoices WHERE status = 'pending'";
            return Convert.ToInt32(cmd.ExecuteScalar());
        }
        catch
        {
            return 0;
        }
    }

    public int GetDeadLetterCount()
    {
        try
        {
            using var conn = NewConnection();
            using var cmd = conn.CreateCommand();
            cmd.CommandText = "SELECT COUNT(*) FROM pending_invoices WHERE status = 'dead_letter'";
            return Convert.ToInt32(cmd.ExecuteScalar());
        }
        catch
        {
            return 0;
        }
    }

    public void ProcessPending(Func<PendingInvoice, Task<bool>> processor)
    {
        var pending = GetPending(10);
        foreach (var item in pending)
        {
            try
            {
                var ok = processor(item).GetAwaiter().GetResult();
                if (ok) MarkSuccess(item.Id);
                else MarkFailed(item.Id);
            }
            catch
            {
                MarkFailed(item.Id);
            }
        }
    }
}
