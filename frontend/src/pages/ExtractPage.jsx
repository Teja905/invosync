import { useState, useCallback, useEffect, useRef } from "react";
import { useLocation } from "react-router-dom";
import { useAuth } from "../auth";
import BACKEND from "../api/client";
import { queuedFetch } from "../api/queue";
import { useToast } from "../components/Toast";
import ManualEntryModal from "../components/ManualEntryModal";
import ConfirmDialog from "../components/ConfirmDialog";
import UploadPanel from "../components/UploadPanel";
import ReviewPanel from "../components/ReviewPanel";
import ValidationModal from "../components/ValidationModal";
import BatchReviewGrid from "../components/BatchReviewGrid";
import { useExtract } from "../contexts/ExtractContext";

const DRAFT_KEY = "invosync_draft";

function saveDraft(data) {
  try { localStorage.setItem(DRAFT_KEY, JSON.stringify({ ...data, _saved: Date.now() })); } catch {}
}

function loadDraft() {
  try {
    const raw = localStorage.getItem(DRAFT_KEY);
    if (!raw) return null;
    const data = JSON.parse(raw);
    if (!data._saved || Date.now() - data._saved > 86400000) { localStorage.removeItem(DRAFT_KEY); return null; }
    return data;
  } catch { return null; }
}

function clearDraft() {
  try { localStorage.removeItem(DRAFT_KEY); } catch {}
}

function QueueStatusChip({ status, error, onRetry }) {
  const styles = {
    pending: { bg: "bg-gray-500/15", text: "text-gray-400", icon: "\u25CB", label: "Queued" },
    processing: { bg: "bg-indigo-500/15", text: "text-indigo-400", icon: "\u25B6", label: "Extracting" },
    done: { bg: "bg-green-500/15", text: "text-green-400", icon: "\u2713", label: "Done" },
    failed: { bg: "bg-red-500/15", text: "text-red-400", icon: "\u2717", label: "Failed" },
    duplicate: { bg: "bg-yellow-500/15", text: "text-yellow-400", icon: "\u26A0", label: "Duplicate" },
  };
  const s = styles[status] || styles.pending;
  return (
    <span className={`inline-flex items-center gap-1 text-[10px] font-medium px-2 py-0.5 rounded-full ${s.bg} ${s.text}`}>
      {status === "processing" && <span className="w-2 h-2 rounded-full bg-indigo-400 animate-pulse" />}
      {s.icon} {s.label}
    </span>
  );
}

export default function ExtractPage() {
  const { form, setForm, currentId, setCurrentId, selectedClient, setSelectedClient, ledgers, setLedgers, reviewConfirmed, setReviewConfirmed, reviewErrors, setReviewErrors } = useExtract();
  const { editInvoice } = useExtract();
  const { user, getAuthHeaders } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const toast = useToast();
  const [extracting, setExtracting] = useState(false);
  const [isBusy, setIsBusy] = useState(false);
  const [showUndoConfirm, setShowUndoConfirm] = useState(false);
  const [validated, setValidated] = useState(false);
  const [errors, setErrors] = useState({});
  const [success, setSuccess] = useState(false);
  const [validation, setValidation] = useState(null);
  const [dupWarning, setDupWarning] = useState(null);
  const [clients, setClients] = useState([]);
  const [showValModal, setShowValModal] = useState(false);
  const [valModalData, setValModalData] = useState(null);
  const [tallyLedgers, setTallyLedgers] = useState([]);
  const [queue, setQueue] = useState([]);
  const [queueIdx, setQueueIdx] = useState(-1);
  const [batchInvoiceIds, setBatchInvoiceIds] = useState([]);
  const abortRef = useRef(null);
  const imageUrl = currentId != null ? `${BACKEND}/invoices/${currentId}/image` : null;

  // Day 5: Error recovery state
  const [recoveryInvoice, setRecoveryInvoice] = useState(null);
  const [showManualEntry, setShowManualEntry] = useState(false);
  const [manualForm, setManualForm] = useState({
    vendor_name: "", invoice_number: "", date: "", total_amount: "",
    gstin: "", gstin_valid: false,
    taxable_amount: "", cgst: "", sgst: "", igst: "", tax_rate: "",
    voucher_type: "Purchase",
    line_items: [{ description: "", quantity: 1, rate: 0, taxable_value: 0, tax_rate: 0 }],
  });

  function validateGstinFormat(gstin) {
    return /^\d{2}[A-Z]{5}\d{4}[A-Z]\d[Z][A-Z\d]$/.test(gstin);
  }

  function updateManualTaxFromRate() {
    setManualForm((p) => {
      const rate = parseFloat(p.tax_rate) || 0;
      const taxable = parseFloat(p.taxable_amount || p.total_amount) || 0;
      const tax = taxable * rate / 100;
      const isInterstate = false;
      return {
        ...p,
        taxable_amount: taxable ? String(taxable) : p.taxable_amount,
        cgst: isInterstate ? "" : String(tax / 2),
        sgst: isInterstate ? "" : String(tax / 2),
        igst: isInterstate ? String(tax) : "",
      };
    });
  }

  useEffect(() => {
    fetch(`${BACKEND}/clients`, { headers: getAuthHeaders() })
      .then((r) => r.json()).then(setClients).catch(() => {});
    fetch(`${BACKEND}/api/v3/sync/ledgers`, { headers: getAuthHeaders() })
      .then((r) => r.json()).then((d) => setTallyLedgers(d.ledgers || [])).catch(() => {});
  }, []);

  const saveTimer = useRef(null);
  useEffect(() => {
    if (form.line_items?.length > 0 || form.invoice_number) {
      if (saveTimer.current) clearTimeout(saveTimer.current);
      saveTimer.current = setTimeout(() => {
        saveDraft({ form, ledgers, currentId, selectedClient, reviewConfirmed });
      }, 1000);
    }
    return () => { if (saveTimer.current) clearTimeout(saveTimer.current); };
  }, [form, ledgers, currentId, selectedClient, reviewConfirmed]);

  const draftRestored = useRef(false);
  useEffect(() => {
    if (draftRestored.current) return;
    const draft = loadDraft();
    if (draft && draft.form?.line_items?.length > 0) {
      const age = Date.now() - (draft._saved || 0);
      if (age < 86400000 && window.confirm(`You have an unsaved draft from ${Math.round(age / 60000)}m ago. Restore it?`)) {
        setForm(draft.form);
        setLedgers(draft.ledgers || []);
        if (draft.currentId) setCurrentId(draft.currentId);
        if (draft.selectedClient) setSelectedClient(draft.selectedClient);
        if (draft.reviewConfirmed) setReviewConfirmed(true);
      } else {
        clearDraft();
      }
    }
    draftRestored.current = true;
  }, []);

  useEffect(() => {
    const params = new URLSearchParams(location.search);
    const editId = params.get("id");
    if (!editId) return;
    clearDraft();
    editInvoice(editId);
  }, [location.search, editInvoice]);

  const companyGstin = user?.company_gstin || "";
  const companyName = user?.company_name || "";
  const showForm = form.line_items?.length > 0 || success;

  function doValidate() {
    const e = {};
    if (form.gstin && !/^\d{2}[A-Z]{5}\d{4}[A-Z]{1}\d[Z]{1}[A-Z\d]{1}$/.test(form.gstin)) e.gstin = "Invalid format";
    if (!form.invoice_number) e.invoice_number = "Required";
    if (!form.date) e.date = "Required";
    else if (!/^\d{4}-\d{2}-\d{2}$/.test(form.date) || isNaN(Date.parse(form.date))) e.date = "Use YYYY-MM-DD";
    const amt = parseFloat(form.total_amount);
    if (isNaN(amt) || amt <= 0) e.total_amount = "Must be positive";
    if (!form.vendor_name) e.vendor_name = "Required";
    if (form.line_items.length === 0) e.line_items = "At least one item";
    form.line_items.forEach((item, i) => {
      if (!item.description) e[`li_${i}_desc`] = `Item ${i+1}: description required`;
      if (isNaN(parseFloat(item.quantity)) || parseFloat(item.quantity) <= 0) e[`li_${i}_qty`] = `Item ${i+1}: positive qty`;
      if (isNaN(parseFloat(item.taxable_value)) || parseFloat(item.taxable_value) < 0) e[`li_${i}_tv`] = `Item ${i+1}: valid value`;
    });
    setErrors(e);
    if (Object.keys(e).length === 0) setValidated(true);
    return Object.keys(e).length === 0;
  }

  async function downloadXML(force = false) {
    if (!force) { const valid = doValidate(); if (!valid && !window.confirm("Generate XML anyway?")) return; }
    try {
      const payload = {
        ...form, total_amount: parseFloat(form.total_amount),
        buyer_gstin: form.buyer_gstin || companyGstin || "",
        buyer_name: form.buyer_name || companyName || "",
        client_id: parseInt(selectedClient) || null,
        line_items: form.line_items.map((item) => ({
          ...item, quantity: parseFloat(item.quantity), rate: parseFloat(item.rate || 0),
          taxable_value: parseFloat(item.taxable_value), tax_rate: parseFloat(item.tax_rate || 0),
          cgst: item.cgst != null ? parseFloat(item.cgst) : null,
          sgst: item.sgst != null ? parseFloat(item.sgst) : null,
          igst: item.igst != null ? parseFloat(item.igst) : null,
        })),
      };
      const url = currentId != null
        ? `${BACKEND}/generate-xml/${currentId}?force=${force}`
        : `${BACKEND}/generate-xml?force=${force}`;
      const res = await fetch(url, {
        method: "POST", headers: { "Content-Type": "application/json", ...getAuthHeaders() },
        body: JSON.stringify(payload),
      });
      if (res.status === 422) {
        const body = await res.json().catch(() => ({}));
        setValModalData({
          blocking: body.blocking_errors || [],
          soft: body.soft_errors || [],
          warnings: body.warnings || [],
          message: body.message || "Validation produced warnings",
        });
        setShowValModal(true);
        return;
      }
      if (!res.ok) throw new Error(await res.text());
      const blob = await res.blob();
      const url2 = URL.createObjectURL(blob);
      const a = document.createElement("a"); a.href = url2; a.download = `voucher_${form.invoice_number || "output"}.xml`; a.click();
      URL.revokeObjectURL(url2);
    } catch (e) { setErrors({ _general: "XML generation failed: " + e.message }); }
  }

  async function doReviewConfirm() {
    setReviewErrors(null);
    const payload = {
      ...form, total_amount: parseFloat(form.total_amount),
      buyer_gstin: form.buyer_gstin || companyGstin || "",
      buyer_name: form.buyer_name || companyName || "",
      client_id: parseInt(selectedClient) || null,
      freight: form.freight != null ? parseFloat(form.freight) : 0,
      round_off: form.round_off != null ? parseFloat(form.round_off) : 0,
      tds_amount: form.tds_amount != null ? parseFloat(form.tds_amount) : 0,
      line_items: form.line_items.map((item, idx) => ({
        description: item.description, quantity: parseFloat(item.quantity),
        rate: parseFloat(item.rate || 0), taxable_value: parseFloat(item.taxable_value),
        tax_rate: parseFloat(item.tax_rate || 0),
        ledger_name: ledgers[idx] || "",
      })),
      item_ledgers: ledgers,
    };
    try {
      setIsBusy(true);
      const res = await queuedFetch(`/api/v3/invoices/${currentId}/confirm-review`, {
        method: "POST", headers: { "Content-Type": "application/json", ...getAuthHeaders() },
        body: JSON.stringify(payload),
      });
      const body = await res.json().catch(() => ({}));
      if (res.ok) {
        setReviewConfirmed(true);
        setValidated(true);
        setReviewErrors(null);
        clearDraft();
        toast.success("Review confirmed — ready to download XML");
      } else {
        setReviewErrors(body.errors || [body.message || "Review confirmation failed"]);
      }
    } catch (e) {
      setReviewErrors([e.queued ? "Saved offline — will sync when reconnected." : "Review failed: " + e.message]);
    } finally {
      setIsBusy(false);
    }
  }

  async function undoReview() {
    if (!currentId) return;
    try {
      setIsBusy(true);
      const res = await queuedFetch(`/invoices/${currentId}/undo`, {
        method: "POST", headers: getAuthHeaders(),
      });
      const body = await res.json().catch(() => ({}));
      if (res.ok) {
        setReviewConfirmed(false);
        setValidated(false);
        toast.success("Review undone — back to draft");
      } else {
        toast.error(body.message || "Undo failed");
      }
    } catch (e) {
      toast.error("Undo error: " + e.message);
    } finally {
      setIsBusy(false);
      setShowUndoConfirm(false);
    }
  }

  function resetForm() {
    setForm({ gstin: "", invoice_number: "", date: "", total_amount: "", vendor_name: "", vendor_address: "", buyer_gstin: "", buyer_name: "", voucher_type: "Purchase", confidence: null, ind_confidence: null, line_items: [], _provider: "", _model: "" });
    setValidated(false); setErrors({}); setSuccess(false); setCurrentId(null); setValidation(null); setDupWarning(null);
    setSelectedClient("");
    setLedgers([]);
    setReviewConfirmed(false);
    setReviewErrors(null);
  }

  // Day 5: Retry failed extraction
  async function retryExtraction(invQueueEntry) {
    if (!currentId) return;
    setQueue((q) => {
      const n = [...q];
      const idx = n.findIndex(e => e.name === invQueueEntry.name);
      if (idx >= 0) n[idx] = { ...n[idx], status: "processing", error: null };
      return n;
    });
    try {
      const res = await fetch(`${BACKEND}/api/v3/invoices/${currentId}/retry-extraction`, {
        method: "POST", headers: getAuthHeaders(),
      });
      if (res.ok) {
        toast.success("Re-queued for extraction");
        pollExtractionStatus(currentId);
      } else {
        const body = await res.json().catch(() => ({}));
        toast.error(body.message || "Retry failed");
        setQueue((q) => {
          const n = [...q];
          const idx = n.findIndex(e => e.name === invQueueEntry.name);
          if (idx >= 0) n[idx] = { ...n[idx], status: "failed", error: body.message || "Retry failed" };
          return n;
        });
      }
    } catch (e) {
      toast.error("Retry error: " + e.message);
    }
  }

  // Day 5: Manual entry for failed extraction
  async function submitManualEntry() {
    if (!currentId) return;
    const taxable = parseFloat(manualForm.taxable_amount || manualForm.total_amount) || 0;
    const cgst = parseFloat(manualForm.cgst) || 0;
    const sgst = parseFloat(manualForm.sgst) || 0;
    const igst = parseFloat(manualForm.igst) || 0;

    const items = manualForm.line_items.map((li) => ({
      ...li,
      quantity: parseFloat(li.quantity) || 1,
      rate: parseFloat(li.rate) || 0,
      taxable_value: parseFloat(li.taxable_value) || taxable,
      tax_rate: parseFloat(li.tax_rate || manualForm.tax_rate) || 0,
      cgst: cgst, sgst: sgst, igst: igst,
    }));

    const payload = {
      ...manualForm,
      total_amount: parseFloat(manualForm.total_amount) || 0,
      taxable_amount: taxable,
      cgst, sgst, igst,
      line_items: items,
    };

    try {
      const res = await fetch(`${BACKEND}/api/v3/invoices/${currentId}/manual-entry`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...getAuthHeaders() },
        body: JSON.stringify(payload),
      });
      if (res.ok) {
        toast.success("Data saved manually — invoice is now in draft");
        setShowManualEntry(false);
        setSuccess(true);
        setForm({
          vendor_name: manualForm.vendor_name, invoice_number: manualForm.invoice_number,
          date: manualForm.date, total_amount: manualForm.total_amount,
          gstin: manualForm.gstin, voucher_type: manualForm.voucher_type,
          confidence: 1.0, ind_confidence: 1.0, line_items: items,
        });
        setLedgers(items.map(() => ""));
        setQueue((q) => {
          const n = [...q];
          const idx = n.findIndex(e => e.status === "failed");
          if (idx >= 0) n[idx] = { ...n[idx], status: "done" };
          return n;
        });
      } else {
        const body = await res.json().catch(() => ({}));
        toast.error(body.message || "Manual entry failed");
      }
    } catch (e) {
      toast.error("Manual entry error: " + e.message);
    }
  }

  // Day 4: Poll extraction status with adaptive backoff
  async function pollExtractionStatus(invoiceObjId) {
    let pollCount = 0;
    const poll = async (resolve, reject) => {
      if (abortRef.current?.signal.aborted) { reject(new Error("Cancelled")); return; }
      pollCount++;
      try {
        const pr = await fetch(`${BACKEND}/extract/status/${invoiceObjId}`, { headers: getAuthHeaders() });
        const ps = await pr.json();
        if (ps.processing_state === "completed" || ps.status === "draft" || ps.status === "validated") {
          if (ps.display_id) {
            const ir = await fetch(`${BACKEND}/invoices/${ps.display_id}`, { headers: getAuthHeaders() });
            if (ir.ok) {
              const inv = await ir.json();
              const ext = inv.extracted || {};
              const items = Array.isArray(ext.line_items) ? ext.line_items : [];
              setCurrentId(ps.display_id);
              setForm({
                gstin: ext.gstin || "", invoice_number: ext.invoice_number || "", date: ext.date || "",
                total_amount: ext.total_amount != null ? String(ext.total_amount) : "",
                vendor_name: ext.vendor_name || "", vendor_address: ext.vendor_address || "",
                buyer_gstin: ext.buyer_gstin || companyGstin || "", buyer_name: ext.buyer_name || companyName || "",
                voucher_type: ext.voucher_type || "Purchase", confidence: ext.confidence ?? null,
                ind_confidence: ext._independent_confidence ?? null,
                line_items: items, _provider: ext._provider || "", _model: ext._model || "",
                freight: ext.freight || 0, round_off: ext.round_off || 0, tds_amount: ext.tds_amount || 0,
              });
              setLedgers(items.map(() => ""));
              setReviewConfirmed(false);
              setReviewErrors(null);
              setValidation(inv.validation || ext.validation || null);
              if (inv.extracted?._duplicate_warning) setDupWarning(inv.extracted._duplicate_warning);
              setSuccess(true);
              resolve(); return;
            }
          }
          setCurrentId(invoiceObjId);
          setSuccess(true);
          resolve();
        } else if (ps.processing_state?.startsWith("failed") || ps.status === "extraction_failed") {
          reject(new Error(ps.processing_state || "Extraction failed"));
        } else if (pollCount > 60) {
          reject(new Error("Extraction timed out after 2 minutes"));
        } else {
          const isActive = ps.processing_state === "processing";
          const delay = isActive ? 3000 : 8000;
          setTimeout(() => poll(resolve, reject), delay);
        }
      } catch (e) {
        if (e.name !== "AbortError") setTimeout(() => poll(resolve, reject), 8000);
        else reject(e);
      }
    };
    return new Promise((resolve, reject) => poll(resolve, reject));
  }

  // Day 3+4: Enhanced queue processing with better status tracking
  const processOne = useCallback(async (file, idx) => {
    const fd = new FormData();
    fd.append("file", file);
    const timer = setTimeout(() => { if (abortRef.current) abortRef.current.abort(); }, 120000);
    abortRef.current = new AbortController();
    try {
      const res = await fetch(`${BACKEND}/extract?client_id=${selectedClient}`, {
        method: "POST", body: fd, signal: abortRef.current.signal,
        headers: getAuthHeaders(),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        if (body.error === "company_profile_required") {
          toast.error("Set up your company profile first (Company Name, GSTIN, State) in Settings.");
          setQueue((q) => { const n = [...q]; n[idx] = { ...n[idx], status: "failed", error: "No company profile" }; return n; });
          return;
        }
        if (res.status === 409 && body.duplicate) {
          setCurrentId(body._id || null);
          setQueue((q) => { const n = [...q]; n[idx] = { ...n[idx], status: "duplicate" }; return n; });
          return;
        }
        throw new Error(body.message || body.detail || `HTTP ${res.status}`);
      }
      const body = await res.json();
      if (res.status === 202 && body.invoice_id) {
        setQueue((q) => { const n = [...q]; n[idx] = { ...n[idx], oid: body.invoice_id }; return n; });
        await pollExtractionStatus(body.invoice_id);
        setQueue((q) => { const n = [...q]; n[idx] = { ...n[idx], status: "done" }; return n; });
      } else {
        const d = body;
        setCurrentId(d._id || null);
        const items = Array.isArray(d.line_items) ? d.line_items : [];
        setForm({
          gstin: d.gstin || "", invoice_number: d.invoice_number || "", date: d.date || "",
          total_amount: d.total_amount != null ? String(d.total_amount) : "",
          vendor_name: d.vendor_name || "", vendor_address: d.vendor_address || "",
          buyer_gstin: d.buyer_gstin || companyGstin || "", buyer_name: d.buyer_name || companyName || "",
          voucher_type: d.voucher_type || "Purchase", confidence: d.confidence ?? null, line_items: items,
          _provider: d._provider || "", _model: d._model || "",
        });
        setLedgers(items.map(() => ""));
        setReviewConfirmed(false);
        setReviewErrors(null);
        setValidation(d.validation || null);
        if (d._duplicate_warning) setDupWarning(d._duplicate_warning);
        setSuccess(true);
        setQueue((q) => { const n = [...q]; n[idx] = { ...n[idx], status: "done", data: d }; return n; });
      }
    } catch (e) {
      if (e.name !== "AbortError") {
        setQueue((q) => { const n = [...q]; n[idx] = { ...n[idx], status: "failed", error: e.message }; return n; });
      }
    } finally { clearTimeout(timer); }
  }, [selectedClient, setForm, setCurrentId, companyGstin, companyName, getAuthHeaders]);

  const handleUpload = useCallback(async (files) => {
    if (!selectedClient) { toast.warning("Select a client first"); return; }
    const fileList = Array.isArray(files) ? files : [files];
    setValidated(false); setErrors({}); setSuccess(false); setValidation(null); setDupWarning(null);

    const entries = fileList.map((f) => ({
      name: f.name,
      file: f,
      status: "pending",
      error: null,
      data: null,
    }));
    setQueue(entries);
    setQueueIdx(0);
    setExtracting(true);

    for (let i = 0; i < fileList.length; i++) {
      setQueueIdx(i);
      setQueue((q) => { const n = [...q]; n[i] = { ...n[i], status: "processing" }; return n; });
      await processOne(fileList[i], i);
    }
    setQueueIdx(-1);
    setExtracting(false);
    setBatchInvoiceIds((prev) => {
      const ids = entries.filter((e) => e.oid).map((e) => e.oid);
      return [...new Set([...prev, ...ids])];
    });
  }, [selectedClient, processOne]);

  const queueDone = queue.filter((e) => e.status === "done").length;
  const queueFail = queue.filter((e) => e.status === "failed").length;
  const queueTotal = queue.length;
  const showQueue = queueTotal > 0 && (extracting || queueFail > 0 || queueDone < queueTotal);
  const queueProgressPct = queueTotal > 0 ? Math.round(((queueDone + queueFail) / queueTotal) * 100) : 0;

  return (
    <div className="space-y-5 animate-fadeInUp">
      {/* Client Selector */}
      <div className="premium-card" style={{ display: "flex", alignItems: "center", gap: "12px", padding: "12px 16px" }}>
        <span className="premium-section-label" style={{ margin: 0, whiteSpace: "nowrap" }}>Client:</span>
        <select className="premium-input" value={selectedClient} onChange={(e) => setSelectedClient(e.target.value)}>
          <option value="">-- Select a client --</option>
          {clients.map((c) => (
            <option key={c.client_id} value={c.client_id}>{c.company_name} ({c.client_name})</option>
          ))}
        </select>
        {clients.length === 0 && <span className="premium-badge premium-badge-warning" style={{ whiteSpace: "nowrap" }}>Add clients first</span>}
      </div>

      {/* Upload Panel */}
      {!showForm && (
        <div className="space-y-3">
          <UploadPanel
            onUpload={handleUpload}
            extracting={extracting}
            extractionStatus={null}
          />
          <div className="flex items-center gap-3">
            <div className="flex-1 h-px bg-white/10" />
            <span className="text-xs text-gray-500">or</span>
            <div className="flex-1 h-px bg-white/10" />
          </div>
          <button
            onClick={() => {
              resetForm();
              setShowForm(true);
            }}
            className="w-full premium-btn-secondary text-sm py-2"
          >
            Enter Invoice Manually
          </button>
        </div>
      )}

      {/* Day 3: Enhanced Queue Progress with status chips + progress bar */}
      {showQueue && (
        <div className="premium-card p-4 space-y-3">
          <div className="flex justify-between items-center">
            <span className="text-sm font-medium text-gray-300">
              {extracting ? `Processing ${queueIdx + 1}/${queueTotal}` : "Batch complete"}
            </span>
            <div className="flex items-center gap-3 text-xs">
              <span className="text-green-400">{queueDone} done</span>
              {queueFail > 0 && <span className="text-red-400">{queueFail} failed</span>}
              <span className="text-gray-500">{queueProgressPct}%</span>
            </div>
          </div>

          {/* Progress bar */}
          <div className="w-full bg-gray-700 rounded-full h-2 overflow-hidden">
            <div
              className={`h-full rounded-full transition-all duration-500 ${queueFail > 0 ? "bg-gradient-to-r from-green-500 to-red-500" : "bg-gradient-to-r from-indigo-500 to-green-500"}`}
              style={{ width: `${queueProgressPct}%` }}
            />
          </div>

          {/* Day 3: Per-file status list with chips + retry */}
          <div className="max-h-48 overflow-y-auto space-y-1.5">
            {queue.map((e, i) => (
              <div key={i} className="flex items-center gap-2 py-1 px-2 rounded-lg hover:bg-white/[0.02]">
                <QueueStatusChip status={e.status} error={e.error} />
                <span className="text-xs text-gray-400 truncate flex-1">{e.name}</span>
                {e.error && <span className="text-[10px] text-red-400/70 truncate max-w-[140px]" title={e.error}>{e.error}</span>}
                {/* Day 5: Retry button for failed items */}
                {e.status === "failed" && e.file && (
                  <button onClick={() => retryExtraction(e)}
                    className="text-[10px] text-blue-400 hover:text-blue-300 shrink-0 px-1.5 py-0.5 rounded bg-blue-500/10 hover:bg-blue-500/20 transition-colors">
                    Retry
                  </button>
                )}
                {e.status === "failed" && !e.file && (
                  <button onClick={() => { setRecoveryInvoice(e); setShowManualEntry(true); }}
                    className="text-[10px] text-amber-400 hover:text-amber-300 shrink-0 px-1.5 py-0.5 rounded bg-amber-500/10 hover:bg-amber-500/20 transition-colors">
                    Enter Manually
                  </button>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Batch Review Grid — shown after batch completes with multiple files */}
      {!extracting && batchInvoiceIds.length > 1 && !showForm && (
        <BatchReviewGrid
          invoiceIds={batchInvoiceIds}
          onRefresh={() => setQueue([])}
          onReviewInvoice={(displayId) => {
            setCurrentId(displayId);
            setQueue([]);
            setBatchInvoiceIds([]);
            setSuccess(true);
          }}
        />
      )}

      {/* Error / Duplicate Warnings */}
      {errors._general && (
        <div className="premium-alert premium-alert-error animate-fadeInUp">
          <span>{'\u26A0'}</span>
          <span>{errors._general}</span>
        </div>
      )}
      {dupWarning && (
        <div className="premium-alert premium-alert-warning animate-fadeInUp">
          <span>{'\u26A0'}</span>
          <span>{typeof dupWarning === "string" ? dupWarning : dupWarning.message}</span>
        </div>
      )}

      {/* Review Panel */}
      {showForm && (
        <ReviewPanel
          form={form}
          setForm={setForm}
          ledgers={ledgers}
          setLedgers={setLedgers}
          errors={errors}
          reviewConfirmed={reviewConfirmed}
          reviewErrors={reviewErrors}
          currentId={currentId}
          imageUrl={imageUrl}
          tallyLedgers={tallyLedgers}
          validation={validation}
          getAuthHeaders={getAuthHeaders}
          companyGstin={companyGstin}
          companyName={companyName}
          onReviewConfirm={doReviewConfirm}
          onDownloadXML={() => downloadXML()}
          onPreviewMasters={() => {}}
          onUndo={() => setShowUndoConfirm(true)}
          onReset={resetForm}
          submitting={isBusy}
        />
      )}

      {showUndoConfirm && (
        <ConfirmDialog
          title="Undo review?"
          message="This invoice will go back to draft status. You can review it again anytime."
          confirmLabel="Undo Review"
          onConfirm={undoReview}
          onCancel={() => setShowUndoConfirm(false)}
        />
      )}

      {/* Day 5: Enhanced Manual Entry Modal */}
      <ManualEntryModal
        show={showManualEntry}
        onClose={() => setShowManualEntry(false)}
        manualForm={manualForm}
        setManualForm={setManualForm}
        onSubmit={submitManualEntry}
      />

      <ValidationModal show={showValModal} data={valModalData}
        onGenerateAnyway={() => { setShowValModal(false); downloadXML(true); }}
        onClose={() => setShowValModal(false)}
        onApplyFix={(fix) => {
          if (fix.fix_type === "set_field") {
            setForm((f) => ({ ...f, [fix.fix_payload.field]: fix.fix_payload.value }));
          } else if (fix.fix_type === "correct_gstin") {
            setForm((f) => ({ ...f, gstin: fix.fix_payload.suggestion }));
          }
          setShowValModal(false);
        }}
        onFixAll={() => {
          const fixes = valModalData?.fix_suggestions || [];
          let updates = {};
          for (const f of fixes) {
            if (f.fix_type === "set_field") {
              updates[f.fix_payload.field] = f.fix_payload.value;
            } else if (f.fix_type === "correct_gstin") {
              updates.gstin = f.fix_payload.suggestion;
            }
          }
          if (Object.keys(updates).length > 0) setForm((prev) => ({ ...prev, ...updates }));
          setShowValModal(false);
        }} />
    </div>
  );
}
