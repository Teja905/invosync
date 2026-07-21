import { useState, useEffect } from "react";
import { Link } from "react-router-dom";
import BACKEND from "../api/client";

function getClientAuth() {
  const token = localStorage.getItem("client_token");
  const user = JSON.parse(localStorage.getItem("client_user") || "null");
  return { token, user, headers: token ? { Authorization: `Bearer ${token}` } : {} };
}

export default function ClientDashboardPage() {
  const { user, headers } = getClientAuth();
  const [tb, setTb] = useState(null);
  const [pnl, setPnl] = useState(null);
  const [bs, setBs] = useState(null);

  useEffect(() => {
    if (!user) return;
    async function load() {
      const opts = { method: "POST", headers: { "Content-Type": "application/json", ...headers } };
      try {
        const [tbRes, pnlRes, bsRes] = await Promise.all([
          fetch(`${BACKEND}/trial-balance`, opts),
          fetch(`${BACKEND}/pnl`, opts),
          fetch(`${BACKEND}/balance-sheet`, opts),
        ]);
        if (tbRes.ok) setTb(await tbRes.json());
        if (pnlRes.ok) setPnl(await pnlRes.json());
        if (bsRes.ok) setBs(await bsRes.json());
      } catch {}
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

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-white">Welcome, {user.name || user.email}</h1>
          <p className="text-gray-400 text-sm">Your financial reports at a glance</p>
        </div>
        <button
          onClick={() => { localStorage.removeItem("client_token"); localStorage.removeItem("client_user"); window.location.reload(); }}
          className="text-sm text-gray-400 hover:text-white transition-colors"
        >
          Sign Out
        </button>
      </div>

      <div className="grid grid-cols-3 gap-4">
        <Link to="/reports/trial-balance" className="premium-card-flat p-4 hover:bg-gray-800/50 transition-colors">
          <div className="text-gray-400 text-sm">Trial Balance</div>
          <div className="text-lg font-semibold text-white mt-1">
            {tb ? `${tb.rows?.length || 0} ledgers` : "Loading..."}
          </div>
          {tb && <div className={`text-xs mt-1 ${tb.is_balanced ? "text-green-400" : "text-red-400"}`}>{tb.is_balanced ? "Balanced" : "Unbalanced"}</div>}
        </Link>

        <Link to="/reports/pnl" className="premium-card-flat p-4 hover:bg-gray-800/50 transition-colors">
          <div className="text-gray-400 text-sm">Profit & Loss</div>
          {pnl ? (
            <>
              <div className="text-lg font-semibold text-green-400 mt-1">₹{pnl.income?.toFixed(2)}</div>
              <div className="text-xs text-gray-500">Income</div>
              <div className="text-sm font-medium text-red-400">₹{pnl.expense?.toFixed(2)}</div>
              <div className="text-xs text-gray-500">Expenses</div>
            </>
          ) : <div className="text-gray-500 mt-1">Loading...</div>}
        </Link>

        <Link to="/reports/balance-sheet" className="premium-card-flat p-4 hover:bg-gray-800/50 transition-colors">
          <div className="text-gray-400 text-sm">Balance Sheet</div>
          <div className="text-lg font-semibold text-blue-400 mt-1">{bs ? `₹${bs.assets?.toFixed(2)}` : "Loading..."}</div>
          {bs && <div className={`text-xs mt-1 ${bs.balanced ? "text-green-400" : "text-red-400"}`}>{bs.balanced ? "Balanced" : "Unbalanced"}</div>}
        </Link>
      </div>

      <div className="premium-card-flat p-6">
        <h2 className="text-sm font-medium text-gray-300 mb-4">Your Reports</h2>
        <div className="grid grid-cols-3 gap-4">
          <Link to="/reports/trial-balance" className="text-center p-4 rounded-lg bg-gray-800/50 hover:bg-gray-700/50 transition-colors">
            <div className="text-3xl mb-2">📊</div>
            <div className="text-white text-sm font-medium">Trial Balance</div>
            <div className="text-gray-400 text-xs mt-1">All ledgers with balances</div>
          </Link>
          <Link to="/reports/pnl" className="text-center p-4 rounded-lg bg-gray-800/50 hover:bg-gray-700/50 transition-colors">
            <div className="text-3xl mb-2">📈</div>
            <div className="text-white text-sm font-medium">P&L Statement</div>
            <div className="text-gray-400 text-xs mt-1">Income vs expenses</div>
          </Link>
          <Link to="/reports/balance-sheet" className="text-center p-4 rounded-lg bg-gray-800/50 hover:bg-gray-700/50 transition-colors">
            <div className="text-3xl mb-2">📋</div>
            <div className="text-white text-sm font-medium">Balance Sheet</div>
            <div className="text-gray-400 text-xs mt-1">Assets & liabilities</div>
          </Link>
        </div>
      </div>
    </div>
  );
}
