using System.Drawing.Imaging;

namespace InvoSync.TallyConnector.Services;

public enum ConnectorState
{
    AllConnected,
    TallyClosed,
    ServerDisconnected,
    Syncing,
}

public static class TrayIconProvider
{
    private static Icon? _greenIcon;
    private static Icon? _yellowIcon;
    private static Icon? _redIcon;
    private static Icon? _syncIcon;

    public static Icon GetIcon(ConnectorState state)
    {
        return state switch
        {
            ConnectorState.AllConnected => _greenIcon ??= MakeCircleIcon(Color.LimeGreen),
            ConnectorState.TallyClosed => _yellowIcon ??= MakeCircleIcon(Color.Orange),
            ConnectorState.ServerDisconnected => _redIcon ??= MakeCircleIcon(Color.Red),
            ConnectorState.Syncing => _syncIcon ??= MakeCircleIcon(Color.DodgerBlue),
            _ => _redIcon ??= MakeCircleIcon(Color.Red),
        };
    }

    public static string GetText(ConnectorState state, int pending = 0)
    {
        return state switch
        {
            ConnectorState.AllConnected => "InvoSync — Connected ✓",
            ConnectorState.TallyClosed => "InvoSync — Open TallyPrime",
            ConnectorState.ServerDisconnected => "InvoSync — Reconnecting...",
            ConnectorState.Syncing => $"InvoSync — Syncing {pending} invoices",
            _ => "InvoSync",
        };
    }

    private static Icon MakeCircleIcon(Color color)
    {
        using var bmp = new Bitmap(16, 16);
        using var g = Graphics.FromImage(bmp);
        g.SmoothingMode = System.Drawing.Drawing2D.SmoothingMode.AntiAlias;
        using var brush = new SolidBrush(color);
        g.FillEllipse(brush, 2, 2, 12, 12);
        using var pen = new Pen(Color.FromArgb(200, color.R / 2, color.G / 2, color.B / 2), 1);
        g.DrawEllipse(pen, 2, 2, 12, 12);
        return Icon.FromHandle(bmp.GetHicon());
    }
}
