import React, { useState, useEffect } from 'react';

const BACKEND = import.meta.env.VITE_API_URL || (
  window.location.hostname === "localhost" ? "" : "https://invosync-backend-yjfa.onrender.com"
);

function getAuthHeaders() {
  const t = localStorage.getItem("token");
  return t ? { Authorization: `Bearer ${t}` } : {};
}

export default function PremiumVoucherReviewWorkspace({ invoiceId, onClose, onSaved }) {
  const [inv, setInv] = useState(null);
  const [ledger, setLedger] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!invoiceId) return;
    setLoading(true);
    Promise.all([
      fetch(`${BACKEND}/invoices/${invoiceId}`, { headers: getAuthHeaders() }).then(r => r.json()),
      fetch(`${BACKEND}/api/v3/invoices/${invoiceId}/preview-ledger`, { headers: getAuthHeaders() }).then(r => r.json()),
    ]).then(([invData, ledgerData]) => {
      setInv(invData); setLedger(ledgerData);
    }).catch(() => {}).finally(() => setLoading(false));
  }, [invoiceId]);

  function setField(k, v) { setInv(p => ({ ...p, [k]: v })); }

  async function handleSave() {
    setSaving(true);
    try {
      const r = await fetch(`${BACKEND}/invoices/${invoiceId}`, {
        method: "PUT", headers: { "Content-Type": "application/json", ...getAuthHeaders() },
        body: JSON.stringify(inv),
      });
      if (r.ok) {
        await fetch(`${BACKEND}/api/v3/invoices/${invoiceId}/confirm-review`, {
          method: "POST", headers: getAuthHeaders(),
        });
        onSaved?.(); onClose?.();
      }
    } catch {} finally { setSaving(false); }
  }

  if (loading) return (
    <div className="flex h-[400px] items-center justify-center">
      <div className="h-8 w-8 animate-spin rounded-full border-4 border-slate-700 border-t-indigo-500" />
    </div>
  );
  if (!inv) return <p className="text-sm text-red-400">Failed to load invoice</p>;

  const confidence = inv.confidence ?? 1;
  const lowConf = confidence < 0.65;

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 animate-fadeIn">
      {/* LEFT: Image */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 space-y-3">
        <div className="flex justify-between items-center pb-2 border-b border-slate-800">
          <span className="text-xs font-bold text-slate-500 uppercase tracking-wider">Invoice Image</span>
          <span className="text-[10px] font-mono text-slate-600">#{inv.display_id}</span>
        </div>
        <div className="w-full h-[500px] bg-slate-950 rounded-lg border border-slate-800/60 flex items-center justify-center overflow-hidden">
          {inv._image_available ? (
            <img src={`${BACKEND}/invoices/${invoiceId}/image`} alt="Invoice" className="max-w-full max-h-full object-contain" />
          ) : (
            <p className="text-xs text-slate-600">No image available</p>
          )}
        </div>
      </div>

      {/* RIGHT: Fields + Ledger Preview */}
      <div className="space-y-5">
        {/* Extracted fields */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 space-y-4">
          <h3 className="text-xs font-bold text-slate-500 uppercase tracking-wider border-b border-slate-800 pb-2">Extracted Fields</h3>
          <div className="grid grid-cols-2 gap-3">
            {[{k:"invoice_number",l:"Invoice No"},{k:"date",l:"Date"},{k:"vendor_name",l:"Party"},{k:"total_amount",l:"Total"}].map(f => (
              <div key={f.k} className={`p-2.5 rounded-md bg-slate-950 border ${lowConf ? 'border-amber-500/30 ring-1 ring-amber-500/10' : 'border-slate-800/60'}`}>
                <label className="text-[10px] font-bold text-slate-500 uppercase">{f.l}</label>
                <input value={inv[f.k] || ""} onChange={e => setField(f.k, e.target.value)}
                  className="w-full bg-transparent border-0 p-0 text-sm font-bold text-slate-100 focus:ring-0 focus:outline-none" />
              </div>
            ))}
          </div>
          {lowConf && <p className="text-[10px] text-amber-400 flex items-center gap-1">⚠ Low confidence ({Math.round(confidence * 100)}%) — please verify</p>}
        </div>

        {/* Ledger preview */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 space-y-3">
          <div className="flex justify-between items-center border-b border-slate-800 pb-2">
            <h3 className="text-xs font-bold text-slate-500 uppercase tracking-wider">Double-Entry Preview</h3>
            <span className="text-[10px] bg-indigo-500/10 border border-indigo-500/20 text-indigo-400 px-2 py-0.5 rounded font-mono">{ledger?.voucher_type}</span>
          </div>
          <div className="space-y-1.5 max-h-56 overflow-y-auto">
            {ledger?.ledger_entries?.map((e, i) => (
              <div key={i} className="flex items-center justify-between p-2.5 bg-slate-950 border border-slate-800/60 rounded-lg text-xs font-mono">
                <div className="flex items-center gap-2 min-w-0">
                  <span className={`shrink-0 w-14 text-center px-1 py-0.5 rounded text-[10px] font-bold ${
                    e.type.startsWith("Debit") ? 'bg-blue-500/10 text-blue-400' : 'bg-purple-500/10 text-purple-400'
                  }`}>{e.type}</span>
                  <span className="truncate text-slate-300">{e.ledger_name}</span>
                </div>
                <span className="shrink-0 font-bold text-slate-400">₹{Math.abs(parseFloat(e.amount)).toLocaleString('en-IN', {minimumFractionDigits:2})}</span>
              </div>
            ))}
          </div>
          <div className="flex items-center justify-between p-2.5 bg-slate-950 border border-slate-800 rounded-lg">
            <span className="text-[10px] font-bold text-slate-500 uppercase tracking-wider">Zero-Sum Check</span>
            {ledger?.is_balanced ? (
              <span className="text-[10px] font-bold text-emerald-400">✔ Balanced (0.00)</span>
            ) : (
              <span className="text-[10px] font-bold text-rose-400 animate-pulse">⚠ Out of Balance</span>
            )}
          </div>
        </div>

        {/* Actions */}
        <button onClick={handleSave} disabled={saving}
          className="w-full bg-gradient-to-r from-indigo-500 to-violet-500 hover:from-indigo-600 hover:to-violet-600 disabled:opacity-50 text-white font-bold text-xs uppercase tracking-widest py-3.5 rounded-xl shadow-xl transition flex items-center justify-center gap-2">
          {saving ? <div className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent" /> : "Save & Post to Tally"}
        </button>
      </div>
    </div>
  );
}
