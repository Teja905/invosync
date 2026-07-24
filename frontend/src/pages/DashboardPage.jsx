import { useState, useEffect, useRef } from "react";
import { useAuth } from "../auth";
import BACKEND from "../api/client";
import { queuedFetch } from "../api/queue";
import { useToast } from "../components/Toast";
import { CONFIDENCE_THRESHOLDS } from "../constants/thresholds";
import ConfirmDialog from "../components/ConfirmDialog";
import WarningBanner from "../components/WarningBanner";
import MissingMastersDialog from "../components/MissingMastersDialog";
import ValidationModal from "../components/ValidationModal";

export default function DashboardPage({ refreshKey, setRefreshKey, onEditInvoice }) {
  const { getAuthHeaders } = useAuth();
  const toast = useToast();
  const [invoices, setInvoices] = useState([]);
  const [clients, setClients] = useState([]);
  const [loading, setLoading] = useState(true);
  const [fetchError, setFetchError] = useState(null);
  const [actionMsg, setActionMsg] = useState(null);
  const actionTimer = useRef(null);
  useEffect(() => {
    if (actionMsg) {
      if (actionTimer.current) clearTimeout(actionTimer.current);
      if (actionMsg.type !== "error") actionTimer.current = setTimeout(() => setActionMsg(null), 5000);
    }
    return () => { if (actionTimer.current) clearTimeout(actionTimer.current); };
  }, [actionMsg]);
  const [filterClient, setFilterClient] = useState("");
  const [showDashModal, setShowDashModal] = useState(false);
  const [dashModalData, setDashModalData] = useState(null);
  const [dashPendingInv, setDashPendingInv] = useState(null);
  const [selectedIds, setSelectedIds] = useState([]);
  const [bulkLedger, setBulkLedger] = useState("");
  const [missingMasters, setMissingMasters] = useState(null);
  const [pendingSyncInv, setPendingSyncInv] = useState(null);
  const [syncingId, setSyncingId] = useState(null);
  const [showBulkDelete, setShowBulkDelete] = useState(false);
  const [flagOnly, setFlagOnly] = useState(false);
  const [bulkReviewing, setBulkReviewing] = useState(false);

  useEffect(() => {
    fetch(`${BACKEND}/clients`, { headers: getAuthHeaders() })
      .then((r) => r.json()).then(setClients).catch(() => {});
  }, []);

  useEffect(() => {
    setLoading(true); setFetchError(null);
    const ctrl = new AbortController();
    const url = filterClient ? `${BACKEND}/invoices?client_id=${filterClient}` : `${BACKEND}/invoices`;
    fetch(url, { signal: ctrl.signal, headers: getAuthHeaders() })
      .then((r) => { if (!r.ok) throw new Error("Failed"); return r.json(); })
      .then(setInvoices)
      .catch((e) => { if (e.name !== "AbortError") setFetchError(e.message); })
      .finally(() => setLoading(false));
    return () => ctrl.abort();
  }, [refreshKey, filterClient]);

  function toggleSelect(id) {
    setSelectedIds((prev) => prev.includes(id) ? prev.filter((i) => i !== id) : [...prev, id]);
  }

  function toggleSelectAll() {
    const visible = getVisibleInvoices();
    const visibleIds = visible.map(i => i.id);
    if (selectedIds.length === visibleIds.length && visibleIds.every(id => selectedIds.includes(id))) {
      setSelectedIds([]);
    } else {
      setSelectedIds(visibleIds);
    }
  }

  function getVisibleInvoices() {
    if (!flagOnly) return invoices;
    return invoices.filter(inv => {
      const conf = inv.ind_confidence ?? inv.confidence;
      return inv.status === "draft" && conf != null && conf < CONFIDENCE_THRESHOLDS.MEDIUM;
    });
  }

  const visibleInvoices = getVisibleInvoices();

  const stats = {
    total: invoices.length,
    draft: invoices.filter(i => i.status === "draft").length,
    needsReview: invoices.filter(i => i.status === "draft" && ((i.ind_confidence ?? i.confidence) != null && (i.ind_confidence ?? i.confidence) < CONFIDENCE_THRESHOLDS.MEDIUM)).length,
    ready: invoices.filter(i => i.status === "validated").length,
    synced: invoices.filter(i => i.status === "exported").length,
  };

  async function bulkConfirmReview() {
    if (!selectedIds.length) return;
    setBulkReviewing(true);
    setActionMsg({ type: "info", text: `Confirming review for ${selectedIds.length} invoices...` });
    try {
      const res = await queuedFetch(`/api/v3/invoices/bulk/confirm-review`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...getAuthHeaders() },
        body: JSON.stringify({ invoice_ids: selectedIds }),
      });
      const body = await res.json();
      if (res.ok) {
        const { confirmed = 0, failed = 0, skipped = 0 } = body;
        const failedItems = (body.results || []).filter(r => r.status === "validation_failed" || r.status === "error");
        const skippedItems = (body.results || []).filter(r => r.status === "skipped");

        let msg = "";
        if (confirmed > 0) msg += `${confirmed} confirmed`;
        if (skipped > 0) msg += `${msg ? " · " : ""}${skipped} skipped (not draft)`;
        if (failed > 0) {
          const details = failedItems.slice(0, 5).map(r => {
            const errs = r.errors || [r.error || "Unknown"];
            return `#${r.id}: ${errs.join(", ")}`;
          }).join("; ");
          msg += `${msg ? " · " : ""}${failed} failed — ${details}`;
        }
        const msgType = failed > 0 ? "warning" : "success";
        setActionMsg({ type: msgType, text: msg || "Done" });
        setSelectedIds([]);
        setRefreshKey((k) => k + 1);
      } else {
        setActionMsg({ type: "error", text: body.message || "Bulk confirm failed" });
      }
    } catch (e) {
      setActionMsg({ type: e.queued ? "info" : "error", text: e.queued ? "Saved offline — will sync when reconnected." : "Bulk confirm failed" });
    } finally {
      setBulkReviewing(false);
    }
  }

  async function applyBulkMap() {
    if (!selectedIds.length || !bulkLedger.trim()) return;
    try {
      const res = await queuedFetch(`/api/v3/invoices/bulk-map`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...getAuthHeaders() },
        body: JSON.stringify({ invoice_ids: selectedIds, target_ledger: bulkLedger.trim() }),
      });
      if (res.ok) { setActionMsg({ type: "success", text: `${selectedIds.length} invoices mapped to "${bulkLedger}"` }); setSelectedIds([]); setRefreshKey((k) => k + 1); }
      else setActionMsg({ type: "error", text: "Bulk map failed" });
    } catch (e) {
      setActionMsg({ type: e.queued ? "info" : "error", text: e.queued ? "Saved offline — will sync when reconnected." : "Bulk map failed" });
    }
  }

  async function generateXml(inv, force = false) {
    setActionMsg({ type: "info", text: "Validating..." });
    try {
      const res = await fetch(`${BACKEND}/invoices/${inv.id}/generate?force=${force}`, { method: "POST", headers: getAuthHeaders() });
      if (res.status === 422) {
        const body = await res.json();
        let fixes = [];
        try {
          const fr = await fetch(`${BACKEND}/api/v3/invoices/${inv.id}/validate-with-fixes`, { headers: getAuthHeaders() });
          if (fr.ok) { const fd = await fr.json(); fixes = fd.fix_suggestions || []; }
        } catch {}
        setDashModalData({
          blocking: body.blocking_errors || [],
          soft: body.soft_errors || [],
          warnings: body.warnings || [],
          fix_suggestions: fixes,
          message: body.message || "Validation produced warnings",
        });
        setDashPendingInv(inv);
        setShowDashModal(true);
        return;
      }
      const result = await res.json();
      if (result.valid) {
        const blob = new Blob([result.xml], { type: "text/plain" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a"); a.href = url; a.download = `invoice_${inv.id}_${(inv.invoice_number||"output").replace(/[^a-zA-Z0-9_-]/g,"_")}.xml`; a.click();
        URL.revokeObjectURL(url);
        setActionMsg({ type: "success", text: "XML downloaded!" });
        setRefreshKey((k) => k + 1);
      } else setActionMsg({ type: "error", text: "Validation failed." });
    } catch (e) { setActionMsg({ type: "error", text: e.message }); }
  }

  async function downloadXml(id) {
    try {
      const res = await fetch(`${BACKEND}/invoices/${id}/xml`, { headers: getAuthHeaders() });
      if (!res.ok) throw new Error("Not available");
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a"); a.href = url; a.download = `invoice_${id}.xml`; a.click();
      URL.revokeObjectURL(url);
    } catch (e) { setActionMsg({ type: "error", text: e.message }); }
  }

  async function sendToTally(inv) {
    setActionMsg(null);
    try {
      const preRes = await fetch(`${BACKEND}/api/v3/sync/preflight-diagnostics`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...getAuthHeaders() },
        body: JSON.stringify({
          invoice_data: { vendor_name: inv.vendor_name, line_items: inv.line_items || [],
            voucher_type: inv.voucher_type, total_amount: inv.total_amount,
            invoice_date: inv.invoice_date, invoice_number: inv.invoice_number },
        }),
      });
      if (preRes.ok) {
        const preResult = await preRes.json();
        if (preResult.missing_masters && preResult.missing_masters.length > 0) {
          setPendingSyncInv(inv);
          setMissingMasters(preResult.missing_masters);
          return;
        }
      }
    } catch (e) {}

    await queueSyncNow(inv);
  }

  async function queueSyncNow(inv) {
    setSyncingId(inv.id);
    setActionMsg({ type: "info", text: "Queueing for Tally sync..." });
    try {
      const res = await queuedFetch(`/api/v3/invoices/${inv.id}/sync-now`, { method: "POST", headers: getAuthHeaders() });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `HTTP ${res.status}`);
      }
      const result = await res.json();
      setActionMsg({ type: "success", text: result.message || "Queued! Connector will pick it up within 30s." });
      toast.success("Queued for Tally sync");
      setRefreshKey((k) => k + 1);
    } catch (e) {
      setActionMsg({ type: e.queued ? "info" : "error", text: e.queued ? "Saved offline — will sync when reconnected." : `Sync trigger failed: ${e.message}` });
    } finally {
      setSyncingId(null);
    }
  }

  function handleMastersDone(action) {
    setMissingMasters(null);
    const inv = pendingSyncInv;
    setPendingSyncInv(null);
    if (action === "synced" || action === "created") {
      queueSyncNow(inv);
    }
  }

  async function confirmBulkDelete() {
    try {
      const res = await queuedFetch(`/api/v3/invoices/bulk/delete`, {
        method: "POST", headers: {"Content-Type":"application/json", ...getAuthHeaders()},
        body: JSON.stringify({invoice_ids: selectedIds}),
      });
      if (res.ok) { setActionMsg({type:"success", text:"Deleted"}); setSelectedIds([]); setRefreshKey(k=>k+1); toast.success("Invoices deleted"); }
    } catch (e) {
      if (!e.queued) setActionMsg({type:"error", text:"Delete failed"});
    } finally {
      setShowBulkDelete(false);
    }
  }

  function confidenceBar(inv) {
    const conf = inv.ind_confidence ?? inv.confidence;
    if (conf == null) return <span className="text-xs text-gray-500">—</span>;
    const pct = Math.round(conf * 100);
    let color = "bg-green-500";
    let textColor = "text-green-400";
    if (conf < CONFIDENCE_THRESHOLDS.MEDIUM) { color = "bg-red-500"; textColor = "text-red-400"; }
    else if (conf < CONFIDENCE_THRESHOLDS.HIGH) { color = "bg-yellow-500"; textColor = "text-yellow-400"; }
    return (
      <div className="flex items-center gap-1.5" title={`Confidence: ${pct}%`}>
        <div className="w-12 h-1.5 bg-gray-700 rounded-full overflow-hidden">
          <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
        </div>
        <span className={`text-xs ${textColor}`}>{pct}%</span>
      </div>
    );
  }

  function statusBadge(inv) {
    const s = inv.status;
    const conf = inv.ind_confidence ?? inv.confidence;
    const needsReview = conf != null && conf < 0.7;

    if (s === "draft") {
      return (
        <div className="flex items-center gap-1.5">
          {needsReview ? (
            <span className="premium-badge premium-badge-danger text-[10px]">{'\u26A0'} Needs Review</span>
          ) : (
            <span className="premium-badge premium-badge-warning text-[10px]">Draft</span>
          )}
        </div>
      );
    }
    if (s === "validated") {
      return <span className="premium-badge premium-badge-success text-[10px]">{'\u2713'} Reviewed</span>;
    }
    if (s === "exported") {
      return <span className="premium-badge premium-badge-info text-[10px]">{'\u2192'} Exported</span>;
    }
    if (s === "sync_error") {
      return <span className="premium-badge premium-badge-danger text-[10px]">{'\u2717'} Failed</span>;
    }
    return <span className="premium-badge premium-badge-neutral text-[10px]">{s || "Pending"}</span>;
  }

  function tallySyncBadge(inv) {
    const s = inv.status;
    if (s === "exported") {
      return <span className="inline-flex items-center gap-1 text-xs font-medium px-2 py-0.5 rounded-full" style={{ background: "rgba(16,185,129,0.15)", color: "#34d399" }}>
        {'\u2713'} Synced
      </span>;
    }
    if (s === "sync_error") {
      return (
        <div className="flex flex-col items-center gap-1">
          <span className="inline-flex items-center gap-1 text-xs font-medium px-2 py-0.5 rounded-full" style={{ background: "rgba(239,68,68,0.15)", color: "#f87171" }} title={inv.sync_error || ""}>
            {'\u2717'} Failed
          </span>
          {inv.sync_error && <span className="text-[9px] text-red-400/70 max-w-[120px] truncate" title={inv.sync_error}>{inv.sync_error}</span>}
        </div>
      );
    }
    if (s === "validated" && inv.xml_generated) {
      if (syncingId === inv.id) {
        return <span className="text-xs font-medium text-blue-400 flex items-center gap-1.5"><span className="w-3.5 h-3.5 border-2 border-blue-400/40 border-t-blue-400 rounded-full animate-spin" />Sending…</span>;
      }
      return <button onClick={(e) => { e.stopPropagation(); sendToTally(inv); }}
        className="text-xs font-medium text-blue-400 hover:text-blue-300 underline">{'\u2192'} Send</button>;
    }
    return <span className="text-xs text-gray-500">-</span>;
  }

  function xmlBadge(inv) {
    if (inv.status === "draft") {
      return <button onClick={(e) => { e.stopPropagation(); onEditInvoice(inv.id); }}
        className="text-xs font-medium text-yellow-400 hover:text-yellow-300 underline">{'\u26A0'} Review</button>;
    }
    if (inv.xml_generated) {
      return <button onClick={(e) => { e.stopPropagation(); downloadXml(inv.id); }}
        className="text-xs font-medium text-indigo-400 hover:text-indigo-300 underline">{'\u2193'} Download</button>;
    }
    return <button onClick={(e) => { e.stopPropagation(); generateXml(inv); }}
      className="text-xs font-medium text-yellow-400 hover:text-yellow-300 underline">{'\u2699'} Generate</button>;
  }

  if (loading) return <div className="text-center py-20"><div className="w-8 h-8 border-2 border-indigo-400 border-t-transparent rounded-full animate-spin mx-auto" /></div>;

  return (
    <div className="space-y-4 animate-fadeInUp">
      {actionMsg && (
        <div className={`premium-card rounded-xl p-4 text-sm flex items-center gap-2 ${
          actionMsg.type === "error" ? "border-red-500/20 text-red-300"
          : actionMsg.type === "success" ? "border-green-500/20 text-green-300"
          : actionMsg.type === "warning" ? "border-yellow-500/20 text-yellow-300"
          : "border-indigo-500/20 text-indigo-300"
        }`}>{actionMsg.text}</div>
      )}

      {fetchError && (
        <div className="premium-card rounded-xl p-4 text-sm flex items-center gap-2 border-red-500/20 text-red-300">
          <span>{'\u26A0'} Failed to load invoices: {fetchError}</span>
          <button onClick={() => { setFetchError(null); setRefreshKey((k) => k + 1); }}
            className="ml-auto text-xs px-3 py-1 rounded-lg bg-red-500/20 hover:bg-red-500/30 text-red-300">Retry</button>
        </div>
      )}

      {/* Summary Stats */}
      {invoices.length > 0 && (
        <div className="grid grid-cols-5 gap-3">
          {[
            { label: "Total", value: stats.total, color: "text-gray-200", bg: "bg-gray-500/10" },
            { label: "Draft", value: stats.draft, color: "text-yellow-400", bg: "bg-yellow-500/10" },
            { label: "Needs Review", value: stats.needsReview, color: "text-red-400", bg: "bg-red-500/10" },
            { label: "Ready", value: stats.ready, color: "text-green-400", bg: "bg-green-500/10" },
            { label: "Synced", value: stats.synced, color: "text-blue-400", bg: "bg-blue-500/10" },
          ].map(s => (
            <div key={s.label} className={`premium-card rounded-xl px-4 py-3 ${s.bg}`}>
              <div className={`text-2xl font-bold ${s.color}`}>{s.value}</div>
              <div className="text-xs text-gray-400 mt-0.5">{s.label}</div>
            </div>
          ))}
        </div>
      )}

      {/* Filters + Client Selector */}
      <div className="premium-card rounded-xl px-4 py-3 flex items-center gap-3 flex-wrap">
        <label className="text-sm text-gray-300 whitespace-nowrap">Filter by client:</label>
        <select className="input max-w-xs" value={filterClient} onChange={(e) => setFilterClient(e.target.value)}>
          <option value="">All Clients</option>
          {clients.map((c) => (
            <option key={c.client_id} value={c.client_id}>{c.company_name}</option>
          ))}
        </select>
        <div className="ml-auto flex items-center gap-2">
          <label className="flex items-center gap-1.5 text-sm text-gray-300 cursor-pointer select-none">
            <input type="checkbox" className="accent-yellow-500" checked={flagOnly}
              onChange={(e) => { setFlagOnly(e.target.checked); setSelectedIds([]); }} />
            Flagged only
          </label>
          {flagOnly && <span className="text-xs text-yellow-400">({stats.needsReview} items)</span>}
        </div>
      </div>

      {invoices.length === 0 ? (
        <div className="premium-card-flat p-10 text-center space-y-3">
          <div className="text-4xl opacity-40">📄</div>
          <h3 className="text-lg font-semibold text-[var(--premium-text-primary)]">No invoices yet</h3>
          <p className="text-sm text-[var(--text-secondary)] max-w-sm mx-auto">
            Upload your first invoice to get started. InvoSync extracts the data, validates it, and prepares Tally-ready XML automatically.
          </p>
          <p className="text-xs text-[var(--text-tertiary)]">{'\uD83D\uDCA1'} Tip: you can upload multiple invoices at once from the Extract page.</p>
        </div>
      ) : (
        <div>
          {/* Bulk Actions Bar */}
          {selectedIds.length > 0 && (
            <div className="premium-card rounded-xl px-4 py-3 mb-3 flex flex-wrap items-center gap-2">
              <span className="text-xs text-gray-400 font-medium">{selectedIds.length} selected</span>

              <button onClick={bulkConfirmReview} disabled={bulkReviewing}
                className="px-3 py-1.5 bg-green-500/20 text-green-300 rounded-lg text-xs font-medium hover:bg-green-500/30 disabled:opacity-50 disabled:cursor-not-allowed">
                {bulkReviewing ? "Reviewing..." : "Confirm Review"}
              </button>

              <input className="input flex-1 text-xs min-w-[140px]" value={bulkLedger}
                onChange={(e) => setBulkLedger(e.target.value)} placeholder="Target ledger..." />

              <button onClick={applyBulkMap}
                className="px-3 py-1.5 bg-indigo-500/20 text-indigo-300 rounded-lg text-xs font-medium hover:bg-indigo-500/30">
                Map Ledger
              </button>

              <button onClick={async () => {
                try {
                  const res = await queuedFetch(`/api/v3/invoices/bulk/generate-xml`, {
                    method: "POST", headers: {"Content-Type":"application/json", ...getAuthHeaders()},
                    body: JSON.stringify({invoice_ids: selectedIds}),
                  });
                  if (res.ok) { setActionMsg({type:"success", text:"XML generated for selected"}); setRefreshKey(k=>k+1); }
                } catch (e) {
                  if (!e.queued) setActionMsg({type:"error", text:"Generate failed"});
                }
              }}
                className="px-3 py-1.5 bg-purple-500/20 text-purple-300 rounded-lg text-xs font-medium hover:bg-purple-500/30">
                Generate XML
              </button>

              <button onClick={async () => {
                try {
                  const res = await queuedFetch(`/api/v3/invoices/bulk/sync`, {
                    method: "POST", headers: {"Content-Type":"application/json", ...getAuthHeaders()},
                    body: JSON.stringify({invoice_ids: selectedIds}),
                  });
                  if (res.ok) { setActionMsg({type:"success", text:"Marked as synced"}); setRefreshKey(k=>k+1); }
                } catch (e) {
                  if (!e.queued) setActionMsg({type:"error", text:"Sync failed"});
                }
              }}
                className="px-3 py-1.5 bg-blue-500/20 text-blue-300 rounded-lg text-xs font-medium hover:bg-blue-500/30">
                Sync to Tally
              </button>

              <button onClick={() => setShowBulkDelete(true)}
                className="px-3 py-1.5 bg-red-500/20 text-red-300 rounded-lg text-xs font-medium hover:bg-red-500/30">
                Delete
              </button>

              <button onClick={() => setSelectedIds([])}
                className="text-xs text-gray-500 hover:text-gray-300 ml-1">Clear</button>
            </div>
          )}

          {/* Invoice Table */}
          <div className="premium-card-flat overflow-hidden">
            <table className="w-full text-sm">
              <thead><tr className="border-b border-white/5 text-left text-xs text-gray-500 uppercase">
                <th className="px-2 py-3.5 w-8">
                  <input type="checkbox" className="accent-indigo-500"
                    checked={visibleInvoices.length > 0 && visibleInvoices.every(i => selectedIds.includes(i.id))}
                    onChange={toggleSelectAll} />
                </th>
                <th className="px-2 py-3.5 font-medium">#</th>
                <th className="px-4 py-3.5 font-medium">Vendor</th>
                <th className="px-4 py-3.5 font-medium">Invoice</th>
                <th className="px-4 py-3.5 font-medium">Date</th>
                <th className="px-4 py-3.5 font-medium">Confidence</th>
                <th className="px-4 py-3.5 font-medium">Status</th>
                <th className="px-4 py-3.5 font-medium text-center">Tally Sync</th>
                <th className="px-4 py-3.5 font-medium text-right">Amount</th>
                <th className="px-4 py-3.5 font-medium text-center">XML</th>
              </tr></thead>
              <tbody className="divide-y divide-white/5">
                {visibleInvoices.map((inv) => (
                  <tr key={inv.id} className={`premium-table-row cursor-pointer hover:bg-white/[0.03] ${selectedIds.includes(inv.id) ? "bg-indigo-500/5" : ""}`} onClick={() => onEditInvoice(inv.id)}>
                    <td className="px-2 py-3.5">
                      <input type="checkbox" className="accent-indigo-500" checked={selectedIds.includes(inv.id)} onChange={(e) => { e.stopPropagation(); toggleSelect(inv.id); }} onClick={(e) => e.stopPropagation()} />
                    </td>
                    <td className="px-2 py-3.5 text-gray-500 text-xs">{inv.id}</td>
                    <td className="px-4 py-3.5 font-medium text-gray-200">{inv.vendor_name || "-"}</td>
                    <td className="px-4 py-3.5 text-gray-300">{inv.invoice_number || "-"}</td>
                    <td className="px-4 py-3.5 text-gray-400">{inv.date || "-"}</td>
                    <td className="px-4 py-3.5">{confidenceBar(inv)}</td>
                    <td className="px-4 py-3.5">
                      {statusBadge(inv)}
                      {inv.decision_label && inv.decision_label !== "Unknown" && (
                        <span className={`inline-flex items-center gap-1 text-[10px] font-medium px-2 py-0.5 rounded-full mt-1`}
                          style={{ backgroundColor: inv.decision_color === "green" ? "rgba(34,197,94,0.15)" : inv.decision_color === "red" ? "rgba(239,68,68,0.15)" : inv.decision_color === "yellow" ? "rgba(234,179,8,0.15)" : "rgba(107,114,128,0.15)", color: inv.decision_color === "green" ? "#22c55e" : inv.decision_color === "red" ? "#ef4444" : inv.decision_color === "yellow" ? "#eab308" : "#9ca3af" }}>
                          {inv.decision_label}
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3.5 text-center">
                      {tallySyncBadge(inv)}
                    </td>
                    <td className="px-4 py-3.5 text-right font-medium text-gray-200">{inv.total_amount ? "\u20B9" + parseFloat(inv.total_amount).toLocaleString() : "-"}</td>
                    <td className="px-4 py-3.5 text-center">
                      {xmlBadge(inv)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {flagOnly && visibleInvoices.length === 0 && (
              <div className="p-8 text-center text-sm text-gray-500">
                No flagged invoices — all extractions look good!
              </div>
            )}
          </div>
          </div>
      )}

      {showDashModal && dashModalData && (
        <ValidationModal
          show={showDashModal}
          data={dashModalData}
          onGenerateAnyway={() => {
            const inv = dashPendingInv;
            setShowDashModal(false); setDashPendingInv(null);
            if (inv) generateXml(inv, true);
          }}
          onClose={() => { setShowDashModal(false); setDashPendingInv(null); }}
          onApplyFix={(fix) => {
            if (dashPendingInv) {
              fetch(`${BACKEND}/invoices/${dashPendingInv.id}`, {
                method: "PUT",
                headers: { "Content-Type": "application/json", ...getAuthHeaders() },
                body: JSON.stringify(
                  fix.fix_type === "correct_gstin"
                    ? { gstin: fix.fix_payload.suggestion }
                    : { [fix.fix_payload.field]: fix.fix_payload.value }
                ),
              }).then(() => { setShowDashModal(false); setDashPendingInv(null); setRefreshKey(k => k + 1); });
            }
          }}
          onFixAll={async () => {
            const fixes = dashModalData.fix_suggestions || [];
            let patch = {};
            for (const f of fixes) {
              if (f.fix_type === "correct_gstin") patch.gstin = f.fix_payload.suggestion;
              else if (f.fix_type === "set_field") patch[f.fix_payload.field] = f.fix_payload.value;
            }
            if (dashPendingInv && Object.keys(patch).length > 0) {
              await fetch(`${BACKEND}/invoices/${dashPendingInv.id}`, {
                method: "PUT",
                headers: { "Content-Type": "application/json", ...getAuthHeaders() },
                body: JSON.stringify(patch),
              });
              setActionMsg({ type: "success", text: "Fixes applied — regenerate XML" });
            }
            setShowDashModal(false); setDashPendingInv(null);
            if (dashPendingInv) setRefreshKey(k => k + 1);
          }}
        />
      )}

      {missingMasters && pendingSyncInv && (
        <MissingMastersDialog
          invoice={pendingSyncInv}
          missingMasters={missingMasters}
          onDone={handleMastersDone}
          getAuthHeaders={getAuthHeaders}
        />
      )}

      {showBulkDelete && (
        <ConfirmDialog
          title={`Delete ${selectedIds.length} invoice${selectedIds.length > 1 ? "s" : ""}?`}
          message="This permanently removes the selected invoices. This cannot be undone."
          confirmLabel="Delete"
          onConfirm={confirmBulkDelete}
          onCancel={() => setShowBulkDelete(false)}
        />
      )}
    </div>
  );
}
