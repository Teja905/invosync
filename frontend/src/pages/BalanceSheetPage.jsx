import { useState, useEffect } from "react";
import { useAuth } from "../auth";
import BACKEND from "../api/client";
import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer, Legend } from "recharts";

const COLORS = ["#3B82F6", "#F59E0B", "#10B981", "#EF4444", "#8B5CF6"];

export default function BalanceSheetPage() {
  const { getAuthHeaders } = useAuth();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  async function fetchReport() {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${BACKEND}/balance-sheet`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...getAuthHeaders() },
      });
      if (!res.ok) throw new Error("Failed to load balance sheet");
      const d = await res.json();
      setData(d);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { fetchReport(); }, []);

  const pieData = data ? [
    { name: "Assets", value: Math.max(0, data.assets || 0) },
    { name: "Liabilities", value: Math.max(0, data.liabilities || 0) },
  ] : [];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-white">Balance Sheet</h1>
          <p className="text-gray-400 text-sm">Assets = Liabilities (must be balanced)</p>
        </div>
        <button onClick={fetchReport} className="premium-btn-primary text-sm py-1.5 px-4">Refresh</button>
      </div>

      {loading && <div className="text-center text-gray-400 py-12 animate-pulse">Loading balance sheet...</div>}
      {error && <div className="premium-card-flat p-4 text-red-400">{error}</div>}

      {data && !loading && (
        <>
          <div className="grid grid-cols-3 gap-4">
            <div className="premium-card-flat p-4 text-center">
              <div className="text-gray-400 text-sm">Total Assets</div>
              <div className="text-2xl font-semibold text-blue-400">₹{data.assets?.toFixed(2)}</div>
            </div>
            <div className="premium-card-flat p-4 text-center">
              <div className="text-gray-400 text-sm">Total Liabilities</div>
              <div className="text-2xl font-semibold text-yellow-400">₹{data.liabilities?.toFixed(2)}</div>
            </div>
            <div className={`premium-card-flat p-4 text-center ${data.balanced ? "border-green-500/30" : "border-red-500/30"}`}>
              <div className="text-gray-400 text-sm">Status</div>
              <div className={`text-lg font-semibold ${data.balanced ? "text-green-400" : "text-red-400"}`}>
                {data.balanced ? "Balanced" : "Unbalanced"}
              </div>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="premium-card-flat p-4">
              <h3 className="text-sm font-medium text-gray-300 mb-3">Asset / Liability Split</h3>
              <ResponsiveContainer width="100%" height={250}>
                <PieChart>
                  <Pie data={pieData} cx="50%" cy="50%" innerRadius={60} outerRadius={100} paddingAngle={5} dataKey="value">
                    {pieData.map((_, i) => <Cell key={i} fill={COLORS[i]} />)}
                  </Pie>
                  <Tooltip contentStyle={{ backgroundColor: "#1F2937", border: "1px solid #374151" }} />
                  <Legend />
                </PieChart>
              </ResponsiveContainer>
            </div>

            <div className="premium-card-flat p-4">
              <h3 className="text-sm font-medium text-gray-300 mb-3">Net Position</h3>
              <div className="space-y-3">
                <div className="flex justify-between py-2 border-b border-gray-700">
                  <span className="text-gray-300">Total Assets</span>
                  <span className="text-blue-400 font-medium">₹{data.assets?.toFixed(2)}</span>
                </div>
                <div className="flex justify-between py-2 border-b border-gray-700">
                  <span className="text-gray-300">Total Liabilities</span>
                  <span className="text-yellow-400 font-medium">₹{data.liabilities?.toFixed(2)}</span>
                </div>
                <div className="flex justify-between py-2 text-lg">
                  <span className="text-white font-semibold">Equity</span>
                  <span className="text-green-400 font-bold">₹{((data.assets || 0) - (data.liabilities || 0)).toFixed(2)}</span>
                </div>
              </div>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="premium-card-flat overflow-hidden">
              <div className="px-4 py-3 border-b border-gray-700 text-sm font-medium text-blue-400">Assets</div>
              <table className="w-full text-sm">
                <tbody>
                  {data.asset_breakdown?.map((r, i) => (
                    <tr key={i} className="border-b border-gray-800 hover:bg-gray-800/50">
                      <td className="py-2.5 px-4 text-white">{r.ledger}</td>
                      <td className="py-2.5 px-4 text-right text-blue-400">₹{r.amount?.toFixed(2)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="premium-card-flat overflow-hidden">
              <div className="px-4 py-3 border-b border-gray-700 text-sm font-medium text-yellow-400">Liabilities</div>
              <table className="w-full text-sm">
                <tbody>
                  {data.liability_breakdown?.map((r, i) => (
                    <tr key={i} className="border-b border-gray-800 hover:bg-gray-800/50">
                      <td className="py-2.5 px-4 text-white">{r.ledger}</td>
                      <td className="py-2.5 px-4 text-right text-yellow-400">₹{r.amount?.toFixed(2)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
