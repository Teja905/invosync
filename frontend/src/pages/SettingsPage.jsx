import { useState, useEffect } from "react";
import { useAuth } from "../auth";
import BACKEND, { STATE_CODES } from "../api/client";
import CorrectionMemoryUI from "../components/CorrectionMemoryUI";
import TallyConnectorPanel from "../components/TallyConnectorPanel";

const LEDGER_ROLES = [
  { key: "purchase_ledger", label: "Purchase Ledger", role: "PURCHASE" },
  { key: "sales_ledger", label: "Sales Ledger", role: "SALES" },
  { key: "bank_ledger", label: "Bank Ledger", role: "BANK" },
  { key: "debtors_ledger", label: "Debtors Ledger", role: "DEBTORS" },
  { key: "creditors_ledger", label: "Creditors Ledger", role: "CREDITORS" },
  { key: "input_gst_ledger", label: "Input GST Ledger", role: "GST_INPUT" },
  { key: "output_gst_ledger", label: "Output GST Ledger", role: "GST_OUTPUT" },
];

function confidenceColor(score) {
  if (score >= 90) return "text-green-400";
  if (score >= 70) return "text-yellow-400";
  return "text-red-400";
}

function confidenceBadge(score) {
  if (score >= 90) return "bg-green-500/20 text-green-400 border-green-500/30";
  if (score >= 70) return "bg-yellow-500/20 text-yellow-400 border-yellow-500/30";
  return "bg-red-500/20 text-red-400 border-red-500/30";
}

export default function SettingsPage() {
  const { user, getAuthHeaders } = useAuth();
  const [companyName, setCompanyName] = useState(user?.company_name || "");
  const [companyGstin, setCompanyGstin] = useState(user?.company_gstin || "");
  const [stateCode, setStateCode] = useState(user?.company_state_code || "");

  const [ledgerValues, setLedgerValues] = useState({
    purchase_ledger: user?.purchase_ledger || "Purchase",
    sales_ledger: user?.sales_ledger || "Sales",
    bank_ledger: user?.bank_ledger || "Bank",
    debtors_ledger: user?.debtors_ledger || "Sundry Debtors",
    creditors_ledger: user?.creditors_ledger || "Sundry Creditors",
    input_gst_ledger: user?.input_gst_ledger || "Input CGST @ 9%",
    output_gst_ledger: user?.output_gst_ledger || "Output CGST @ 9%",
  });

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const [tallyLedgers, setTallyLedgers] = useState([]);
  const [suggestions, setSuggestions] = useState(null);
  const [discovering, setDiscovering] = useState(false);

  function getLedgerNames() {
    return tallyLedgers.map((l) => (typeof l === "string" ? l : l.name));
  }

  function ledgerMismatch(name) {
    if (!name || tallyLedgers.length === 0) return false;
    const names = getLedgerNames();
    return !names.some((l) => l.toLowerCase().trim() === name.toLowerCase().trim());
  }

  function getLedgerParent(name) {
    if (!tallyLedgers.length || !name) return "";
    for (const l of tallyLedgers) {
      const lName = typeof l === "string" ? l : l.name;
      if (lName.toLowerCase().trim() === name.toLowerCase().trim()) {
        return typeof l === "string" ? "" : l.parent || "";
      }
    }
    return "";
  }

  function getSuggestion(role) {
    if (!suggestions || !suggestions[role] || !suggestions[role].length) return null;
    return suggestions[role][0];
  }

  async function loadLedgers() {
    try {
      const res = await fetch(`${BACKEND}/api/v3/sync/ledgers`, { headers: getAuthHeaders() });
      const d = await res.json();
      setTallyLedgers(d.ledgers || []);
    } catch {}
  }

  useEffect(() => {
    loadLedgers();
  }, []);

  async function handleDiscover() {
    setDiscovering(true);
    try {
      const res = await fetch(`${BACKEND}/api/v3/sync/discover-ledgers`, {
        method: "POST",
        headers: getAuthHeaders(),
      });
      const d = await res.json();
      setSuggestions(d.suggestions || {});
      // Auto-populate fields from top suggestion per role
      const updates = {};
      for (const roleDef of LEDGER_ROLES) {
        const top = getSuggestion(roleDef.role);
        if (top && top.confidence >= 60) {
          updates[roleDef.key] = top.ledger_name;
        }
      }
      if (Object.keys(updates).length > 0) {
        setLedgerValues((prev) => ({ ...prev, ...updates }));
      }
    } catch (err) {
      setError("Discovery failed: " + err.message);
    }
    setDiscovering(false);
  }

  async function handleRefreshCache() {
    await loadLedgers();
  }

  async function handleSave(e) {
    e.preventDefault();
    setError(""); setSaved(false);
    if (!companyName || !companyGstin || !stateCode) {
      setError("Company Name, GSTIN, and State Code are required");
      return;
    }
    setBusy(true);
    try {
      const res = await fetch(`${BACKEND}/api/v3/config`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...getAuthHeaders() },
        body: JSON.stringify({
          company_name: companyName,
          company_gstin: companyGstin.toUpperCase(),
          company_state_code: stateCode,
          ...ledgerValues,
        }),
      });
      if (!res.ok) { let msg = "Failed to save"; try { const e = await res.json(); msg = e.detail || msg; } catch {} throw new Error(msg); }
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } catch (err) { setError(err.message); }
    setBusy(false);
  }

  function renderLedgerDropdown(roleDef) {
    const key = roleDef.key;
    const value = ledgerValues[key];
    const names = getLedgerNames();
    const suggestion = suggestions ? getSuggestion(roleDef.role) : null;
    const mismatch = ledgerMismatch(value);

    return (
      <div key={key}>
        <label className="text-xs text-gray-500 mb-1 block">{roleDef.label}</label>
        <div className="relative">
          {tallyLedgers.length > 0 ? (
            <select
              className="input w-full text-sm pr-7"
              value={value}
              onChange={(e) => setLedgerValues((prev) => ({ ...prev, [key]: e.target.value }))}
            >
              <option value="">-- Select --</option>
              {names.map((l) => <option key={l} value={l}>{l}</option>)}
            </select>
          ) : (
            <input
              className="input w-full text-sm"
              value={value}
              onChange={(e) => setLedgerValues((prev) => ({ ...prev, [key]: e.target.value }))}
              placeholder={`e.g. ${roleDef.role === "PURCHASE" ? "Purchase Accounts" : ""}`}
            />
          )}
          {mismatch && <span className="absolute right-2 top-1/2 -translate-y-1/2 text-yellow-400 text-xs font-bold">{'\u26A0'}</span>}
        </div>
        {/* Parent group sub-label */}
        {value && tallyLedgers.length > 0 && (
          <p className="text-[10px] text-gray-600 mt-0.5">Parent: {getLedgerParent(value) || "—"}</p>
        )}
        {/* Suggested auto-detect badge */}
        {suggestion && suggestion.confidence >= 60 && suggestion.ledger_name !== value && (
          <button
            type="button"
            className={`mt-1 text-[10px] px-1.5 py-0.5 rounded border ${confidenceBadge(suggestion.confidence)} cursor-pointer hover:opacity-80`}
            onClick={() => setLedgerValues((prev) => ({ ...prev, [key]: suggestion.ledger_name }))}
          >
            {'\u26A1'} Suggestion: {suggestion.ledger_name} ({suggestion.confidence}%)
          </button>
        )}
        {suggestion && suggestion.confidence >= 60 && suggestion.ledger_name === value && (
          <span className={`mt-0.5 text-[10px] ${confidenceColor(suggestion.confidence)}`}>
            {suggestion.match_reason}
          </span>
        )}
      </div>
    );
  }

  return (
    <div className="space-y-4 animate-fadeInUp">
      <h2 className="text-lg font-bold premium-gradient-text">Company Settings</h2>
      <p className="text-sm text-gray-400">These settings are used for all invoices and XML generation.</p>
      <form onSubmit={handleSave} className="premium-card-flat p-6 space-y-4 max-w-2xl">
        <div>
          <label className="text-xs text-gray-500 mb-1 block">Company Name (as in Tally) *</label>
          <input className="input w-full" value={companyName} onChange={(e) => setCompanyName(e.target.value)} placeholder="e.g. My Firm & Co." />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="text-xs text-gray-500 mb-1 block">Company GSTIN *</label>
            <input className="input w-full font-mono text-sm" value={companyGstin} onChange={(e) => setCompanyGstin(e.target.value.toUpperCase())} placeholder="e.g. 27AABCU1234F1ZP" maxLength={15} />
          </div>
          <div>
            <label className="text-xs text-gray-500 mb-1 block">State Code *</label>
            <select className="input w-full" value={stateCode} onChange={(e) => setStateCode(e.target.value)}>
              <option value="">-- Select --</option>
              {STATE_CODES.map((s) => (
                <option key={s} value={s.slice(0,2)}>{s}</option>
              ))}
            </select>
          </div>
        </div>
        <div className="pt-2 border-t border-white/5">
          <div className="flex items-center justify-between mb-3">
            <p className="text-xs text-gray-500">Default Tally Ledgers for XML export
              {tallyLedgers.length > 0 && <span className="text-green-400/70 ml-2">({tallyLedgers.length} ledgers synced)</span>}
            </p>
            <div className="flex gap-2">
              <button
                type="button"
                disabled={discovering}
                className="text-[11px] px-2 py-1 rounded bg-indigo-500/20 text-indigo-300 border border-indigo-500/30 hover:bg-indigo-500/30 cursor-pointer disabled:opacity-50"
                onClick={handleDiscover}
              >
                {discovering ? "Scanning..." : <>{"\u2699"} Auto-Detect</>}
              </button>
              <button
                type="button"
                className="text-[11px] px-2 py-1 rounded bg-white/5 text-gray-400 border border-white/10 hover:bg-white/10 cursor-pointer"
                onClick={handleRefreshCache}
              >
                {'\u21BB'} Reload
              </button>
            </div>
          </div>
          {tallyLedgers.length === 0 && (
            <div className="bg-amber-500/10 border border-amber-500/20 rounded-lg p-3 mb-3">
              <p className="text-xs text-amber-300">{'\u26A0'} No ledgers synced yet. Download and run the Tally Connector (below) to pull your live Chart of Accounts.</p>
            </div>
          )}
          <div className="grid grid-cols-2 lg:grid-cols-3 gap-3">
            {LEDGER_ROLES.map(renderLedgerDropdown)}
          </div>
        </div>
        {error && <p className="text-red-400 text-sm">{error}</p>}
        {saved && <p className="text-green-400 text-sm">Settings saved successfully.</p>}
        <button type="submit" disabled={busy} className="premium-btn-primary py-3 px-6">
          {busy ? "Saving..." : "Save Settings"}
        </button>
      </form>

      <div className="premium-card-flat p-6 max-w-2xl">
        <h3 className="text-sm font-semibold text-gray-200 mb-3">Ledger Corrections</h3>
        <p className="text-xs text-gray-500 mb-3">When a description maps to the wrong ledger, add a correction here. It will be remembered for future invoices.</p>
        <CorrectionMemoryUI />
      </div>

      <TallyConnectorPanel />
    </div>
  );
}
