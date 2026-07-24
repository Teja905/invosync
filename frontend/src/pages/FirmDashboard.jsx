import { useState, useEffect } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../auth";
import BACKEND from "../api/client";

function HealthBadge({ score }) {
  if (score >= 80) return <span className="premium-badge premium-badge-success">{score}</span>;
  if (score >= 50) return <span className="premium-badge premium-badge-warning">{score}</span>;
  return <span className="premium-badge" style={{ background: "rgba(233,69,96,0.2)", color: "#e94560" }}>{score}</span>;
}

function StatCard({ label, value, color }) {
  return (
    <div className="premium-card-flat p-4 text-center">
      <div className="text-2xl font-bold" style={{ color: color || "var(--premium-text)" }}>{value}</div>
      <div className="text-xs text-gray-500 mt-1">{label}</div>
    </div>
  );
}

export default function FirmDashboard() {
  const { getAuthHeaders } = useAuth();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch(`${BACKEND}/firm-dashboard`, {
      method: "POST",
      headers: { ...getAuthHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify({}),
    })
      .then((r) => r.json())
      .then(setData)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  if (loading) return (
    <div className="text-center py-20">
      <div className="w-8 h-8 border-2 border-indigo-400 border-t-transparent rounded-full animate-spin mx-auto" />
    </div>
  );

  const summary = data?.summary || {};
  const clients = data?.clients || [];

  return (
    <div className="space-y-5 animate-fadeInUp">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-bold premium-gradient-text">Firm Dashboard</h2>
        <Link to="/clients" className="premium-btn-primary text-sm py-1.5 px-3">Manage Clients</Link>
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatCard label="Clients" value={summary.total_clients || 0} color="#00c896" />
        <StatCard label="Invoices" value={summary.total_invoices || 0} />
        <StatCard label="Draft Pending" value={summary.draft_pending || 0} color="#f0a500" />
        <StatCard label="Exported to Tally" value={summary.exported_to_tally || 0} color="#4da6ff" />
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatCard label="Total Amount" value={`Rs.${((summary.total_amount || 0) / 100000).toFixed(1)}L`} />
        <StatCard label="Total Tax" value={`Rs.${((summary.total_tax || 0) / 100000).toFixed(1)}L`} />
        <StatCard label="Total TDS" value={`Rs.${((summary.total_tds || 0) / 1000).toFixed(0)}K`} />
        <StatCard label="Avg Health" value={summary.avg_compliance_health || 0} color={summary.avg_compliance_health >= 70 ? "#00c896" : "#f0a500"} />
      </div>

      {/* Client Table */}
      {clients.length > 0 ? (
        <div className="premium-card-flat overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-white/5 text-left text-xs text-gray-500 uppercase">
                <th className="px-4 py-3 font-medium">Client</th>
                <th className="px-4 py-3 font-medium text-center">Invoices</th>
                <th className="px-4 py-3 font-medium text-right">Amount</th>
                <th className="px-4 py-3 font-medium text-center">Draft</th>
                <th className="px-4 py-3 font-medium text-center">Validated</th>
                <th className="px-4 py-3 font-medium text-center">Exported</th>
                <th className="px-4 py-3 font-medium text-center">Low Conf.</th>
                <th className="px-4 py-3 font-medium text-center">Health</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/5">
              {clients.map((c) => (
                <tr key={c.client_id} className="premium-table-row">
                  <td className="px-4 py-3">
                    <div className="font-medium text-gray-200">{c.client_name}</div>
                    <div className="text-xs text-gray-500">{c.company_name || ""}</div>
                  </td>
                  <td className="px-4 py-3 text-center text-gray-300">{c.invoice_count}</td>
                  <td className="px-4 py-3 text-right text-gray-300">Rs.{(c.total_amount || 0).toLocaleString("en-IN")}</td>
                  <td className="px-4 py-3 text-center">
                    {c.draft_count > 0 ? <span className="premium-badge premium-badge-warning">{c.draft_count}</span> : <span className="text-gray-600">0</span>}
                  </td>
                  <td className="px-4 py-3 text-center">
                    {c.validated_count > 0 ? <span className="premium-badge premium-badge-success">{c.validated_count}</span> : <span className="text-gray-600">0</span>}
                  </td>
                  <td className="px-4 py-3 text-center">
                    {c.exported_count > 0 ? <span className="premium-badge" style={{ background: "rgba(77,166,255,0.2)", color: "#4da6ff" }}>{c.exported_count}</span> : <span className="text-gray-600">0</span>}
                  </td>
                  <td className="px-4 py-3 text-center">
                    {c.low_confidence_count > 0 ? <span className="premium-badge" style={{ background: "rgba(233,69,96,0.2)", color: "#e94560" }}>{c.low_confidence_count}</span> : <span className="text-gray-600">0</span>}
                  </td>
                  <td className="px-4 py-3 text-center"><HealthBadge score={c.compliance_health} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="premium-card text-center py-12 text-gray-500">
          <p>No clients yet. Add clients to see the firm dashboard.</p>
          <Link to="/clients" className="premium-btn-primary mt-4 inline-block text-sm">Add Client</Link>
        </div>
      )}
    </div>
  );
}
