import { useState } from "react";
import BACKEND from "../api/client";

const ALL_GROUPS = [
  "Purchase Accounts", "Sales Accounts", "Indirect Expenses", "Bank Accounts",
  "Sundry Debtors", "Sundry Creditors", "Duties & Taxes", "Fixed Assets",
  "Current Assets", "Current Liabilities", "Direct Expenses", "Direct Incomes",
  "Revenue Accounts", "Indirect Incomes", "Capital Account", "Reserves & Surplus",
  "Secured Loans", "Unsecured Loans", "Cash-in-hand", "Stock-in-hand",
  "Deposits (Assets)", "Loans & Advances (Assets)", "Investments",
  "Branch / Divisions", "Suspense A/c", "Profit & Loss A/c",
  "Miscellaneous Expenses (ASSET)", "Sales Tax",
];

export default function MissingMastersDialog({ invoice, missingMasters, onDone, getAuthHeaders }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState(false);

  const [edits, setEdits] = useState(() => {
    const map = {};
    (missingMasters || []).forEach((m, i) => {
      map[i] = { name: m.name, parent: m.parent };
    });
    return map;
  });

  if (!missingMasters || missingMasters.length === 0) return null;

  const groups = missingMasters.filter((m) => m.type === "group");
  const ledgers = missingMasters.filter((m) => m.type === "ledger");

  function updateEdit(index, field, value) {
    setEdits((prev) => ({ ...prev, [index]: { ...prev[index], [field]: value } }));
  }

  function getConfidenceBadge(confidence) {
    if (confidence >= 90) return { bg: "bg-green-500/10", text: "text-green-400", label: `Confidence: ${confidence}%` };
    if (confidence >= 70) return { bg: "bg-yellow-500/10", text: "text-yellow-400", label: `Confidence: ${confidence}%` };
    return { bg: "bg-red-500/10", text: "text-red-400", label: `Confidence: ${confidence}%` };
  }

  function getUsedParents() {
    const used = new Set();
    Object.values(edits).forEach((e) => { if (e.parent) used.add(e.parent); });
    return used;
  }

  async function handleCreateAll() {
    setBusy(true);
    setError("");

    const masters = missingMasters.map((m, i) => ({
      type: m.type,
      name: edits[i]?.name || m.name,
      parent: edits[i]?.parent || m.parent,
    }));

    const parentChanged = missingMasters.some((m, i) => {
      const edit = edits[i];
      return edit && edit.parent !== m.parent;
    });

    try {
      if (parentChanged) {
        // Submit edits with corrections for learning
        const editsPayload = missingMasters.map((m, i) => ({
          original_description: m.reason?.includes("Line item") ? m.name : "",
          type: m.type,
          name: edits[i]?.name || m.name,
          parent: edits[i]?.parent || m.parent,
        }));

        const res = await fetch(`${BACKEND}/api/v3/sync/apply-master-edits`, {
          method: "POST",
          headers: { "Content-Type": "application/json", ...getAuthHeaders() },
          body: JSON.stringify({
            invoice_id: invoice?.id || invoice?.display_id,
            masters,
            edits: editsPayload,
          }),
        });
        if (!res.ok) {
          const body = await res.json().catch(() => ({}));
          throw new Error(body.detail || `HTTP ${res.status}`);
        }
        const result = await res.json();
        setSuccess(true);
        if (result.prepended_to_invoice) {
          setTimeout(() => onDone && onDone("synced"), 500);
        } else {
          setTimeout(() => onDone && onDone("created"), 500);
        }
      } else {
        // No changes — use standard auto-create
        const res = await fetch(`${BACKEND}/api/v3/sync/auto-create-masters`, {
          method: "POST",
          headers: { "Content-Type": "application/json", ...getAuthHeaders() },
          body: JSON.stringify({
            invoice_id: invoice?.id || invoice?.display_id,
            masters,
          }),
        });
        if (!res.ok) {
          const body = await res.json().catch(() => ({}));
          throw new Error(body.detail || `HTTP ${res.status}`);
        }
        const result = await res.json();
        setSuccess(true);
        if (result.prepended_to_invoice) {
          setTimeout(() => onDone && onDone("synced"), 500);
        } else {
          setTimeout(() => onDone && onDone("created"), 500);
        }
      }
    } catch (err) {
      setError(err.message);
    }
    setBusy(false);
  }

  function handleSkip() {
    onDone && onDone("skipped");
  }

  function handleKeyDown(e, index, field) {
    if (e.key === "Enter") handleCreateAll();
    if (e.key === "Escape") handleSkip();
  }

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 animate-fadeIn">
      <div className="bg-gray-900 rounded-xl max-w-lg w-full mx-4 p-6 shadow-2xl border border-white/10 max-h-[90vh] overflow-y-auto">
        <div className="flex items-start gap-3 mb-4">
          <div className="w-10 h-10 rounded-full bg-amber-500/20 flex items-center justify-center text-amber-400 text-lg shrink-0">
            {"\u26A0"}
          </div>
          <div>
            <h3 className="text-lg font-semibold text-gray-100">
              Missing Masters Detected
            </h3>
            <p className="text-sm text-gray-400 mt-0.5">
              To sync this invoice, we need to create the following in Tally.
              Edit the name or parent group if the suggestion is wrong.
            </p>
          </div>
        </div>

        {/* Groups */}
        {groups.length > 0 && (
          <div className="mb-3">
            <p className="text-xs font-medium text-gray-500 uppercase tracking-wider mb-1.5">
              Groups to create ({groups.length})
            </p>
            <div className="space-y-2">
              {groups.map((g, i) => {
                const idx = missingMasters.indexOf(g);
                const c = getConfidenceBadge(g.confidence || 85);
                return (
                  <div key={`g-${i}`} className={`border rounded-lg p-3 space-y-2 ${c.bg} border-white/5`}>
                    <div className="flex items-start gap-2">
                      <span className="text-blue-400 mt-1 text-sm shrink-0">{"\uD83D\uDCC1"}</span>
                      <div className="flex-1 min-w-0">
                        <input
                          type="text"
                          value={edits[idx]?.name || ""}
                          onChange={(e) => updateEdit(idx, "name", e.target.value)}
                          onKeyDown={(e) => handleKeyDown(e)}
                          className="w-full px-2.5 py-1.5 bg-gray-800 border border-gray-700 rounded text-sm text-gray-200 placeholder-gray-500 focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500"
                          placeholder="Group name"
                        />
                      </div>
                    </div>
                    <div className="flex items-center gap-2 ml-7">
                      <span className="text-xs text-gray-500 shrink-0">Under:</span>
                      <select
                        value={edits[idx]?.parent || ""}
                        onChange={(e) => updateEdit(idx, "parent", e.target.value)}
                        className="flex-1 px-2 py-1.5 bg-gray-800 border border-gray-700 rounded text-sm text-gray-200 focus:outline-none focus:border-indigo-500"
                      >
                        {ALL_GROUPS.map((g) => (
                          <option key={g} value={g}>{g}</option>
                        ))}
                      </select>
                      <span className={`text-xs px-1.5 py-0.5 rounded ${c.text} ${c.bg} shrink-0`}>
                        {c.label}
                      </span>
                    </div>
                    {g.reason && (
                      <p className="text-xs text-gray-500 ml-7">{g.reason}</p>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Ledgers */}
        {ledgers.length > 0 && (
          <div className="mb-4">
            <p className="text-xs font-medium text-gray-500 uppercase tracking-wider mb-1.5">
              Ledgers to create ({ledgers.length})
            </p>
            <div className="space-y-2">
              {ledgers.map((l, i) => {
                const idx = missingMasters.indexOf(l);
                const c = getConfidenceBadge(l.confidence || 85);
                const usedParents = getUsedParents();
                const parentOptions = usedParents.size > 0
                  ? [...ALL_GROUPS].filter((g) => usedParents.has(g) || g === (edits[idx]?.parent || l.parent))
                  : ALL_GROUPS;
                return (
                  <div key={`l-${i}`} className={`border rounded-lg p-3 space-y-2 ${c.bg} border-white/5`}>
                    <div className="flex items-start gap-2">
                      <span className="text-green-400 mt-1 text-sm shrink-0">{"\uD83D\uDCD2"}</span>
                      <div className="flex-1 min-w-0">
                        <input
                          type="text"
                          value={edits[idx]?.name || ""}
                          onChange={(e) => updateEdit(idx, "name", e.target.value)}
                          onKeyDown={(e) => handleKeyDown(e)}
                          className="w-full px-2.5 py-1.5 bg-gray-800 border border-gray-700 rounded text-sm text-gray-200 placeholder-gray-500 focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500"
                          placeholder="Ledger name"
                        />
                      </div>
                    </div>
                    <div className="flex items-center gap-2 ml-7">
                      <span className="text-xs text-gray-500 shrink-0">Under:</span>
                      <select
                        value={edits[idx]?.parent || ""}
                        onChange={(e) => updateEdit(idx, "parent", e.target.value)}
                        className="flex-1 px-2 py-1.5 bg-gray-800 border border-gray-700 rounded text-sm text-gray-200 focus:outline-none focus:border-indigo-500"
                      >
                        {parentOptions.map((p) => (
                          <option key={p} value={p}>{p}</option>
                        ))}
                      </select>
                      <span className={`text-xs px-1.5 py-0.5 rounded ${c.text} ${c.bg} shrink-0`}>
                        {c.label}
                      </span>
                    </div>
                    {l.reason && (
                      <p className="text-xs text-gray-500 ml-7">{l.reason}</p>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Error */}
        {error && (
          <div className="mb-4 bg-red-500/10 border border-red-500/20 rounded-lg p-3">
            <p className="text-sm text-red-400">{error}</p>
          </div>
        )}

        {/* Success */}
        {success && (
          <div className="mb-4 bg-green-500/10 border border-green-500/20 rounded-lg p-3">
            <p className="text-sm text-green-400">
              {"\u2713"} Masters created successfully{missingMasters.some((m, i) => edits[i]?.parent !== m.parent) ? " and corrections saved for future" : ""}! The invoice is queued for sync.
            </p>
          </div>
        )}

        {/* Actions */}
        <div className="flex justify-end gap-3 pt-1">
          <button
            disabled={busy || success}
            className="px-3 py-2 text-sm text-gray-400 hover:text-gray-200 hover:bg-white/5 rounded-lg transition disabled:opacity-50"
            onClick={handleSkip}
          >
            Cancel, Fix Manually
          </button>
          <button
            disabled={busy || success}
            className="px-5 py-2 text-sm font-medium bg-indigo-600 text-white rounded-lg hover:bg-indigo-500 transition disabled:opacity-50 flex items-center gap-2"
            onClick={handleCreateAll}
          >
            {busy ? (
              <>
                <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
                Creating...
              </>
            ) : (
              <>
                {"\u2713"} Create All and Sync
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
