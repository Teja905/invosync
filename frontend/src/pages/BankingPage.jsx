import { useState, useEffect } from "react";
import { useAuth } from "../auth";
import BACKEND from "../api/client";

export default function BankingPage() {
  const { getAuthHeaders } = useAuth();
  const [rules, setRules] = useState([]);
  const [keyword, setKeyword] = useState("");
  const [voucherType, setVoucherType] = useState("Receipt");
  const [targetLedger, setTargetLedger] = useState("");
  const [txInput, setTxInput] = useState("");
  const [bankLedger, setBankLedger] = useState("Bank");
  const [processed, setProcessed] = useState(null);
  const [xml, setXml] = useState("");
  const [loading, setLoading] = useState(true);

  const fetchRules = () => {
    fetch(`${BACKEND}/api/v3/banking/rules`, { headers: getAuthHeaders() })
      .then((r) => r.json()).then(setRules).catch(() => {}).finally(() => setLoading(false));
  };

  useEffect(() => { fetchRules(); }, []);

  async function addRule() {
    if (!keyword.trim() || !targetLedger.trim()) return;
    await fetch(`${BACKEND}/api/v3/banking/rules`, {
      method: "POST", headers: { "Content-Type": "application/json", ...getAuthHeaders() },
      body: JSON.stringify({ keyword: keyword.trim(), voucher_type: voucherType, target_ledger: targetLedger.trim() }),
    });
    setKeyword(""); setTargetLedger("");
    fetchRules();
  }

  async function deleteRule(id) {
    await fetch(`${BACKEND}/api/v3/banking/rules/${id}`, { method: "DELETE", headers: getAuthHeaders() });
    fetchRules();
  }

  async function processStatement() {
    let txs;
    try { txs = JSON.parse(txInput); } catch { return; }
    const res = await fetch(`${BACKEND}/api/v3/banking/process`, {
      method: "POST", headers: { "Content-Type": "application/json", ...getAuthHeaders() },
      body: JSON.stringify({ transactions: txs, bank_ledger: bankLedger }),
    });
    if (res.ok) { const d = await res.json(); setProcessed(d.processed); setXml(d.xml); }
  }

  return (
    <div className="space-y-4 animate-fadeInUp">
      <h2 className="text-lg font-bold premium-gradient-text">Bank Statement Automation</h2>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="premium-card-flat p-5 space-y-3">
          <h3 className="text-sm font-semibold text-gray-200">Keyword Rules</h3>
          <p className="text-xs text-gray-400">Map keywords → voucher type + ledger (e.g. "Razorpay" → Receipt → URD Debtors)</p>
          {loading ? <p className="text-xs text-gray-500">Loading...</p> : (
            <div className="space-y-2 max-h-60 overflow-y-auto">
              {rules.length === 0 && <p className="text-xs text-gray-500">No rules yet.</p>}
              {rules.map((r) => (
                <div key={r.id} className="flex items-center justify-between bg-white/5 rounded-lg px-3 py-2">
                  <div className="text-xs"><span className="font-mono text-yellow-400">{r.keyword}</span> <span className="text-gray-500">→</span> <span className="text-blue-400">{r.voucher_type}</span> <span className="text-gray-500">→</span> <span className="text-green-400">{r.target_ledger}</span></div>
                  <button onClick={() => deleteRule(r.id)} className="text-red-400 hover:text-red-300 text-xs">&times;</button>
                </div>
              ))}
            </div>
          )}
          <div className="flex gap-2 items-end">
            <div className="flex-1 space-y-1">
              <label className="text-[10px] text-gray-500">Keyword</label>
              <input className="input w-full text-xs" value={keyword} onChange={(e) => setKeyword(e.target.value)} placeholder="e.g. Razorpay" />
            </div>
            <div className="w-24 space-y-1">
              <label className="text-[10px] text-gray-500">Type</label>
              <select className="input w-full text-xs" value={voucherType} onChange={(e) => setVoucherType(e.target.value)}>
                <option>Receipt</option><option>Payment</option><option>Journal</option>
              </select>
            </div>
            <div className="flex-1 space-y-1">
              <label className="text-[10px] text-gray-500">Ledger</label>
              <input className="input w-full text-xs" value={targetLedger} onChange={(e) => setTargetLedger(e.target.value)} placeholder="e.g. URD Debtors" />
            </div>
            <button onClick={addRule} className="px-3 py-2 bg-indigo-500/20 text-indigo-300 rounded-lg text-xs font-medium hover:bg-indigo-500/30">Add</button>
          </div>
        </div>
        <div className="premium-card-flat p-5 space-y-3">
          <h3 className="text-sm font-semibold text-gray-200">Process Statement</h3>
          <p className="text-xs text-gray-400">Paste JSON array of transactions, click Process</p>
          <div className="flex gap-2">
            <div className="flex-1">
              <label className="text-[10px] text-gray-500">Bank Ledger in Tally</label>
              <input className="input w-full text-xs" value={bankLedger} onChange={(e) => setBankLedger(e.target.value)} />
            </div>
          </div>
          <textarea className="input w-full h-28 text-xs font-mono" value={txInput} onChange={(e) => setTxInput(e.target.value)} placeholder='[{"transaction_date":"2026-07-09","description":"ACH CRED-RAZORPAY","withdraw_amount":0,"deposit_amount":4247,"balance":50000}]' />
          <button onClick={processStatement} className="px-4 py-2 bg-indigo-500/20 text-indigo-300 rounded-lg text-xs font-medium hover:bg-indigo-500/30">Process</button>
          {processed && (
            <div className="space-y-2">
              <h4 className="text-xs font-semibold text-gray-300">Mapped Transactions ({processed.length})</h4>
              <div className="max-h-40 overflow-y-auto space-y-1">
                {processed.map((tx, i) => (
                  <div key={i} className="text-xs bg-white/5 rounded px-2 py-1 flex gap-2">
                    <span className="text-gray-500 w-20">{tx.transaction_date}</span>
                    <span className="text-gray-300 flex-1 truncate">{tx.description}</span>
                    <span className={tx.voucher_type === "Receipt" ? "text-green-400" : "text-red-400"}>{tx.voucher_type}</span>
                    <span className="text-blue-400">{tx.target_ledger}</span>
                    {tx.rule_applied && <span className="text-yellow-500 text-[10px]">({tx.rule_applied})</span>}
                  </div>
                ))}
              </div>
              {xml && <button onClick={() => { const b = new Blob([xml], {type:"application/xml"}); const a = document.createElement("a"); a.href=URL.createObjectURL(b); a.download="bank_statement.xml"; a.click(); }} className="text-xs text-indigo-400 underline">Download XML</button>}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
