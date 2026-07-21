import { useState, useEffect } from "react";
import { useAuth } from "../auth";
import BACKEND from "../api/client";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from "recharts";

export default function TrialBalancePage() {
  const { getAuthHeaders } = useAuth();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [params, setParams] = useState({ start_date: "", end_date: "" });

  async function fetchReport(overrides = {}) {
    setLoading(true);
    setError(null);
    try {
      const p = { ...params, ...overrides };
      const body = {};
      if (p.start_date) body.start_date = p.start_date;
      if (p.end_date) body.end_date = p.end_date;
      const res = await fetch(`${BACKEND}/trial-balance`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...getAuthHeaders() },
        body: JSON.stringify(body),
      });
      if (!res.ok) throw new Error("Failed to load trial balance");
      const d = await res.json();
      setData(d);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { fetchReport(); }, []);

  const chartData = data?.rows?.slice(0, 20).map(r => ({
    name: r.ledger.length > 15 ? r.ledger.slice(0, 15) + "..." : r.ledger,
    Debit: r.debit || 0,
    Credit: r.credit || 0,
  })) || [];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-white">Trial Balance</h1>
          <p className="text-gray-400 text-sm">Verification: all ledgers with debit/credit totals</p>
        </div>
        <div className="flex gap-3 items-center">
          <input type="date" value={params.start_date} onChange={e => setParams(p => ({...p, start_date: e.target.value}))}
            className="premium-input text-sm py-1.5 w-36" placeholder="Start date" />
          <input type="date" value={params.end_date} onChange={e => setParams(p => ({...p, end_date: e.target.value}))}
            className="premium-input text-sm py-1.5 w-36" placeholder="End date" />
          <button onClick={() => fetchReport()} className="premium-btn-primary text-sm py-1.5 px-4">Refresh</button>
        </div>
      </div>

      {loading && <div className="text-center text-gray-400 py-12 animate-pulse">Loading trial balance...</div>}
      {error && <div className="premium-card-flat p-4 text-red-400">{error}</div>}

      {data && !loading && (
        <>
          <div className="grid grid-cols-3 gap-4">
            <div className="premium-card-flat p-4 text-center">
              <div className="text-gray-400 text-sm">Total Debit</div>
              <div className="text-2xl font-semibold text-white">₹{data.total_debit?.toFixed(2)}</div>
            </div>
            <div className="premium-card-flat p-4 text-center">
              <div className="text-gray-400 text-sm">Total Credit</div>
              <div className="text-2xl font-semibold text-white">₹{data.total_credit?.toFixed(2)}</div>
            </div>
            <div className={`premium-card-flat p-4 text-center ${data.is_balanced ? "border-green-500/30" : "border-red-500/30"}`}>
              <div className="text-gray-400 text-sm">Status</div>
              <div className={`text-lg font-semibold ${data.is_balanced ? "text-green-400" : "text-red-400"}`}>
                {data.is_balanced ? "Balanced" : `Diff: ₹${data.difference?.toFixed(2)}`}
              </div>
            </div>
          </div>

          {chartData.length > 0 && (
            <div className="premium-card-flat p-4">
              <h3 className="text-sm font-medium text-gray-300 mb-3">Top 20 Ledgers</h3>
              <ResponsiveContainer width="100%" height={300}>
                <BarChart data={chartData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                  <XAxis dataKey="name" tick={{ fill: "#9CA3AF", fontSize: 11 }} />
                  <YAxis tick={{ fill: "#9CA3AF", fontSize: 11 }} />
                  <Tooltip contentStyle={{ backgroundColor: "#1F2937", border: "1px solid #374151", borderRadius: "8px" }} />
                  <Bar dataKey="Debit" fill="#3B82F6" radius={[4, 4, 0, 0]} />
                  <Bar dataKey="Credit" fill="#10B981" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}

          <div className="premium-card-flat overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-700 text-gray-400">
                  <th className="text-left py-3 px-4">Ledger</th>
                  <th className="text-right py-3 px-4">Account Type</th>
                  <th className="text-right py-3 px-4">Debit</th>
                  <th className="text-right py-3 px-4">Credit</th>
                </tr>
              </thead>
              <tbody>
                {data.rows?.map((r, i) => (
                  <tr key={i} className="border-b border-gray-800 hover:bg-gray-800/50">
                    <td className="py-2.5 px-4 text-white">{r.ledger}</td>
                    <td className="py-2.5 px-4 text-right text-gray-400">{r.account_type}</td>
                    <td className="py-2.5 px-4 text-right text-blue-400">{r.debit > 0 ? `₹${r.debit.toFixed(2)}` : "-"}</td>
                    <td className="py-2.5 px-4 text-right text-green-400">{r.credit > 0 ? `₹${r.credit.toFixed(2)}` : "-"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
