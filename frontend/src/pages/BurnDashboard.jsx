import { useState, useEffect } from "react";
import { useAuth } from "../auth";
import BACKEND from "../api/client";

function fmtCost(n) {
  return n != null ? `$${Number(n).toFixed(4)}` : "$0.0000";
}

function fmtTokens(n) {
  return n != null ? Number(n).toLocaleString("en-IN") : "0";
}

export default function BurnDashboard() {
  const { getAuthHeaders } = useAuth();
  const [metrics, setMetrics] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  async function fetchMetrics() {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${BACKEND}/admin/metrics/live`, {
        headers: { ...getAuthHeaders() },
      });
      if (!res.ok) throw new Error("Failed to load metrics");
      setMetrics(await res.json());
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    fetchMetrics();
    const iv = setInterval(fetchMetrics, 30000);
    return () => clearInterval(iv);
  }, []);

  const providers = metrics?.tokens_by_provider ? Object.entries(metrics.tokens_by_provider) : [];
  const costProviders = metrics?.cost_by_provider ? Object.entries(metrics.cost_by_provider) : [];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-white">API Burn Dashboard</h1>
          <p className="text-gray-400 text-sm">Track AI token consumption and estimated costs</p>
        </div>
        <button onClick={fetchMetrics} className="premium-btn-primary text-sm py-1.5 px-4" disabled={loading}>
          {loading ? "Loading..." : "Refresh"}
        </button>
      </div>

      {error && <div className="premium-card-flat p-4 text-red-400">{error}</div>}

      {metrics && !loading && (
        <>
          {/* Summary cards */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <div className="premium-card-flat p-4 text-center">
              <div className="text-gray-400 text-xs">Total Tokens Used</div>
              <div className="text-2xl font-bold text-white mt-1">{fmtTokens(metrics.total_tokens)}</div>
            </div>
            <div className="premium-card-flat p-4 text-center">
              <div className="text-gray-400 text-xs">Total Estimated Cost</div>
              <div className="text-2xl font-bold text-green-400 mt-1">{fmtCost(metrics.total_cost_usd)}</div>
            </div>
            <div className="premium-card-flat p-4 text-center">
              <div className="text-gray-400 text-xs">Invoices Processed</div>
              <div className="text-2xl font-bold text-blue-400 mt-1">{metrics.invoices_processed || 0}</div>
            </div>
            <div className="premium-card-flat p-4 text-center">
              <div className="text-gray-400 text-xs">Avg Tokens / Invoice</div>
              <div className="text-2xl font-bold text-purple-400 mt-1">
                {metrics.invoices_processed > 0 ? fmtTokens(Math.round(metrics.total_tokens / metrics.invoices_processed)) : "-"}
              </div>
            </div>
          </div>

          {/* Per-provider breakdown */}
          {providers.length > 0 && (
            <div className="premium-card-flat p-4">
              <h3 className="text-sm font-medium text-gray-300 mb-3">Tokens by Provider</h3>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                {providers.map(([provider, tokens]) => {
                  const cost = metrics.cost_by_provider?.[provider] || 0;
                  const pct = metrics.total_tokens > 0 ? (tokens / metrics.total_tokens * 100).toFixed(1) : 0;
                  return (
                    <div key={provider} className="bg-gray-800/50 rounded-lg p-3 border border-gray-700/50">
                      <div className="flex items-center justify-between mb-2">
                        <span className="text-sm font-medium text-white capitalize">{provider}</span>
                        <span className="text-xs text-gray-400">{pct}%</span>
                      </div>
                      <div className="flex items-end justify-between">
                        <div>
                          <div className="text-lg font-bold text-white">{fmtTokens(tokens)}</div>
                          <div className="text-xs text-gray-400">tokens</div>
                        </div>
                        <div className="text-right">
                          <div className="text-lg font-bold text-green-400">{fmtCost(cost)}</div>
                          <div className="text-xs text-gray-400">estimated</div>
                        </div>
                      </div>
                      {/* Progress bar */}
                      <div className="mt-2 h-1.5 bg-gray-700 rounded-full overflow-hidden">
                        <div
                          className={`h-full rounded-full ${provider === "openrouter" ? "bg-indigo-500" : "bg-emerald-500"}`}
                          style={{ width: `${pct}%` }}
                        />
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {providers.length === 0 && (
            <div className="premium-card-flat p-6 text-center text-gray-500">
              <p>No AI tokens recorded yet. Process an invoice to see usage data.</p>
            </div>
          )}

          {/* System health */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <div className="premium-card-flat p-3 text-center">
              <div className="text-gray-400 text-xs">Queue Depth</div>
              <div className={`text-lg font-bold mt-1 ${(metrics.queue_depth || 0) > 10 ? "text-yellow-400" : "text-white"}`}>
                {metrics.queue_depth || 0}
              </div>
            </div>
            <div className="premium-card-flat p-3 text-center">
              <div className="text-gray-400 text-xs">XML Generated</div>
              <div className="text-lg font-bold text-white mt-1">{metrics.xml_generated || 0}</div>
            </div>
            <div className="premium-card-flat p-3 text-center">
              <div className="text-gray-400 text-xs">Tally Synced</div>
              <div className="text-lg font-bold text-white mt-1">{metrics.tally_synced || 0}</div>
            </div>
            <div className="premium-card-flat p-3 text-center">
              <div className="text-gray-400 text-xs">Worker</div>
              <div className={`text-lg font-bold mt-1 ${metrics.worker_alive ? "text-green-400" : "text-red-400"}`}>
                {metrics.worker_alive ? "Healthy" : "Down"}
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
