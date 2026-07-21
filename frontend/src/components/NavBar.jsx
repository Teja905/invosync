import { Link, useLocation } from "react-router-dom";

export default function NavBar({ tallyStatus }) {
  const location = useLocation();
  const path = location.pathname;

  function isActive(pattern) {
    if (pattern === "/reports") return path.startsWith("/reports");
    return path === pattern;
  }

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
        <Link to="/extract" className="premium-logo">
          <div className="premium-logo-icon">I</div>
          <span>InvoSync</span>
        </Link>
        <div className="premium-tabs">
          <Link to="/extract" className={`premium-tab ${isActive("/extract") ? "active" : ""}`}>
            Extract
          </Link>
          <Link to="/dashboard" className={`premium-tab ${isActive("/dashboard") ? "active" : ""}`}>
            Dashboard
          </Link>
          <Link to="/clients" className={`premium-tab ${isActive("/clients") ? "active" : ""}`}>
            Clients
          </Link>
          <div className="relative group">
            <button className={`premium-tab ${isActive("/reports") ? "active" : ""}`}>
              Reports
              <svg className="inline-block ml-1 w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
              </svg>
            </button>
            <div className="absolute left-0 top-full mt-1 bg-gray-800 border border-gray-700 rounded-lg shadow-xl opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-all z-50 min-w-[180px]">
              <Link to="/reports/trial-balance" className="block px-4 py-2 text-sm text-gray-300 hover:bg-gray-700 hover:text-white rounded-t-lg">
                Trial Balance
              </Link>
              <Link to="/reports/pnl" className="block px-4 py-2 text-sm text-gray-300 hover:bg-gray-700 hover:text-white">
                Profit & Loss
              </Link>
              <Link to="/reports/balance-sheet" className="block px-4 py-2 text-sm text-gray-300 hover:bg-gray-700 hover:text-white rounded-b-lg">
                Balance Sheet
              </Link>
            </div>
          </div>
          <Link to="/billing" className={`premium-tab ${isActive("/billing") ? "active" : ""}`}>
            Billing
          </Link>
          <Link to="/settings" className={`premium-tab ${isActive("/settings") ? "active" : ""}`}>
            Settings
          </Link>
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
