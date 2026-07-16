import { useState, useEffect } from "react";
import { useAuth } from "../auth";
import BACKEND from "../api/client";

export default function CorrectionMemoryUI() {
  const { getAuthHeaders, user } = useAuth();
  const [corrections, setCorrections] = useState({});
  const [newDesc, setNewDesc] = useState("");
  const [newLedger, setNewLedger] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    fetch(`${BACKEND}/corrections`, { headers: getAuthHeaders() })
      .then((r) => r.json())
      .then((d) => setCorrections(d.corrections || {}))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [user]);

  async function addCorrection() {
    if (!newDesc.trim() || !newLedger.trim()) return;
    setSaving(true);
    try {
      const res = await fetch(`${BACKEND}/corrections`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...getAuthHeaders() },
        body: JSON.stringify({ description: newDesc.trim(), ledger: newLedger.trim() }),
      });
      if (res.ok) {
        setCorrections((p) => ({ ...p, [newDesc.trim().toLowerCase()]: newLedger.trim() }));
        setNewDesc(""); setNewLedger("");
      }
    } catch {}
    setSaving(false);
  }

  async function clearAll() {
    if (!window.confirm("Clear all correction memory?")) return;
    await fetch(`${BACKEND}/corrections`, { method: "DELETE", headers: getAuthHeaders() });
    setCorrections({});
  }

  async function removeOne(desc) {
    await fetch(`${BACKEND}/corrections`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...getAuthHeaders() },
      body: JSON.stringify({ description: desc, ledger: "" }),
    });
    setCorrections((p) => { const n = { ...p }; delete n[desc]; return n; });
  }

  const entries = Object.entries(corrections);
  return (
    <div>
      {loading ? (
        <div className="text-xs text-gray-500">Loading...</div>
      ) : entries.length > 0 ? (
        <div className="space-y-1.5 mb-3 max-h-48 overflow-y-auto">
          {entries.map(([desc, ledger]) => (
            <div key={desc} className="flex items-center gap-2 text-xs">
              <span className="text-gray-300 font-mono min-w-0 flex-1 truncate">{desc}</span>
              <span className="text-gray-500">→</span>
              <span className="text-indigo-300 font-mono min-w-0 flex-1 truncate">{ledger}</span>
              <button onClick={() => removeOne(desc)} className="text-red-400 hover:text-red-300 shrink-0">✕</button>
            </div>
          ))}
        </div>
      ) : (
        <p className="text-xs text-gray-600 mb-3">No corrections yet. They will appear here after you save them.</p>
      )}
      <div className="flex gap-2">
        <input className="input flex-1 text-xs" placeholder="Description (e.g. AWS)"
          value={newDesc} onChange={(e) => setNewDesc(e.target.value)} />
        <input className="input flex-1 text-xs" placeholder="Ledger (e.g. Professional Charges)"
          value={newLedger} onChange={(e) => setNewLedger(e.target.value)} />
        <button onClick={addCorrection} disabled={saving || !newDesc.trim() || !newLedger.trim()}
          className="premium-btn-primary text-xs px-3 py-1.5 shrink-0">Save</button>
      </div>
      {entries.length > 0 && (
        <button onClick={clearAll} className="text-xs text-red-400 hover:text-red-300 mt-3">Clear all</button>
      )}
    </div>
  );
}
