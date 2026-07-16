import { useState, useCallback, useEffect, useRef } from "react";
import { useAuth } from "../auth";
import BACKEND from "../api/client";
import { queuedFetch } from "../api/queue";
import UploadPanel from "../components/UploadPanel";
import ReviewPanel from "../components/ReviewPanel";
import ValidationModal from "../components/ValidationModal";

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

export default function ExtractPage({ form, setForm, currentId, setCurrentId, selectedClient, setSelectedClient, ledgers, setLedgers, reviewConfirmed, setReviewConfirmed, reviewErrors, setReviewErrors }) {
  const { user, getAuthHeaders } = useAuth();
  const [extracting, setExtracting] = useState(false);
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
  const abortRef = useRef(null);
  const imageUrl = currentId != null ? `${BACKEND}/invoices/${currentId}/image` : null;

  useEffect(() => {
    fetch(`${BACKEND}/clients`, { headers: getAuthHeaders() })
      .then((r) => r.json()).then(setClients).catch(() => {});
    fetch(`${BACKEND}/api/v3/sync/ledgers`, { headers: getAuthHeaders() })
      .then((r) => r.json()).then((d) => setTallyLedgers(d.ledgers || [])).catch(() => {});
  }, []);

  // Auto-save draft on form changes
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

  // Restore draft on mount
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
      } else {
        setReviewErrors(body.errors || [body.message || "Review confirmation failed"]);
      }
    } catch (e) {
      setReviewErrors([e.queued ? "Saved offline — will sync when reconnected." : "Review failed: " + e.message]);
    }
  }

  async function undoReview() {
    if (!currentId) return;
    if (!window.confirm("Undo review? Invoice will go back to draft status.")) return;
    try {
      const res = await queuedFetch(`/invoices/${currentId}/undo`, {
        method: "POST", headers: getAuthHeaders(),
      });
      const body = await res.json().catch(() => ({}));
      if (res.ok) {
        setReviewConfirmed(false);
        setValidated(false);
      } else {
        alert(body.message || "Undo failed");
      }
    } catch (e) {
      alert("Undo error: " + e.message);
    }
  }

  function resetForm() {
    setForm({ gstin: "", invoice_number: "", date: "", total_amount: "", vendor_name: "", vendor_address: "", buyer_gstin: "", buyer_name: "", voucher_type: "Purchase", confidence: null, line_items: [], _provider: "", _model: "" });
    setValidated(false); setErrors({}); setSuccess(false); setCurrentId(null); setValidation(null); setDupWarning(null);
    setSelectedClient("");
    setLedgers([]);
    setReviewConfirmed(false);
    setReviewErrors(null);
  }

  // ── Queue-based batch upload ──
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
          alert("Set up your company profile first (Company Name, GSTIN, State) in Settings.");
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
        let pollCount = 0;
        const poll = async (resolve, reject) => {
          if (abortRef.current?.signal.aborted) { reject(new Error("Cancelled")); return; }
          pollCount++;
          try {
            const pr = await fetch(`${BACKEND}/extract/status/${body.invoice_id}`, { headers: getAuthHeaders() });
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
                    line_items: items, _provider: ext._provider || "", _model: ext._model || "",
                    freight: ext.freight || 0, round_off: ext.round_off || 0, tds_amount: ext.tds_amount || 0,
                  });
                  setLedgers(items.map(() => ""));
                  setReviewConfirmed(false);
                  setReviewErrors(null);
                  setValidation(inv.validation || ext.validation || null);
                  if (inv.extracted?._duplicate_warning) setDupWarning(inv.extracted._duplicate_warning);
                  setSuccess(true);
                  setQueue((q) => { const n = [...q]; n[idx] = { ...n[idx], status: "done", data: ext }; return n; });
                  resolve(); return;
                }
              }
              setCurrentId(body.invoice_id);
              setSuccess(true);
              setQueue((q) => { const n = [...q]; n[idx] = { ...n[idx], status: "done" }; return n; });
              resolve();
            } else if (ps.processing_state?.startsWith("failed") || ps.status === "extraction_failed") {
              setQueue((q) => { const n = [...q]; n[idx] = { ...n[idx], status: "failed", error: ps.processing_state }; return n; });
              reject(new Error(ps.processing_state || "Extraction failed"));
            } else if (pollCount > 60) {
              setQueue((q) => { const n = [...q]; n[idx] = { ...n[idx], status: "failed", error: "Timed out" }; return n; });
              reject(new Error("Extraction timed out after 2 minutes"));
            } else {
              setTimeout(() => poll(resolve, reject), 2000);
            }
          } catch (e) {
            if (e.name !== "AbortError") setTimeout(() => poll(resolve, reject), 2000);
            else reject(e);
          }
        };
        await new Promise((resolve, reject) => poll(resolve, reject));
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
    if (!selectedClient) { alert("Select a client first"); return; }
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
  }, [selectedClient, processOne]);

  const queueDone = queue.filter((e) => e.status === "done").length;
  const queueFail = queue.filter((e) => e.status === "failed").length;
  const showQueue = queue.length > 0 && (extracting || queueFail > 0 || queueDone < queue.length);

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
        <UploadPanel
          onUpload={handleUpload}
          extracting={extracting}
          extractionStatus={null}
        />
      )}

      {/* Queue Progress */}
      {showQueue && (
        <div className="premium-card p-4 space-y-2">
          <div className="flex justify-between items-center">
            <span className="text-sm font-medium text-gray-300">
              Processing {queueIdx + 1}/{queue.length}
            </span>
            <span className="text-xs text-gray-500">
              {queueDone} done, {queueFail} failed
            </span>
          </div>
          <div className="w-full bg-gray-700 rounded-full h-1.5">
            <div className="bg-indigo-500 h-1.5 rounded-full transition-all duration-300" style={{ width: `${((queueIdx + 1) / queue.length) * 100}%` }} />
          </div>
          <div className="max-h-32 overflow-y-auto space-y-1">
            {queue.map((e, i) => (
              <div key={i} className="flex items-center gap-2 text-xs">
                <span className={
                  e.status === "done" ? "text-green-400" :
                  e.status === "failed" ? "text-red-400" :
                  e.status === "processing" ? "text-yellow-400" :
                  "text-gray-500"
                }>
                  {e.status === "done" ? "\u2713" : e.status === "failed" ? "\u2717" : e.status === "processing" ? "\u25B6" : "\u25CB"}
                </span>
                <span className="truncate flex-1 text-gray-400">{e.name}</span>
                {e.error && <span className="text-red-400 truncate max-w-[100px]">{e.error}</span>}
                {e.status === "failed" && e.file && (
                  <button onClick={async () => {
                    setQueue((q) => { const n = [...q]; n[i] = { ...n[i], status: "processing", error: null }; return n; });
                    await processOne(e.file, i);
                  }} className="text-blue-400 hover:text-blue-300 shrink-0 ml-1">Retry</button>
                )}
              </div>
            ))}
          </div>
        </div>
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
          onUndo={undoReview}
          onReset={resetForm}
        />
      )}

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
