export default function NavBar({ active, onChange, tallyStatus }) {
  const tabs = [
    { key: "extract", label: "Extract" },
    { key: "clients", label: "Clients" },
    { key: "dashboard", label: "Dashboard" },
    { key: "learning", label: "Learning" },
    { key: "settings", label: "Settings" },
  ];

  function dotColor() {
    if (!tallyStatus) return "grey";
    if (tallyStatus.connector_online && tallyStatus.tally_reachable) return "green";
    if (tallyStatus.connector_online && !tallyStatus.tally_reachable) return "yellow";
    return "red";
  }

  function statusText() {
    if (!tallyStatus) return "Connecting...";
    if (tallyStatus.connector_online && tallyStatus.tally_reachable)
      return `Tally: ${tallyStatus.company || "Connected"}`;
    if (tallyStatus.connector_online && !tallyStatus.tally_reachable)
      return "Tally not detected — open Tally Prime (F1 → Settings → Connectivity → Port 9000)";
    return "Connector offline — run InvoSync.exe on this PC";
  }

  return (
    <div className="premium-header">
      <div className="premium-header-inner">
        <div className="premium-logo">
          <div className="premium-logo-icon">I</div>
          <span>InvoSync</span>
        </div>
        <div className="premium-tabs">
          {tabs.map((t) => (
            <button key={t.key} onClick={() => onChange(t.key)}
              className={`premium-tab ${active === t.key ? "active" : ""}`}>
              {t.label}
            </button>
          ))}
        </div>
        <div className="premium-status" title={statusText()}>
          <span className={`premium-status-dot ${dotColor()}`} />
          <span className="premium-status-label">{statusText()}</span>
          <span style={{color:"var(--text-tertiary)", fontSize:"11px", marginLeft:"4px"}}>v3.2</span>
        </div>
      </div>
    </div>
  );
}
