import { useState, useEffect } from "react";
import { useAuth } from "../auth";
import BACKEND from "../api/client";

function fmt(n) {
  return n != null ? `₹${Number(n).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : "-";
}

function StatusDot({ matched }) {
  return (
    <span className={`inline-block w-2 h-2 rounded-full mr-2 ${matched ? "bg-green-400" : "bg-red-400"}`} />
  );
}

export default function DiffViewPage() {
  const { getAuthHeaders } = useAuth();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [filter, setFilter] = useState("all");

  async function fetchDiff() {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${BACKEND}/trial-balance/diff`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...getAuthHeaders() },
        body: JSON.stringify({}),
      });
      if (!res.ok) throw new Error("Failed to load diff");
      setData(await res.json());
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { fetchDiff(); }, []);

  const rows = data?.diff || [];
  const filtered = filter === "match" ? rows.filter(r => r.matched)
    : filter === "mismatch" ? rows.filter(r => !r.matched)
    : filter === "invosync" ? [] // handled separately
    : filter === "tally" ? []
    : rows;
  const onlyInv = data?.only_in_invosync || [];
  const onlyTally = data?.only_in_tally || [];
  const mismatchCount = (data?.mismatch_count || 0) + onlyInv.length + onlyTally.length;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-white">Diff View</h1>
          <p className="text-gray-400 text-sm">Compare InvoSync journal lines against Tally trial balance snapshot</p>
        </div>
        <button onClick={fetchDiff} className="premium-btn-primary text-sm py-1.5 px-4" disabled={loading}>
          {loading ? "Loading..." : "Refresh"}
        </button>
      </div>

      {error && <div className="premium-card-flat p-4 text-red-400">{error}</div>}

      {data && !loading && (
        <>
          {/* Summary cards */}
          <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
            <div className="premium-card-flat p-3 text-center">
              <div className="text-gray-400 text-xs">Status</div>
              <div className={`text-sm font-semibold mt-1 ${data.status === "no_tally_data" ? "text-yellow-400" : data.all_match ? "text-green-400" : "text-red-400"}`}>
                {data.status === "no_tally_data" ? "No Tally Data" : data.all_match ? "All Match" : `${mismatchCount} Mismatch${mismatchCount !== 1 ? "es" : ""}`}
              </div>
            </div>
            <div className="premium-card-flat p-3 text-center">
              <div className="text-gray-400 text-xs">Matched Ledgers</div>
              <div className="text-2xl font-bold text-green-400">{data.match_count || 0}</div>
            </div>
            <div className="premium-card-flat p-3 text-center">
              <div className="text-gray-400 text-xs">Mismatches</div>
              <div className="text-2xl font-bold text-red-400">{mismatchCount}</div>
            </div>
            <div className="premium-card-flat p-3 text-center">
              <div className="text-gray-400 text-xs">Only in InvoSync</div>
              <div className="text-2xl font-bold text-blue-400">{onlyInv.length}</div>
            </div>
            <div className="premium-card-flat p-3 text-center">
              <div className="text-gray-400 text-xs">Only in Tally</div>
              <div className="text-2xl font-bold text-orange-400">{onlyTally.length}</div>
            </div>
          </div>

          {data.total_diff > 0 && (
            <div className="premium-card-flat p-3 border border-red-500/30">
              <span className="text-red-400 text-sm font-medium">Total difference: {fmt(data.total_diff)}</span>
              {data.snapshot_date && <span className="text-gray-500 text-xs ml-3">Tally snapshot: {new Date(data.snapshot_date).toLocaleString("en-IN")}</span>}
            </div>
          )}

          {data.status === "no_tally_data" && (
            <div className="premium-card-flat p-6 text-center text-gray-400">
              <p className="text-lg mb-2">No Tally trial balance data available</p>
              <p className="text-sm">Push Tally TB data via the connector to enable comparison.</p>
            </div>
          )}

          {/* Filter tabs */}
          {data.status !== "no_tally_data" && (
            <div className="flex gap-2">
              {["all", "match", "mismatch"].map(f => (
                <button key={f} onClick={() => setFilter(f)}
                  className={`px-3 py-1 text-sm rounded-lg transition-colors ${filter === f ? "bg-indigo-600 text-white" : "bg-gray-800 text-gray-400 hover:text-white"}`}>
                  {f.charAt(0).toUpperCase() + f.slice(1)}
                </button>
              ))}
              {onlyInv.length > 0 && (
                <button onClick={() => setFilter("invosync")}
                  className={`px-3 py-1 text-sm rounded-lg transition-colors ${filter === "invosync" ? "bg-blue-600 text-white" : "bg-gray-800 text-gray-400 hover:text-white"}`}>
                  Only InvoSync ({onlyInv.length})
                </button>
              )}
              {onlyTally.length > 0 && (
                <button onClick={() => setFilter("tally")}
                  className={`px-3 py-1 text-sm rounded-lg transition-colors ${filter === "tally" ? "bg-orange-600 text-white" : "bg-gray-800 text-gray-400 hover:text-white"}`}>
                  Only Tally ({onlyTally.length})
                </button>
              )}
            </div>
          )}

          {/* Diff table */}
          {data.status !== "no_tally_data" && (
            <div className="premium-card-flat overflow-hidden">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-gray-700 text-gray-400">
                    <th className="text-left py-3 px-4">Ledger</th>
                    <th className="text-right py-3 px-4">InvoSync Dr</th>
                    <th className="text-right py-3 px-4">InvoSync Cr</th>
                    <th className="text-right py-3 px-4">Tally Dr</th>
                    <th className="text-right py-3 px-4">Tally Cr</th>
                    <th className="text-right py-3 px-4">Dr Diff</th>
                    <th className="text-right py-3 px-4">Cr Diff</th>
                  </tr>
                </thead>
                <tbody>
                  {filter === "invosync" && onlyInv.map((ledger, i) => (
                    <tr key={`inv-${i}`} className="border-b border-gray-800 bg-blue-900/10">
                      <td className="py-2.5 px-4 text-blue-400 flex items-center"><StatusDot matched={false} />{ledger}</td>
                      <td className="py-2.5 px-4 text-right text-gray-500" colSpan={6}>Only in InvoSync</td>
                    </tr>
                  ))}
                  {filter === "tally" && onlyTally.map((ledger, i) => (
                    <tr key={`tl-${i}`} className="border-b border-gray-800 bg-orange-900/10">
                      <td className="py-2.5 px-4 text-orange-400 flex items-center"><StatusDot matched={false} />{ledger}</td>
                      <td className="py-2.5 px-4 text-right text-gray-500" colSpan={6}>Only in Tally</td>
                    </tr>
                  ))}
                  {filter !== "invosync" && filter !== "tally" && filtered.map((r, i) => (
                    <tr key={i} className={`border-b border-gray-800 hover:bg-gray-800/50 ${!r.matched ? "bg-red-900/10" : ""}`}>
                      <td className="py-2.5 px-4 text-white flex items-center"><StatusDot matched={r.matched} />{r.ledger}</td>
                      <td className="py-2.5 px-4 text-right text-blue-400">{r.invosync_debit > 0 ? fmt(r.invosync_debit) : "-"}</td>
                      <td className="py-2.5 px-4 text-right text-green-400">{r.invosync_credit > 0 ? fmt(r.invosync_credit) : "-"}</td>
                      <td className="py-2.5 px-4 text-right text-blue-300">{r.tally_debit > 0 ? fmt(r.tally_debit) : "-"}</td>
                      <td className="py-2.5 px-4 text-right text-green-300">{r.tally_credit > 0 ? fmt(r.tally_credit) : "-"}</td>
                      <td className={`py-2.5 px-4 text-right ${Math.abs(r.debit_diff) > 0.01 ? "text-red-400 font-medium" : "text-gray-500"}`}>
                        {r.debit_diff !== 0 ? (r.debit_diff > 0 ? "+" : "") + fmt(r.debit_diff) : "-"}
                      </td>
                      <td className={`py-2.5 px-4 text-right ${Math.abs(r.credit_diff) > 0.01 ? "text-red-400 font-medium" : "text-gray-500"}`}>
                        {r.credit_diff !== 0 ? (r.credit_diff > 0 ? "+" : "") + fmt(r.credit_diff) : "-"}
                      </td>
                    </tr>
                  ))}
                  {filtered.length === 0 && filter !== "invosync" && filter !== "tally" && (
                    <tr><td colSpan={7} className="py-8 text-center text-gray-500">No matching rows</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  );
}
