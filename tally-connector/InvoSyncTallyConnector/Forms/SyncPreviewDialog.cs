using System.Text.Json;
using InvoSync.TallyConnector.Models;

namespace InvoSync.TallyConnector.Forms;

public class SyncPreviewDialog : Form
{
    private readonly List<InvoiceDto> _invoices;
    private readonly IHttpClientFactory _httpFactory;
    private readonly ILogger _log;
    private CheckedListBox _invoiceList = null!;
    private Label _summaryLabel = null!;
    private Button _syncBtn = null!, _cancelBtn = null!;
    private bool _confirmed;

    public bool Confirmed => _confirmed;
    public List<InvoiceDto> SelectedInvoices { get; private set; } = new();

    private static readonly Color BgDark = Color.FromArgb(13, 17, 23);
    private static readonly Color BgCard = Color.FromArgb(22, 27, 34);
    private static readonly Color BorderColor = Color.FromArgb(48, 54, 61);
    private static readonly Color TextPrimary = Color.FromArgb(230, 237, 243);
    private static readonly Color TextSecondary = Color.FromArgb(139, 148, 158);
    private static readonly Color AccentBlue = Color.FromArgb(88, 166, 255);

    public SyncPreviewDialog(List<InvoiceDto> invoices, IHttpClientFactory httpFactory, ILogger log)
    {
        _invoices = invoices;
        _httpFactory = httpFactory;
        _log = log;
        InitializeComponent();
        LoadInvoices();
    }

    private void InitializeComponent()
    {
        Text = "Sync Preview";
        Size = new Size(560, 440);
        StartPosition = FormStartPosition.CenterParent;
        FormBorderStyle = FormBorderStyle.FixedDialog;
        MaximizeBox = false;
        MinimizeBox = false;
        BackColor = BgDark;
        ForeColor = TextPrimary;
        Font = new Font("Segoe UI", 10);

        var root = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            RowCount = 4,
            ColumnCount = 1,
            Padding = new Padding(16),
        };
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));

        // Header
        var header = new Label
        {
            Text = "Pending Invoices",
            Font = new Font("Segoe UI", 13, FontStyle.Bold),
            ForeColor = TextPrimary,
            AutoSize = true,
            Margin = new Padding(0, 0, 0, 8),
        };
        root.Controls.Add(header, 0, 0);

        // Invoice checklist
        _invoiceList = new CheckedListBox
        {
            Dock = DockStyle.Fill,
            BackColor = BgCard,
            ForeColor = TextPrimary,
            BorderStyle = BorderStyle.FixedSingle,
            CheckOnClick = true,
            Font = new Font("Segoe UI", 9),
            IntegralHeight = false,
        };
        root.Controls.Add(_invoiceList, 0, 1);

        // Summary
        _summaryLabel = new Label
        {
            Text = "",
            Font = new Font("Segoe UI", 10, FontStyle.Bold),
            ForeColor = AccentBlue,
            AutoSize = true,
            Margin = new Padding(0, 8, 0, 8),
        };
        root.Controls.Add(_summaryLabel, 0, 2);

        // Buttons
        var btnPanel = new FlowLayoutPanel
        {
            Dock = DockStyle.Fill,
            FlowDirection = FlowDirection.RightToLeft,
            BackColor = Color.Transparent,
        };

        _syncBtn = new Button
        {
            Text = "Sync Selected",
            BackColor = Color.FromArgb(0, 120, 80),
            ForeColor = TextPrimary,
            FlatStyle = FlatStyle.Flat,
            AutoSize = true,
            Height = 34,
            Padding = new Padding(16, 0, 16, 0),
            Cursor = Cursors.Hand,
            Font = new Font("Segoe UI", 10, FontStyle.Bold),
        };
        _syncBtn.FlatAppearance.BorderSize = 0;
        _syncBtn.Click += (_, _) => Confirm();

        _cancelBtn = new Button
        {
            Text = "Cancel",
            BackColor = Color.FromArgb(33, 38, 45),
            ForeColor = TextPrimary,
            FlatStyle = FlatStyle.Flat,
            AutoSize = true,
            Height = 34,
            Padding = new Padding(16, 0, 16, 0),
            Cursor = Cursors.Hand,
            Margin = new Padding(0, 0, 8, 0),
        };
        _cancelBtn.FlatAppearance.BorderSize = 0;
        _cancelBtn.Click += (_, _) => { _confirmed = false; Close(); };

        btnPanel.Controls.AddRange([_syncBtn, _cancelBtn]);
        root.Controls.Add(btnPanel, 0, 3);

        Controls.Add(root);
    }

    private void LoadInvoices()
    {
        _invoiceList.Items.Clear();
        foreach (var inv in _invoices)
        {
            var text = $"#{inv.DisplayId,-6} {inv.InvoiceNumber,-14} {inv.VendorName,-24} {inv.TotalAmount,10:N2}  ({inv.VoucherType ?? "Purchase"})";
            _invoiceList.Items.Add(text, true);
        }
        UpdateSummary();
        _invoiceList.ItemCheck += (_, _) => UpdateSummary();
    }

    private void UpdateSummary()
    {
        var selected = _invoiceList.CheckedIndices.Count;
        var total = 0m;
        for (int i = 0; i < _invoiceList.Items.Count; i++)
        {
            if (_invoiceList.GetItemChecked(i) && i < _invoices.Count)
                total += _invoices[i].TotalAmount;
        }
        _summaryLabel.Text = $"{selected} of {_invoices.Count} selected  |  Total: \u20B9{total:N2}";
    }

    private void Confirm()
    {
        SelectedInvoices = new List<InvoiceDto>();
        for (int i = 0; i < _invoiceList.Items.Count; i++)
        {
            if (_invoiceList.GetItemChecked(i) && i < _invoices.Count)
                SelectedInvoices.Add(_invoices[i]);
        }

        if (SelectedInvoices.Count == 0)
        {
            MessageBox.Show("Select at least one invoice to sync.", "Nothing Selected",
                MessageBoxButtons.OK, MessageBoxIcon.Warning);
            return;
        }

        _confirmed = true;
        Close();
    }
}
