import { useState, useEffect } from "react";
import { Link } from "react-router-dom";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, PieChart, Pie, Cell } from "recharts";
import BACKEND from "../api/client";

function getClientAuth() {
  const token = localStorage.getItem("client_token");
  const user = JSON.parse(localStorage.getItem("client_user") || "null");
  return { token, user, headers: token ? { Authorization: `Bearer ${token}` } : {} };
}

function MiniBar({ data, dataKey, color }) {
  if (!data || data.length === 0) return <div className="text-gray-500 text-xs py-4 text-center">No data</div>;
  return (
    <ResponsiveContainer width="100%" height={80}>
      <BarChart data={data.slice(0, 6)} margin={{ top: 4, right: 4, bottom: 0, left: 4 }}>
        <XAxis dataKey="ledger" hide />
        <YAxis hide />
        <Tooltip
          contentStyle={{ background: "#1e1e2e", border: "1px solid #333", borderRadius: "8px", fontSize: "11px" }}
          formatter={(v) => `\u20B9${v.toFixed(2)}`}
        />
        <Bar dataKey={dataKey} fill={color} radius={[3, 3, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}

function MiniPie({ data, colors }) {
  if (!data || data.length === 0) return <div className="text-gray-500 text-xs py-4 text-center">No data</div>;
  const total = data.reduce((s, d) => s + Math.abs(d.amount), 0);
  return (
    <div className="flex items-center gap-2">
      <ResponsiveContainer width={80} height={80}>
        <PieChart>
          <Pie data={data} dataKey="amount" cx="50%" cy="50%" innerRadius={18} outerRadius={36} stroke="none">
            {data.map((_, i) => <Cell key={i} fill={colors[i % colors.length]} />)}
          </Pie>
        </PieChart>
      </ResponsiveContainer>
      <div className="text-xs text-gray-400">
        <span className="text-white font-semibold">\u20B9{total.toFixed(0)}</span>
        <span className="block text-[10px]">{data.length} entries</span>
      </div>
    </div>
  );
}

export default function ClientDashboardPage() {
  const { user, headers } = getClientAuth();
  const [dash, setDash] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!user) { setLoading(false); return; }
    async function load() {
      try {
        const res = await fetch(`${BACKEND}/client-dashboard`, {
          method: "POST",
          headers: { "Content-Type": "application/json", ...headers },
          body: JSON.stringify({}),
        });
        if (res.ok) setDash(await res.json());
      } catch {} finally { setLoading(false); }
    }
    load();
  }, []);

  if (!user) {
    return (
      <div className="text-center py-16">
        <div className="premium-card-flat p-8 max-w-md mx-auto">
          <h1 className="text-xl font-semibold text-white mb-4">Client Portal</h1>
          <p className="text-gray-400 mb-6">Please log in to view your reports.</p>
          <Link to="/client/login" className="premium-btn-primary inline-block py-2.5 px-6">Sign In</Link>
        </div>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-24">
        <div className="animate-spin w-8 h-8 border-2 border-indigo-400 border-t-transparent rounded-full" />
      </div>
    );
  }

  const tb = dash?.trial_balance;
  const pnl = dash?.pnl;
  const bs = dash?.balance_sheet;

  return (
    <div className="space-y-5 animate-fadeInUp">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-white">Welcome, {user.name || user.email}</h1>
          <p className="text-gray-400 text-sm">Your financial snapshot</p>
        </div>
        <div className="flex items-center gap-3">
          {dash && <span className="text-xs text-gray-500">{dash.total_invoices} invoice{dash.total_invoices !== 1 ? "s" : ""} processed</span>}
          <button
            onClick={() => { localStorage.removeItem("client_token"); localStorage.removeItem("client_user"); window.location.reload(); }}
            className="text-sm text-gray-400 hover:text-white transition-colors"
          >
            Sign Out
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="premium-card-flat p-4">
          <div className="text-gray-400 text-xs uppercase tracking-wider mb-1">Net Profit</div>
          {pnl ? (
            <div className={`text-2xl font-bold ${pnl.profit >= 0 ? "text-green-400" : "text-red-400"}`}>
              \u20B9{Math.abs(pnl.profit).toFixed(2)}
              <span className="text-xs ml-1">{pnl.profit >= 0 ? "profit" : "loss"}</span>
            </div>
          ) : <div className="text-gray-500">\u20B90.00</div>}
        </div>
        <div className="premium-card-flat p-4">
          <div className="text-gray-400 text-xs uppercase tracking-wider mb-1">Total Income</div>
          {pnl ? <div className="text-2xl font-bold text-green-400">\u20B9{pnl.income.toFixed(2)}</div>
            : <div className="text-gray-500">\u20B90.00</div>}
        </div>
        <div className="premium-card-flat p-4">
          <div className="text-gray-400 text-xs uppercase tracking-wider mb-1">Total Expenses</div>
          {pnl ? <div className="text-2xl font-bold text-red-400">\u20B9{pnl.expense.toFixed(2)}</div>
            : <div className="text-gray-500">\u20B90.00</div>}
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="premium-card-flat p-5">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-semibold text-gray-200">P&L Breakdown</h2>
            <Link to="/reports/pnl" className="text-[10px] text-indigo-400 hover:text-indigo-300">Full report →</Link>
          </div>
          {pnl && pnl.income_breakdown ? (
            <div className="space-y-3">
              <div>
                <div className="flex justify-between text-xs mb-1">
                  <span className="text-green-400">Income</span>
                  <span className="text-green-400">\u20B9{pnl.income.toFixed(2)}</span>
                </div>
                <MiniPie data={pnl.income_breakdown} colors={["#22c55e", "#4ade80", "#86efac", "#bbf7d0", "#166534"]} />
              </div>
              <div>
                <div className="flex justify-between text-xs mb-1">
                  <span className="text-red-400">Expenses</span>
                  <span className="text-red-400">\u20B9{pnl.expense.toFixed(2)}</span>
                </div>
                <MiniPie data={pnl.expense_breakdown} colors={["#ef4444", "#f87171", "#fca5a5", "#fecaca", "#991b1b"]} />
              </div>
            </div>
          ) : <p className="text-gray-500 text-xs">No P&L data yet.</p>}
        </div>

        <div className="premium-card-flat p-5">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-semibold text-gray-200">Top Ledgers</h2>
            <Link to="/reports/trial-balance" className="text-[10px] text-indigo-400 hover:text-indigo-300">Full report →</Link>
          </div>
          {tb && tb.rows.length > 0 ? (
            <>
              <MiniBar data={tb.rows.map(r => ({ ...r, net: Math.abs(r.debit - r.credit) }))} dataKey="net" color="#818cf8" />
              <div className="mt-2 flex items-center justify-between text-[10px]">
                <span className={tb.is_balanced ? "text-green-400" : "text-red-400"}>
                  {tb.is_balanced ? "Balanced" : "Unbalanced"}
                </span>
                <span className="text-gray-500">{tb.rows.length} ledgers</span>
              </div>
            </>
          ) : <p className="text-gray-500 text-xs">No ledger data yet.</p>}
        </div>
      </div>

      <div className="premium-card-flat p-5">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-semibold text-gray-200">Balance Sheet Summary</h2>
          <Link to="/reports/balance-sheet" className="text-[10px] text-indigo-400 hover:text-indigo-300">Full report →</Link>
        </div>
        {bs ? (
          <div className="grid grid-cols-2 gap-4">
            <div>
              <div className="text-xs text-blue-400 mb-1">Assets</div>
              <div className="text-lg font-semibold text-white">\u20B9{bs.assets.toFixed(2)}</div>
            </div>
            <div>
              <div className="text-xs text-yellow-400 mb-1">Liabilities</div>
              <div className="text-lg font-semibold text-white">\u20B9{bs.liabilities.toFixed(2)}</div>
            </div>
            <div className="col-span-2 flex items-center gap-2 text-xs">
              <span className={bs.balanced ? "text-green-400" : "text-red-400"}>
                {bs.balanced ? "Balanced" : "Unbalanced"}
              </span>
              {bs.balanced && <span className="text-gray-500">— Assets equal Liabilities</span>}
            </div>
          </div>
        ) : <p className="text-gray-500 text-xs">No balance sheet data yet.</p>}
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        <Link to="/reports/trial-balance" className="premium-card-flat p-3 text-center hover:bg-gray-800/50 transition-colors">
          <div className="text-white text-sm font-medium">Trial Balance</div>
          <div className="text-gray-400 text-xs mt-1">All ledgers</div>
        </Link>
        <Link to="/reports/pnl" className="premium-card-flat p-3 text-center hover:bg-gray-800/50 transition-colors">
          <div className="text-white text-sm font-medium">P&L Statement</div>
          <div className="text-gray-400 text-xs mt-1">Income & expenses</div>
        </Link>
        <Link to="/reports/balance-sheet" className="premium-card-flat p-3 text-center hover:bg-gray-800/50 transition-colors">
          <div className="text-white text-sm font-medium">Balance Sheet</div>
          <div className="text-gray-400 text-xs mt-1">Assets & liabilities</div>
        </Link>
      </div>
    </div>
  );
}