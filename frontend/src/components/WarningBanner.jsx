import { useState } from "react";
import BACKEND from "../api/client";

export default function WarningBanner({ warning, getAuthHeaders }) {
  const [creating, setCreating] = useState(false);
  const [created, setCreated] = useState(false);
  const [error, setError] = useState(null);

  if (!warning) return null;

  const severity = warning.severity || "medium";
  const bgMap = {
    high: "bg-red-500/10 border-red-500/20",
    medium: "bg-amber-500/10 border-amber-500/20",
    low: "bg-blue-500/10 border-blue-500/20",
  };
  const textMap = {
    high: "text-red-300",
    medium: "text-amber-300",
    low: "text-blue-300",
  };
  const iconMap = {
    high: "\u26A0",
    medium: "\u26A0",
    low: "\u2139",
  };

  function isLedgerWarning() {
    return warning.type === "Ledger" || (warning.message && warning.message.startsWith("Ledger '"));
  }

  function extractLedgerName() {
    if (!warning.message) return "";
    const match = warning.message.match(/Ledger '([^']+)'/);
    return match ? match[1] : "";
  }

  async function handleCreateLedger() {
    setCreating(true);
    setError(null);
    const ledgerName = warning.ledgerName || extractLedgerName();
    if (!ledgerName) {
      setError("No ledger name to create");
      setCreating(false);
      return;
    }
    try {
      const res = await fetch(`${BACKEND}/api/v3/ledgers/create`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...getAuthHeaders() },
        body: JSON.stringify({
          name: ledgerName,
          parent: warning.parent || "Primary",
          company_name: warning.companyName || "",
        }),
      });
      if (!res.ok) throw new Error(await res.text());
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `ledger_${ledgerName.replace(/[^a-zA-Z0-9_-]/g, "_")}.xml`;
      a.click();
      URL.revokeObjectURL(url);
      setCreated(true);
    } catch (e) {
      setError(e.message);
    }
    setCreating(false);
  }

  return (
    <div className={`${bgMap[severity]} border rounded-lg p-3 space-y-2`}>
      <div className="flex items-start gap-2">
        <span className={`mt-0.5 ${textMap[severity]}`}>{iconMap[severity]}</span>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1 mb-0.5">
            <span className={`text-[10px] font-bold uppercase ${textMap[severity]}`}>
              {warning.type || "Warning"}
            </span>
            {severity === "high" && (
              <span className="text-[9px] px-1 py-0.5 rounded bg-red-500/20 text-red-300 font-medium">HIGH</span>
            )}
          </div>
          <p className="text-[12px] text-gray-300">{warning.message}</p>
        </div>
      </div>

      {isLedgerWarning() && !created && (
        <div className="flex items-center gap-2 ml-5">
          <button
            onClick={handleCreateLedger}
            disabled={creating}
            className="text-[10px] px-2.5 py-1 rounded-lg font-medium bg-indigo-500/20 text-indigo-300 hover:bg-indigo-500/30 disabled:opacity-50"
          >
            {creating ? "Creating..." : "+ Create Ledger"}
          </button>
          {error && <span className="text-[10px] text-red-400">{error}</span>}
        </div>
      )}

      {created && (
        <div className="ml-5 flex items-center gap-1 text-[11px] text-green-400">
          {'\u2713'} XML downloaded. Import into Tally to create ledger.
        </div>
      )}
    </div>
  );
}
