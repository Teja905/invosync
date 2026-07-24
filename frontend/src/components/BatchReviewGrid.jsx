import { useState, useEffect, useRef, useCallback } from "react";
import { useAuth } from "../auth";
import BACKEND from "../api/client";
import { queuedFetch } from "../api/queue";
import { useToast } from "./Toast";
import { CONFIDENCE_THRESHOLDS } from "../constants/thresholds";

const STATUS_META = {
  validated: { color: "green", label: "Ready", tag: "gh-tag-green" },
  draft: { color: "yellow", label: "Review", tag: "gh-tag-yellow" },
  extraction_failed: { color: "red", label: "Failed", tag: "gh-tag-red" },
  processing: { color: "blue", label: "Processing", tag: "gh-tag-blue" },
  processing_queued: { color: "blue", label: "Queued", tag: "gh-tag-blue" },
  synced: { color: "purple", label: "Synced", tag: "gh-tag-gray" },
};

function confPct(inv) {
  const c = inv.ind_confidence ?? inv.confidence;
  return c != null ? Math.round(c * 100) : null;
}

function confColor(pct) {
  if (pct == null) return "text-gray-500";
  if (pct >= CONFIDENCE_THRESHOLDS.HIGH * 100) return "text-green-400";
  if (pct >= CONFIDENCE_THRESHOLDS.MEDIUM * 100) return "text-yellow-400";
  return "text-red-400";
}

export default function BatchReviewGrid({ invoiceIds, onRefresh, onReviewInvoice }) {
  const { getAuthHeaders } = useAuth();
  const toast = useToast();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState("all");
  const [selected, setSelected] = useState(new Set());
  const [syncing, setSyncing] = useState(false);
  const pollRef = useRef(null);

  const fetchBatchStatus = useCallback(async () => {
    if (!invoiceIds || invoiceIds.length === 0) return;
    try {
      const res = await fetch(`${BACKEND}/api/v3/extraction/batch-status`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...getAuthHeaders() },
        body: JSON.stringify({ invoice_ids: invoiceIds }),
      });
      if (!res.ok) return;
      const body = await res.json();
      const results = body.results || {};

      const invRes = await fetch(`${BACKEND}/invoices`, { headers: getAuthHeaders() });
      const allInvs = invRes.ok ? await invRes.json() : [];
      const invMap = {};
      for (const inv of allInvs) invMap[inv.id] = inv;

      const summary = { total: 0, validated: 0, draft: 0, failed: 0, processing: 0, queued: 0, synced: 0 };
      const invoices = [];
      for (const [oid, st] of Object.entries(results)) {
        const inv = invMap[st.display_id] || {};
        const status = st.status || "unknown";
        summary.total++;
        if (status === "validated") summary.validated++;
        else if (status === "draft") summary.draft++;
        else if (status === "extraction_failed") summary.failed++;
        else if (status === "synced") summary.synced++;
        else if (st.processing_state === "processing") summary.processing++;
        else summary.queued++;

        invoices.push({
          oid,
          display_id: st.display_id,
          status,
          processing_state: st.processing_state,
          vendor_name: inv.extracted?.vendor_name || "",
          invoice_number: inv.extracted?.invoice_number || "",
          total_amount: inv.extracted?.total_amount ?? null,
          ind_confidence: inv.ind_confidence ?? inv.confidence ?? null,
          date: inv.extracted?.date || "",
        });
      }
      setData({ summary, invoices, all_done: summary.processing === 0 && summary.queued === 0 });
    } catch {
    } finally {
      setLoading(false);
    }
  }, [invoiceIds, getAuthHeaders]);

  useEffect(() => {
    fetchBatchStatus();
    pollRef.current = setInterval(() => {
      fetchBatchStatus();
    }, 3000);
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [fetchBatchStatus]);

  useEffect(() => {
    if (data?.all_done && pollRef.current) {
      clearInterval(pollRef.current);
    }
  }, [data?.all_done]);

  function toggleSelect(oid) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(oid)) next.delete(oid); else next.add(oid);
      return next;
    });
  }

  function toggleSelectAll() {
    const visible = filteredInvoices();
    if (selected.size === visible.length && visible.length > 0) {
      setSelected(new Set());
    } else {
      setSelected(new Set(visible.map((i) => i.oid)));
    }
  }

  function filteredInvoices() {
    if (!data) return [];
    if (filter === "all") return data.invoices;
    return data.invoices.filter((inv) => {
      if (filter === "validated") return inv.status === "validated";
      if (filter === "draft") return inv.status === "draft";
      if (filter === "failed") return inv.status === "extraction_failed";
      return true;
    });
  }

  async function bulkSyncReady() {
    const readyIds = data.invoices
      .filter((i) => i.status === "validated" && i.display_id)
      .map((i) => i.display_id);
    if (readyIds.length === 0) { toast.warning("No ready invoices to sync"); return; }
    setSyncing(true);
    try {
      const res = await queuedFetch("/api/v3/invoices/bulk/sync", {
        method: "POST",
        headers: { "Content-Type": "application/json", ...getAuthHeaders() },
        body: JSON.stringify({ invoice_ids: readyIds }),
      });
      if (res.ok) {
        toast.success(`Synced ${readyIds.length} invoices to Tally`);
        fetchBatchStatus();
        if (onRefresh) onRefresh();
      } else {
        const err = await res.json().catch(() => ({}));
        toast.error(err.detail || "Sync failed");
      }
    } catch (e) { toast.error(e.message); }
    finally { setSyncing(false); }
  }

  async function bulkConfirmReview() {
    const draftIds = data.invoices
      .filter((i) => i.status === "draft" && i.display_id)
      .map((i) => i.display_id);
    if (draftIds.length === 0) { toast.warning("No draft invoices to confirm"); return; }
    try {
      const res = await queuedFetch("/api/v3/invoices/bulk/confirm-review", {
        method: "POST",
        headers: { "Content-Type": "application/json", ...getAuthHeaders() },
        body: JSON.stringify({ invoice_ids: draftIds }),
      });
      if (res.ok) {
        const body = await res.json();
        const confirmed = body.results?.filter((r) => r.ok).length || 0;
        const failed = body.results?.filter((r) => !r.ok).length || 0;
        toast.success(`Confirmed ${confirmed}${failed ? ` · ${failed} failed` : ""}`);
        fetchBatchStatus();
        if (onRefresh) onRefresh();
      }
    } catch (e) { toast.error(e.message); }
  }

  if (!invoiceIds || invoiceIds.length === 0) return null;
  if (loading) {
    return (
      <div className="gh-card p-6 text-center">
        <div className="text-sm text-gray-400">Loading batch status...</div>
      </div>
    );
  }
  if (!data) return null;

  const s = data.summary;
  const pctReady = s.total ? Math.round((s.validated / s.total) * 100) : 0;
  const pctDraft = s.total ? Math.round((s.draft / s.total) * 100) : 0;
  const pctFailed = s.total ? Math.round((s.failed / s.total) * 100) : 0;
  const pctProcessing = s.total ? Math.round(((s.processing + s.queued) / s.total) * 100) : 0;

  return (
    <div className="space-y-4">
      {/* Summary Cards */}
      <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
        <SummaryCard count={s.validated} label="Ready to Sync" color="green" />
        <SummaryCard count={s.draft} label="Needs Review" color="yellow" />
        <SummaryCard count={s.processing + s.queued} label="Processing" color="blue" />
        <SummaryCard count={s.failed} label="Failed" color="red" />
        <SummaryCard count={s.total} label="Total" color="gray" />
      </div>

      {/* Progress Bar */}
      <div className="gh-card p-3">
        <div className="flex h-3 rounded-full overflow-hidden bg-gray-800">
          {pctReady > 0 && <div className="bg-green-500 transition-all duration-500" style={{ width: `${pctReady}%` }} />}
          {pctDraft > 0 && <div className="bg-yellow-500 transition-all duration-500" style={{ width: `${pctDraft}%` }} />}
          {pctFailed > 0 && <div className="bg-red-500 transition-all duration-500" style={{ width: `${pctFailed}%` }} />}
          {pctProcessing > 0 && <div className="bg-blue-500 animate-pulse transition-all duration-500" style={{ width: `${pctProcessing}%` }} />}
        </div>
        {!data.all_done && (
          <div className="text-[10px] text-gray-500 mt-1.5 text-center">
            Processing... {s.processing + s.queued} remaining
          </div>
        )}
      </div>

      {/* Filters + Bulk Actions */}
      <div className="flex flex-wrap items-center gap-2">
        <FilterBtn active={filter === "all"} onClick={() => setFilter("all")} count={s.total} label="All" />
        <FilterBtn active={filter === "validated"} onClick={() => setFilter("validated")} count={s.validated} label="Ready" color="green" />
        <FilterBtn active={filter === "draft"} onClick={() => setFilter("draft")} count={s.draft} label="Review" color="yellow" />
        <FilterBtn active={filter === "failed"} onClick={() => setFilter("failed")} count={s.failed} label="Failed" color="red" />
        <div className="flex-1" />
        {s.draft > 0 && (
          <button onClick={bulkConfirmReview} className="gh-btn gh-btn-secondary text-xs px-3 py-1.5">
            Confirm All Review ({s.draft})
          </button>
        )}
        {s.validated > 0 && (
          <button onClick={bulkSyncReady} disabled={syncing} className="gh-btn gh-btn-primary text-xs px-3 py-1.5">
            {syncing ? "Syncing..." : `Sync All Ready (${s.validated})`}
          </button>
        )}
      </div>

      {/* Invoice Table */}
      <div className="gh-card overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-800 text-xs text-gray-500 uppercase tracking-wider">
              <th className="px-3 py-2 text-left w-8">
                <input type="checkbox" checked={selected.size === filteredInvoices().length && filteredInvoices().length > 0 && selected.size > 0}
                  onChange={toggleSelectAll} className="accent-blue-500" />
              </th>
              <th className="px-3 py-2 text-left">Vendor</th>
              <th className="px-3 py-2 text-left">Invoice #</th>
              <th className="px-3 py-2 text-right">Amount</th>
              <th className="px-3 py-2 text-center">Confidence</th>
              <th className="px-3 py-2 text-center">Status</th>
              <th className="px-3 py-2 text-right">Action</th>
            </tr>
          </thead>
          <tbody>
            {filteredInvoices().map((inv) => {
              const meta = STATUS_META[inv.status] || STATUS_META.draft;
              const pct = confPct(inv);
              return (
                <tr key={inv.oid} className={`border-b border-gray-800/50 hover:bg-white/[0.02] ${selected.has(inv.oid) ? "bg-blue-500/5" : ""}`}>
                  <td className="px-3 py-2">
                    <input type="checkbox" checked={selected.has(inv.oid)} onChange={() => toggleSelect(inv.oid)} className="accent-blue-500" />
                  </td>
                  <td className="px-3 py-2 text-gray-300 truncate max-w-[180px]">{inv.vendor_name || "—"}</td>
                  <td className="px-3 py-2 text-gray-400 font-mono text-xs">{inv.invoice_number || "—"}</td>
                  <td className="px-3 py-2 text-right text-gray-300 font-mono">
                    {inv.total_amount != null ? `₹${Number(inv.total_amount).toLocaleString("en-IN")}` : "—"}
                  </td>
                  <td className="px-3 py-2 text-center">
                    {pct != null ? (
                      <span className={`text-xs font-medium ${confColor(pct)}`}>{pct}%</span>
                    ) : (
                      <span className="text-xs text-gray-600">—</span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-center">
                    <span className={`gh-tag ${meta.tag} text-[10px] px-2 py-0.5`}>{meta.label}</span>
                  </td>
                  <td className="px-3 py-2 text-right">
                    {inv.status === "draft" && inv.display_id && (
                      <button onClick={() => onReviewInvoice && onReviewInvoice(inv.display_id)}
                        className="text-[10px] text-blue-400 hover:text-blue-300 px-2 py-1 rounded bg-blue-500/10 hover:bg-blue-500/20 transition-colors">
                        Review
                      </button>
                    )}
                    {inv.status === "extraction_failed" && (
                      <span className="text-[10px] text-red-400/60">Failed</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {filteredInvoices().length === 0 && (
          <div className="text-center py-8 text-gray-500 text-sm">No invoices in this category</div>
        )}
      </div>
    </div>
  );
}

function SummaryCard({ count, label, color }) {
  const colors = {
    green: "border-green-500/30 text-green-400",
    yellow: "border-yellow-500/30 text-yellow-400",
    blue: "border-blue-500/30 text-blue-400",
    red: "border-red-500/30 text-red-400",
    gray: "border-gray-600/30 text-gray-400",
  };
  return (
    <div className={`gh-card p-3 border ${colors[color] || colors.gray}`}>
      <div className="text-xl font-bold">{count}</div>
      <div className="text-[10px] uppercase tracking-wider opacity-70">{label}</div>
    </div>
  );
}

function FilterBtn({ active, onClick, count, label, color }) {
  const base = "text-xs px-2.5 py-1 rounded-full border transition-colors";
  const activeCls = active
    ? "border-blue-500/50 bg-blue-500/15 text-blue-300"
    : "border-gray-700 bg-transparent text-gray-500 hover:text-gray-300 hover:border-gray-600";
  return (
    <button onClick={onClick} className={`${base} ${activeCls}`}>
      {label} ({count})
    </button>
  );
}
