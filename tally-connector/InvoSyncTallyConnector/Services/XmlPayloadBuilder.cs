using System.Text;

namespace InvoSync.TallyConnector.Services;

/// <summary>
/// Builds Tally XML for creating groups, ledgers, and masters.
/// Every method returns clean Tally-compatible XML ready for TallyPusher.
/// Supports three scenarios:
///   1. Group + Ledger in one XML (new group that doesn't exist)
///   2. Ledger only under existing group
///   3. Group only (for chart-of-accounts setup)
/// </summary>
public class XmlPayloadBuilder
{
    private readonly ILogger<XmlPayloadBuilder> _log;

    public XmlPayloadBuilder(ILogger<XmlPayloadBuilder> log)
    {
        _log = log;
    }

    /// <summary>
    /// Builds XML to create a GROUP and LEDGER in a single Tally import envelope.
    /// The group is created first, then the ledger under it.
    /// </summary>
    public string BuildGroupAndLedgerXml(
        string companyName,
        string groupName,
        string parentGroup,
        string ledgerName,
        string? ledgerParent = null)
    {
        var xml = $@"<ENVELOPE>
<HEADER>
<VERSION>1</VERSION>
<TALLYREQUEST>Import</TALLYREQUEST>
<TYPE>Object</TYPE>
</HEADER>
<BODY>
<DESC>
<STATICVARIABLES>
<SVCURRENTCOMPANY>{EscapeXml(companyName)}</SVCURRENTCOMPANY>
</STATICVARIABLES>
</DESC>
<OBJECT>
<GROUP ACTION=""Create"">
<NAME>{EscapeXml(groupName)}</NAME>
<PARENT>{EscapeXml(parentGroup)}</PARENT>
</GROUP>
<LEDGER ACTION=""Create"">
<NAME>{EscapeXml(ledgerName)}</NAME>
<PARENT>{EscapeXml(ledgerParent ?? groupName)}</PARENT>
</LEDGER>
</OBJECT>
</BODY>
</ENVELOPE>";

        _log.LogDebug("Built Group+Ledger XML for {Ledger} under {Group}", ledgerName, groupName);
        return xml;
    }

    /// <summary>
    /// Builds XML to create only a LEDGER under an existing group.
    /// </summary>
    public string BuildLedgerOnlyXml(
        string companyName,
        string ledgerName,
        string parentGroup)
    {
        var xml = $@"<ENVELOPE>
<HEADER>
<VERSION>1</VERSION>
<TALLYREQUEST>Import</TALLYREQUEST>
<TYPE>Object</TYPE>
</HEADER>
<BODY>
<DESC>
<STATICVARIABLES>
<SVCURRENTCOMPANY>{EscapeXml(companyName)}</SVCURRENTCOMPANY>
</STATICVARIABLES>
</DESC>
<OBJECT>
<LEDGER ACTION=""Create"">
<NAME>{EscapeXml(ledgerName)}</NAME>
<PARENT>{EscapeXml(parentGroup)}</PARENT>
</LEDGER>
</OBJECT>
</BODY>
</ENVELOPE>";

        _log.LogDebug("Built Ledger-only XML for {Ledger} under {Parent}", ledgerName, parentGroup);
        return xml;
    }

    /// <summary>
    /// Builds XML to create only a GROUP under a parent group.
    /// </summary>
    public string BuildGroupOnlyXml(
        string companyName,
        string groupName,
        string parentGroup)
    {
        var xml = $@"<ENVELOPE>
<HEADER>
<VERSION>1</VERSION>
<TALLYREQUEST>Import</TALLYREQUEST>
<TYPE>Object</TYPE>
</HEADER>
<BODY>
<DESC>
<STATICVARIABLES>
<SVCURRENTCOMPANY>{EscapeXml(companyName)}</SVCURRENTCOMPANY>
</STATICVARIABLES>
</DESC>
<OBJECT>
<GROUP ACTION=""Create"">
<NAME>{EscapeXml(groupName)}</NAME>
<PARENT>{EscapeXml(parentGroup)}</PARENT>
</GROUP>
</OBJECT>
</BODY>
</ENVELOPE>";

        _log.LogDebug("Built Group-only XML for {Group} under {Parent}", groupName, parentGroup);
        return xml;
    }

    /// <summary>
    /// Builds a multi-object envelope that creates multiple groups and ledgers in one shot.
    /// Accepts a list of (objType, name, parent) where objType is "GROUP" or "LEDGER".
    /// Orders groups before ledgers automatically.
    /// </summary>
    public string BuildMultiMasterXml(
        string companyName,
        List<(string objType, string name, string parent)> masters)
    {
        var sb = new StringBuilder();
        sb.Append($@"<ENVELOPE>
<HEADER>
<VERSION>1</VERSION>
<TALLYREQUEST>Import</TALLYREQUEST>
<TYPE>Object</TYPE>
</HEADER>
<BODY>
<DESC>
<STATICVARIABLES>
<SVCURRENTCOMPANY>{EscapeXml(companyName)}</SVCURRENTCOMPANY>
</STATICVARIABLES>
</DESC>
");

        // Groups first, then ledgers (Tally requires parent objects to exist first)
        foreach (var (objType, name, parent) in masters.OrderBy(m => m.objType == "GROUP" ? 0 : 1))
        {
            sb.Append($@"<OBJECT>
<{objType} ACTION=""Create"">
<NAME>{EscapeXml(name)}</NAME>
<PARENT>{EscapeXml(parent)}</PARENT>
</{objType}>
</OBJECT>
");
        }

        sb.Append(@"</BODY>
</ENVELOPE>");

        _log.LogDebug("Built multi-master XML with {Count} objects", masters.Count);
        return sb.ToString();
    }

    private static string EscapeXml(string s) =>
        s.Replace("&", "&amp;").Replace("<", "&lt;").Replace(">", "&gt;").Replace("\"", "&quot;").Replace("'", "&apos;");
}
