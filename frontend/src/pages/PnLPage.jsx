import { useState, useEffect } from "react";
import { useAuth } from "../auth";
import BACKEND from "../api/client";
import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer, Legend, BarChart, Bar, XAxis, YAxis, CartesianGrid } from "recharts";

const COLORS = ["#10B981", "#EF4444", "#3B82F6", "#F59E0B", "#8B5CF6", "#EC4899"];

export default function PnLPage() {
  const { getAuthHeaders } = useAuth();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  async function fetchReport() {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${BACKEND}/pnl`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...getAuthHeaders() },
      });
      if (!res.ok) throw new Error("Failed to load P&L");
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
    { name: "Income", value: Math.max(0, data.income || 0) },
    { name: "Expenses", value: Math.max(0, data.expense || 0) },
  ] : [];

  const incomeChart = data?.income_breakdown?.map(r => ({ name: r.ledger, amount: r.amount })) || [];
  const expenseChart = data?.expense_breakdown?.map(r => ({ name: r.ledger, amount: r.amount })) || [];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-white">Profit & Loss Statement</h1>
          <p className="text-gray-400 text-sm">Income − Expenses = Net Profit/Loss</p>
        </div>
        <button onClick={fetchReport} className="premium-btn-primary text-sm py-1.5 px-4">Refresh</button>
      </div>

      {loading && <div className="text-center text-gray-400 py-12 animate-pulse">Loading P&L...</div>}
      {error && <div className="premium-card-flat p-4 text-red-400">{error}</div>}

      {data && !loading && (
        <>
          <div className="grid grid-cols-3 gap-4">
            <div className="premium-card-flat p-4 text-center">
              <div className="text-gray-400 text-sm">Total Income</div>
              <div className="text-2xl font-semibold text-green-400">₹{data.income?.toFixed(2)}</div>
            </div>
            <div className="premium-card-flat p-4 text-center">
              <div className="text-gray-400 text-sm">Total Expenses</div>
              <div className="text-2xl font-semibold text-red-400">₹{data.expense?.toFixed(2)}</div>
            </div>
            <div className={`premium-card-flat p-4 text-center ${(data.profit || 0) >= 0 ? "border-green-500/30" : "border-red-500/30"}`}>
              <div className="text-gray-400 text-sm">{data.profit >= 0 ? "Net Profit" : "Net Loss"}</div>
              <div className={`text-2xl font-semibold ${data.profit >= 0 ? "text-green-400" : "text-red-400"}`}>
                ₹{Math.abs(data.profit || 0).toFixed(2)}
              </div>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="premium-card-flat p-4">
              <h3 className="text-sm font-medium text-gray-300 mb-3">Income vs Expenses</h3>
              <ResponsiveContainer width="100%" height={250}>
                <PieChart>
                  <Pie data={pieData} cx="50%" cy="50%" innerRadius={60} outerRadius={100} paddingAngle={5} dataKey="value">
                    {pieData.map((_, i) => <Cell key={i} fill={COLORS[i]} />)}
                  </Pie>
                  <Tooltip contentStyle={{ backgroundColor: "#1F2937", border: "1px solid #374151", borderRadius: "8px" }} />
                  <Legend />
                </PieChart>
              </ResponsiveContainer>
            </div>

            <div className="premium-card-flat p-4">
              <h3 className="text-sm font-medium text-gray-300 mb-3">Summary</h3>
              <div className="space-y-3">
                <div className="flex justify-between py-2 border-b border-gray-700">
                  <span className="text-gray-300">Total Income</span>
                  <span className="text-green-400 font-medium">₹{data.income?.toFixed(2)}</span>
                </div>
                <div className="flex justify-between py-2 border-b border-gray-700">
                  <span className="text-gray-300">Total Expenses</span>
                  <span className="text-red-400 font-medium">₹{data.expense?.toFixed(2)}</span>
                </div>
                <div className="flex justify-between py-2 text-lg">
                  <span className="text-white font-semibold">{data.profit >= 0 ? "Net Profit" : "Net Loss"}</span>
                  <span className={`font-bold ${data.profit >= 0 ? "text-green-400" : "text-red-400"}`}>
                    ₹{Math.abs(data.profit || 0).toFixed(2)}
                  </span>
                </div>
              </div>
            </div>
          </div>

          {incomeChart.length > 0 && (
            <div className="premium-card-flat p-4">
              <h3 className="text-sm font-medium text-gray-300 mb-3">Income Breakdown</h3>
              <ResponsiveContainer width="100%" height={200}>
                <BarChart data={incomeChart}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                  <XAxis dataKey="name" tick={{ fill: "#9CA3AF", fontSize: 11 }} />
                  <YAxis tick={{ fill: "#9CA3AF", fontSize: 11 }} />
                  <Tooltip contentStyle={{ backgroundColor: "#1F2937", border: "1px solid #374151" }} />
                  <Bar dataKey="amount" fill="#10B981" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}

          {expenseChart.length > 0 && (
            <div className="premium-card-flat p-4">
              <h3 className="text-sm font-medium text-gray-300 mb-3">Expense Breakdown</h3>
              <ResponsiveContainer width="100%" height={200}>
                <BarChart data={expenseChart}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                  <XAxis dataKey="name" tick={{ fill: "#9CA3AF", fontSize: 11 }} />
                  <YAxis tick={{ fill: "#9CA3AF", fontSize: 11 }} />
                  <Tooltip contentStyle={{ backgroundColor: "#1F2937", border: "1px solid #374151" }} />
                  <Bar dataKey="amount" fill="#EF4444" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </>
      )}
    </div>
  );
}
