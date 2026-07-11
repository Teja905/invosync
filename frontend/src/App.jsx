import React, { useState, useCallback, useEffect, useRef } from "react";
import { useDropzone } from "react-dropzone";
import { useAuth } from "./auth";
import gsap from "gsap";

const BACKEND = import.meta.env.VITE_API_URL || "";

const COMMON_LEDGERS = [
  "Purchase", "Sales", "Purchase Accounts", "Sales Accounts",
  "Professional Charges", "Office Expenses", "Rent Expenses",
  "Electricity Expenses", "Telephone Expenses", "Travel Expenses",
  "Food Expenses", "Fixed Assets", "Freight Expenses", "Bank Charges",
  "Interest Expenses", "Insurance Expenses", "Repairs & Maintenance",
  "Salary Expenses", "Software Expenses", "Legal Expenses",
  "Audit Expenses", "Advertisement Expenses", "Commission Expenses",
  "Printing & Stationery", "Postage & Courier", "Carriage Inwards",
  "Carriage Outwards", "Packing Expenses", "Labour Charges",
  "Job Work Charges", "Consulting Fees", "Management Fees",
  "Royalty Expenses", "Training Expenses", "Recruitment Expenses",
  "Membership & Subscription", "Donations", "Charity Expenses",
  "Miscellaneous Expenses", "Suspense", "Round Off",
  "TDS Payable", "GST Input CGST", "GST Input SGST", "GST Input IGST",
  "GST Output CGST", "GST Output SGST", "GST Output IGST",
  "TCS Payable", "Wages Payable", "Salary Payable",
  "Interest Payable", "Rent Payable", "Electricity Payable",
  "Outstanding Expenses", "Prepaid Expenses",
  "Capital Account", "Drawings", "Bank OD", "Cash in Hand",
  "Bank (HDFC)", "Bank (ICICI)", "Bank (SBI)", "Bank (Axis)",
  "Loans & Advances", "Security Deposits", "Advances to Suppliers",
  "Sundry Debtors", "Sundry Creditors",
  "Stock-in-Hand", "Opening Stock", "Closing Stock",
  "Purchase Returns", "Sales Returns", "Discount Allowed",
  "Discount Received", "Bad Debts", "Provision for Bad Debts",
  "Investments", "Interest Income", "Other Income",
  "Dividend Income", "Rent Income", "Commission Income",
];

function safeJson(r) {
  if (!r.ok) return Promise.reject(new Error(r.status + " " + r.statusText));
  return r.json().catch(() => ({}));
}

function Field({ label, error, children, optional }) {
  return (
    <div>
      <label className="gh-label">
        {label}
        {optional && <span className="gh-label-optional">(optional)</span>}
      </label>
      {children}
      {error && <p className="gh-error"><span>&#9888;</span>{error}</p>}
    </div>
  );
}

function NavBar({ active, onChange, tallyStatus }) {
  const tabs = [
    { key: "extract", label: "Extract" },
    { key: "clients", label: "Clients" },
    { key: "dashboard", label: "Dashboard" },
    { key: "settings", label: "Settings" },
  ];

  function dotColor() {
    if (!tallyStatus) return "grey";
    if (tallyStatus.connector_online && tallyStatus.tally_reachable) return "green";
    if (tallyStatus.connector_online && !tallyStatus.tally_reachable) return "yellow";
    return "red";
  }

  function statusText() {
    if (!tallyStatus) return "Connecting...";
    if (tallyStatus.connector_online && tallyStatus.tally_reachable)
      return `Tally: ${tallyStatus.company || "Connected"}`;
    if (tallyStatus.connector_online && !tallyStatus.tally_reachable)
      return "Tally not detected — open Tally Prime (F1 → Settings → Connectivity → Port 9000)";
    return "Connector offline — run InvoSync.exe on this PC";
  }

  return (
    <div className="gh-header">
      <div className="gh-header-inner">
        <div className="gh-logo">
          <div className="gh-logo-icon">I</div>
          <span>InvoSync</span>
        </div>
        <div className="gh-tabs">
          {tabs.map((t) => (
            <button key={t.key} onClick={() => onChange(t.key)}
              className={`gh-tab ${active === t.key ? "active" : ""}`}>
              {t.label}
            </button>
          ))}
        </div>
        <div className="gh-status" title={statusText()}>
          <span className={`gh-status-dot ${dotColor()}`} />
          <span className="gh-status-label">{statusText()}</span>
          <span style={{color:"var(--text-tertiary)", fontSize:"11px", marginLeft:"4px"}}>v3.2</span>
        </div>
      </div>
    </div>
  );
}

// AUTH DISABLED - LoginPage removed

function ClientPage({ refreshKey }) {
  const { getAuthHeaders } = useAuth();
  const [clients, setClients] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [companyName, setCompanyName] = useState("");
  const [clientName, setClientName] = useState("");
  const [gstin, setGstin] = useState("");
  const [editingClient, setEditingClient] = useState(null);
  const [editCompanyName, setEditCompanyName] = useState("");
  const [editClientName, setEditClientName] = useState("");
  const [editGstin, setEditGstin] = useState("");

  useEffect(() => {
    setLoading(true);
    fetch(`${BACKEND}/clients`, { headers: getAuthHeaders() })
      .then((r) => r.json()).then(setClients).catch(() => {}).finally(() => setLoading(false));
  }, [refreshKey]);

  async function addClient() {
    if (!companyName || !clientName) return;
    try {
      const r = await fetch(`${BACKEND}/clients`, {
        method: "POST", headers: { "Content-Type": "application/json", ...getAuthHeaders() },
        body: JSON.stringify({ company_name: companyName, client_name: clientName, gstin }),
      });
      if (!r.ok) { const err = await r.text(); alert("Failed: " + err); return; }
      setCompanyName(""); setClientName(""); setGstin(""); setShowForm(false);
      const res = await fetch(`${BACKEND}/clients`, { headers: getAuthHeaders() });
      if (!res.ok) throw new Error(await res.text());
      setClients(await res.json());
    } catch (e) { alert("Failed: " + e.message); }
  }

  function startEdit(c) {
    setEditingClient(c);
    setEditCompanyName(c.company_name);
    setEditClientName(c.client_name);
    setEditGstin(c.gstin || "");
  }

  function cancelEdit() {
    setEditingClient(null);
    setEditCompanyName(""); setEditClientName(""); setEditGstin("");
  }

  async function saveEdit() {
    if (!editCompanyName || !editClientName || !editingClient) return;
    try {
      await fetch(`${BACKEND}/clients/${editingClient.client_id}`, {
        method: "PUT", headers: { "Content-Type": "application/json", ...getAuthHeaders() },
        body: JSON.stringify({ company_name: editCompanyName, client_name: editClientName, gstin: editGstin }),
      });
      cancelEdit();
      const res = await fetch(`${BACKEND}/clients`, { headers: getAuthHeaders() });
      setClients(await res.json());
    } catch (e) { alert("Failed: " + e.message); }
  }

  async function deleteClient(id) {
    if (!window.confirm("Delete this client and ALL their invoices?")) return;
    try {
      await fetch(`${BACKEND}/clients/${id}`, { method: "DELETE", headers: getAuthHeaders() });
      setClients((prev) => prev.filter((c) => c.client_id !== id));
    } catch (e) { alert("Failed: " + e.message); }
  }

  if (loading) return <div className="text-center py-20"><div className="w-8 h-8 border-2 border-indigo-400 border-t-transparent rounded-full animate-spin mx-auto" /></div>;

  return (
    <div className="space-y-4 animate-fadeIn">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-bold gradient-text">Clients ({clients.length})</h2>
        <button onClick={() => setShowForm(!showForm)} className="btn-primary text-sm px-4 py-2">
          {showForm ? "Cancel" : "+ Add Client"}
        </button>
      </div>

      {showForm && (
        <div className="glass-card p-5 space-y-4 animate-slideUp">
          <h3 className="text-sm font-semibold text-gray-200">New Client</h3>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <div>
              <label className="text-xs text-gray-500 mb-1 block">Company Name *</label>
              <input className="input w-full" value={companyName} onChange={(e) => setCompanyName(e.target.value)} placeholder="e.g. ABC Traders" />
            </div>
            <div>
              <label className="text-xs text-gray-500 mb-1 block">Contact Person *</label>
              <input className="input w-full" value={clientName} onChange={(e) => setClientName(e.target.value)} placeholder="e.g. Rajesh Kumar" />
            </div>
            <div>
              <label className="text-xs text-gray-500 mb-1 block">GSTIN <span className="text-gray-600">(optional)</span></label>
              <input className="input w-full" value={gstin} onChange={(e) => setGstin(e.target.value.toUpperCase())} placeholder="Leave blank if N/A" />
            </div>
          </div>
          <div className="flex justify-end gap-2 pt-2">
            <button onClick={() => setShowForm(false)} className="btn-secondary text-sm px-4 py-2">Cancel</button>
            <button onClick={addClient} className="btn-primary text-sm px-4 py-2">Save Client</button>
          </div>
        </div>
      )}

      {editingClient && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm animate-fadeIn" onClick={cancelEdit}>
          <div className="glass-card p-5 space-y-4 w-full max-w-lg animate-slideUp" onClick={(e) => e.stopPropagation()}>
            <h3 className="text-sm font-semibold text-gray-200">Edit Client</h3>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
              <div>
                <label className="text-xs text-gray-500 mb-1 block">Company Name *</label>
                <input className="input w-full" value={editCompanyName} onChange={(e) => setEditCompanyName(e.target.value)} placeholder="e.g. ABC Traders" />
              </div>
              <div>
                <label className="text-xs text-gray-500 mb-1 block">Contact Person *</label>
                <input className="input w-full" value={editClientName} onChange={(e) => setEditClientName(e.target.value)} placeholder="e.g. Rajesh Kumar" />
              </div>
              <div>
                <label className="text-xs text-gray-500 mb-1 block">GSTIN <span className="text-gray-600">(optional)</span></label>
                <input className="input w-full" value={editGstin} onChange={(e) => setEditGstin(e.target.value.toUpperCase())} placeholder="Leave blank if N/A" />
              </div>
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <button onClick={cancelEdit} className="btn-secondary text-sm px-4 py-2">Cancel</button>
              <button onClick={saveEdit} className="btn-primary text-sm px-4 py-2">Save Changes</button>
            </div>
          </div>
        </div>
      )}

      {clients.length === 0 ? (
        <div className="gh-card" style={{padding:"48px 20px", textAlign:"center"}}>
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" style={{margin:"0 auto 16px", opacity:0.3}}>
            <path d="M3 7V5a2 2 0 012-2h14a2 2 0 012 2v2" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
            <path d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V7" stroke="currentColor" strokeWidth="1.5"/>
            <path d="M3 7h18" stroke="currentColor" strokeWidth="1.5"/>
            <path d="M9 12h6" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
          </svg>
          <p style={{color:"var(--text-secondary)", fontSize:"16px", marginBottom:"4px"}}>No clients yet</p>
          <p style={{color:"var(--text-tertiary)", fontSize:"13px"}}>Add your first client to start processing invoices.</p>
        </div>
      ) : (
        <div className="gh-card">
          <table className="gh-table">
            <thead><tr>
              <th>Company</th>
              <th>Contact</th>
              <th>GSTIN</th>
              <th>Invoices</th>
              <th>Action</th>
            </tr></thead>
            <tbody>
              {clients.map((c) => (
                <tr key={c.client_id} className="table-row">
                  <td>{c.company_name}</td>
                  <td>{c.client_name}</td>
                  <td className="font-mono text-xs">{c.gstin || <span className="text-tertiary">N/A</span>}</td>
                  <td>{c.invoice_count || 0}</td>
                  <td className="flex gap-2">
                    <button onClick={() => startEdit(c)} className="text-xs" style={{color:"var(--accent-blue)"}}>Edit</button>
                    <button onClick={() => deleteClient(c.client_id)} className="text-xs" style={{color:"var(--accent-red)"}}>Delete</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function ExtractPage({ form, setForm, currentId, setCurrentId, selectedClient, setSelectedClient, ledgers, setLedgers, reviewConfirmed, setReviewConfirmed, reviewErrors, setReviewErrors }) {
  const { user, getAuthHeaders } = useAuth();
  const [extracting, setExtracting] = useState(false);
  const [validated, setValidated] = useState(false);
  const [errors, setErrors] = useState({});
  const [success, setSuccess] = useState(false);
  const [validation, setValidation] = useState(null);
  const [dupWarning, setDupWarning] = useState(null);
  const [clients, setClients] = useState([]);
  const [mastersPreview, setMastersPreview] = useState(null);
  const [showWarnings, setShowWarnings] = useState([]);
  const [showPreview, setShowPreview] = useState(false);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [showValModal, setShowValModal] = useState(false);
  const [valModalData, setValModalData] = useState(null);
  const [tallyLedgers, setTallyLedgers] = useState([]);
  const abortRef = useRef(null);
  const imageUrl = currentId != null ? `${BACKEND}/invoices/${currentId}/image` : null;

  useEffect(() => {
    fetch(`${BACKEND}/clients`, { headers: getAuthHeaders() })
      .then((r) => r.json()).then(setClients).catch(() => {});
    fetch(`${BACKEND}/api/v3/sync/ledgers`, { headers: getAuthHeaders() })
      .then((r) => r.json()).then((d) => setTallyLedgers(d.ledgers || [])).catch(() => {});
  }, []);

  const companyGstin = user?.company_gstin || "";
  const companyName = user?.company_name || "";
  const showForm = form.line_items.length > 0 || success;

  const onDrop = useCallback(async (acceptedFiles) => {
    const file = acceptedFiles[0];
    if (!file) return;
    if (!selectedClient) { alert("Select a client first"); return; }
    setExtracting(true); setValidated(false); setErrors({}); setSuccess(false); setValidation(null); setDupWarning(null);
    setCurrentId(null);
    setForm((p) => ({ ...p, line_items: [] }));

    abortRef.current = new AbortController();
    const timer = setTimeout(() => abortRef.current.abort(), 120000);
    const fd = new FormData();
    fd.append("file", file);
    try {
      const res = await fetch(`${BACKEND}/extract?client_id=${selectedClient}`, {
        method: "POST", body: fd, signal: abortRef.current.signal,
        headers: getAuthHeaders(),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        if (body.error === "company_profile_required") {
          alert("Set up your company profile first (Company Name, GSTIN, State) in Settings.");
          return;
        }
        if (res.status === 409 && body.duplicate) {
          setDupWarning(`Duplicate file (existing ID: ${body.existing_id}).`);
          const d = body;
          setCurrentId(d._id || null);
          setForm({ gstin: "", invoice_number: "", date: "", total_amount: "", vendor_name: "", vendor_address: "", buyer_gstin: companyGstin || "", buyer_name: companyName || "", voucher_type: "Purchase", confidence: null, line_items: [], _provider: "", _model: "" });
          setSuccess(true);
          return;
        }
        throw new Error(body.message || body.detail || `HTTP ${res.status}`);
      }

      const body = await res.json();

      // 202 — queued for background extraction; poll until done
      if (res.status === 202 && body.invoice_id) {
        let pollCount = 0;
        const poll = async (resolve, reject) => {
          if (abortRef.current.signal.aborted) { reject(new Error("Cancelled")); return; }
          pollCount++;
          try {
            const pr = await fetch(`${BACKEND}/extract/status/${body.invoice_id}`, { headers: getAuthHeaders() });
            const ps = await pr.json();
            if (ps.processing_state === "completed" || ps.status === "draft" || ps.status === "validated") {
              // Fetch the completed invoice data via display_id or invoice_id
              const fetchId = ps.display_id || body.invoice_id;
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
                  resolve();
                  return;
                }
              }
              // Fallback: no display_id yet, try GET invoice by _id
              setCurrentId(body.invoice_id);
              setSuccess(true);
              resolve();
            } else if (ps.processing_state?.startsWith("failed") || ps.status === "extraction_failed") {
              reject(new Error(ps.processing_state || "Extraction failed"));
            } else if (pollCount > 60) {
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
        // Synchronous response (fallback / no DB)
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
      }
    } catch (e) {
      if (e.name !== "AbortError") setErrors({ _general: "Extraction failed: " + e.message });
    } finally { clearTimeout(timer); setExtracting(false); }
  }, [selectedClient, setForm, setCurrentId, companyGstin, companyName, getAuthHeaders]);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop, accept: { "image/*": [".png", ".jpg", ".jpeg", ".webp"], "application/pdf": [".pdf"] }, maxFiles: 1, disabled: extracting,
  });

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

  async function previewMasters() {
    if (!doValidate()) return;
    setPreviewLoading(true);
    setMastersPreview(null);
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
      const res = await fetch(`${BACKEND}/preview-masters`, {
        method: "POST", headers: { "Content-Type": "application/json", ...getAuthHeaders() },
        body: JSON.stringify(payload),
      });
      if (!res.ok) throw new Error(await res.text());
      const body = await res.json();
      setMastersPreview(body.masters || []);
      setShowWarnings(body.warnings || []);
      setShowPreview(true);
    } catch (e) {
      setErrors({ _general: "Preview failed: " + e.message });
    }
    setPreviewLoading(false);
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
      line_items: form.line_items.map((item) => ({
        description: item.description, quantity: parseFloat(item.quantity),
        rate: parseFloat(item.rate || 0), taxable_value: parseFloat(item.taxable_value),
        tax_rate: parseFloat(item.tax_rate || 0),
      })),
      item_ledgers: ledgers,
    };
    try {
      const res = await fetch(`${BACKEND}/api/v3/invoices/${currentId}/confirm-review`, {
        method: "POST", headers: { "Content-Type": "application/json", ...getAuthHeaders() },
        body: JSON.stringify(payload),
      });
      const body = await res.json().catch(() => ({}));
      if (res.ok) {
        setReviewConfirmed(true);
        setValidated(true);
        setReviewErrors(null);
      } else {
        setReviewErrors(body.errors || [body.message || "Review confirmation failed"]);
      }
    } catch (e) {
      setReviewErrors(["Review failed: " + e.message]);
    }
  }

  function resetForm() {
    setForm({ gstin: "", invoice_number: "", date: "", total_amount: "", vendor_name: "", vendor_address: "", buyer_gstin: "", buyer_name: "", voucher_type: "Purchase", confidence: null, line_items: [], _provider: "", _model: "" });
    setValidated(false); setErrors({}); setSuccess(false); setCurrentId(null); setValidation(null); setDupWarning(null);
    setSelectedClient("");
    setMastersPreview(null);
    setShowPreview(false);
    setShowWarnings([]);
    setLedgers([]);
    setReviewConfirmed(false);
    setReviewErrors(null);
  }

  return (
    <div className="space-y-5 animate-fadeIn">
      <div className="gh-card" style={{display:"flex", alignItems:"center", gap:"12px", padding:"12px 16px"}}>
        <span className="gh-label" style={{margin:0, whiteSpace:"nowrap"}}>Client:</span>
        <select className="gh-input" value={selectedClient} onChange={(e) => setSelectedClient(e.target.value)}>
          <option value="">-- Select a client --</option>
          {clients.map((c) => (
            <option key={c.client_id} value={c.client_id}>{c.company_name} ({c.client_name})</option>
          ))}
        </select>
        {clients.length === 0 && <span className="gh-tag gh-tag-yellow" style={{whiteSpace:"nowrap"}}>Add clients first</span>}
      </div>

      <div {...getRootProps()} className={`gh-dropzone ${isDragActive ? "active" : ""}`}>
        <input {...getInputProps()} />
        {extracting ? (
          <div className="flex flex-col items-center gap-3">
            <div className="w-8 h-8 border-2 border-indigo-400 border-t-transparent rounded-full animate-spin" />
            <p className="text-gray-400">Extracting invoice data...</p>
          </div>
        ) : isDragActive ? (
          <p style={{fontSize:"16px", fontWeight:500, color:"var(--accent-blue)"}}>Drop invoice here</p>
        ) : (
          <div>
            <svg width="48" height="48" viewBox="0 0 24 24" fill="none" style={{margin:"0 auto 16px", opacity:0.4}}>
              <path d="M12 3v12m0 0l-3-3m3 3l3-3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
              <path d="M4 17v2a2 2 0 002 2h12a2 2 0 002-2v-2" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
              <rect x="3" y="15" width="18" height="2" rx="1" fill="currentColor" opacity="0.1"/>
            </svg>
            <p style={{color:"var(--text-secondary)", fontSize:"14px", fontWeight:500}}>Drop invoice image or PDF here</p>
            <p style={{color:"var(--text-tertiary)", fontSize:"12px", marginTop:"4px"}}>or click to browse &bull; PNG, JPG, WebP, PDF</p>
          </div>
        )}
      </div>

      {errors._general && (
        <div className="gh-alert gh-alert-error animate-fadeIn">
          <span>&#9888;</span>
          <span>{errors._general}</span>
        </div>
      )}

      {dupWarning && (
        <div className="gh-alert gh-alert-warning animate-fadeIn">
          <span>&#9888;</span>
          <span>{typeof dupWarning === "string" ? dupWarning : dupWarning.message}</span>
        </div>
      )}

      {validation && <ValidationSummary validation={validation} />}

      {showForm && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 animate-slideUp" style={{ animationDelay: "0.1s" }}>
          <div className="space-y-4">
            <div className="gh-card" style={{padding:"16px"}}>
              <h3 className="text-xs font-medium uppercase tracking-wider mb-3" style={{color:"var(--text-secondary)", letterSpacing:"0.5px"}}>Invoice Document</h3>
              {imageUrl ? (
                <div className="rounded-lg overflow-hidden bg-black/20">
                  <img src={imageUrl} alt="Invoice" className="w-full h-auto object-contain max-h-[600px]" onError={(e) => { e.target.style.display = "none"; e.target.nextSibling.style.display = "flex"; }} />
                  <div className="hidden items-center justify-center h-48 text-gray-500 text-sm"><span>Image not available</span></div>
                </div>
              ) : (
                <div style={{display:"flex", alignItems:"center", justifyContent:"center", height:"192px", background:"var(--bg-primary)", borderRadius:"6px", border:"1px dashed var(--border-primary)"}}>
                  <div style={{textAlign:"center"}}>
                    <svg width="32" height="32" viewBox="0 0 24 24" fill="none" style={{margin:"0 auto 8px", opacity:0.3}}>
                      <rect x="3" y="3" width="18" height="18" rx="2" stroke="currentColor" strokeWidth="1.5"/>
                      <circle cx="8.5" cy="8.5" r="1.5" fill="currentColor" opacity="0.5"/>
                      <path d="M3 16l4-4 3 3 5-5 6 6" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
                    </svg>
                    <p style={{fontSize:"13px", color:"var(--text-tertiary)"}}>Invoice preview</p>
                    <p style={{fontSize:"11px", color:"var(--text-tertiary)", opacity:0.6}}>shown after extraction</p>
                  </div>
                </div>
              )}
            </div>
            {form.confidence != null && (
              <div className="glass-card p-4">
                <div className="flex items-center gap-2 text-sm">
                  <span className="text-gray-400">AI Confidence:</span>
                  <div className="flex-1 h-2 bg-white/10 rounded-full overflow-hidden max-w-[200px]">
                    <div className="h-full rounded-full transition-all duration-500" style={{
                      width: `${form.confidence * 100}%`,
                      background: form.confidence >= 0.8 ? "linear-gradient(90deg, #22c55e, #4ade80)"
                        : form.confidence >= 0.5 ? "linear-gradient(90deg, #eab308, #facc15)"
                        : "linear-gradient(90deg, #ef4444, #f87171)"
                    }} />
                  </div>
                  <span className={`font-semibold text-xs ${form.confidence >= 0.8 ? "text-green-400" : form.confidence >= 0.5 ? "text-yellow-400" : "text-red-400"}`}>
                    {(form.confidence * 100).toFixed(1)}%
                  </span>
                </div>
                {form.confidence < 0.8 && (
                  <p className="text-xs text-yellow-400/70 mt-2 flex items-center gap-1">{'\u26A0'} Low confidence &mdash; verify all fields carefully</p>
                )}
              </div>
            )}
          </div>

          <div className="gh-card" style={{padding:"20px"}}>
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-xs font-medium uppercase tracking-wider" style={{color:"var(--text-secondary)", letterSpacing:"0.5px"}}>Extracted Fields</h3>
              {(form.confidence != null && form.confidence < 0.7) && (
                <span className="tag tag-yellow text-[10px]">{'\u26A0'} Needs Review</span>
              )}
            </div>

            <div className={`${form.confidence != null && form.confidence < 0.7 ? "ring-1 ring-yellow-500/20 rounded-lg p-3 -mx-1" : ""}`}>
              <Field label="Seller GSTIN" error={errors.gstin} optional>
                <input className={`input ${form.confidence != null && form.confidence < 0.6 ? "border-yellow-500/30" : ""}`} value={form.gstin} onChange={(e) => setForm((p) => ({ ...p, gstin: e.target.value }))} placeholder="Leave empty if not on invoice" />
              </Field>
              <div className="grid grid-cols-2 gap-3">
                <Field label="Invoice Number" error={errors.invoice_number}>
                  <input className={`input ${form.confidence != null && form.confidence < 0.6 ? "border-yellow-500/30" : ""}`} value={form.invoice_number} onChange={(e) => setForm((p) => ({ ...p, invoice_number: e.target.value }))} />
                </Field>
                <Field label="Date" error={errors.date}>
                  <input className={`input ${form.confidence != null && form.confidence < 0.6 ? "border-yellow-500/30" : ""}`} value={form.date} onChange={(e) => setForm((p) => ({ ...p, date: e.target.value }))} placeholder="YYYY-MM-DD" />
                </Field>
              </div>
              <Field label="Total Amount" error={errors.total_amount}>
                <input className="input" type="number" step="0.01" value={form.total_amount} onChange={(e) => setForm((p) => ({ ...p, total_amount: e.target.value }))} />
              </Field>
              <Field label="Vendor Name" error={errors.vendor_name}>
                <input className={`input ${form.confidence != null && form.confidence < 0.6 ? "border-yellow-500/30" : ""}`} value={form.vendor_name} onChange={(e) => setForm((p) => ({ ...p, vendor_name: e.target.value }))} />
              </Field>
              <Field label="Vendor Address" optional>
                <input className="input" value={form.vendor_address || ""} onChange={(e) => setForm((p) => ({ ...p, vendor_address: e.target.value }))} />
              </Field>
              <div className="grid grid-cols-2 gap-3">
                <Field label="Buyer GSTIN" optional>
                  <input className="input" value={form.buyer_gstin || ""} onChange={(e) => setForm((p) => ({ ...p, buyer_gstin: e.target.value }))} />
                </Field>
                <Field label="Buyer Name" optional>
                  <input className="input" value={form.buyer_name || ""} onChange={(e) => setForm((p) => ({ ...p, buyer_name: e.target.value }))} />
                </Field>
              </div>

              <Field label="Voucher Type">
                <select className="input" value={form.voucher_type || "Purchase"} onChange={(e) => setForm((p) => ({ ...p, voucher_type: e.target.value }))}>
                  <option value="Purchase">Purchase</option>
                  <option value="Sales">Sales</option>
                  <option value="Payment">Payment</option>
                  <option value="Receipt">Receipt</option>
                  <option value="Journal">Journal</option>
                  <option value="Credit Note">Credit Note</option>
                  <option value="Debit Note">Debit Note</option>
                </select>
              </Field>
            </div>

            <div className="pt-2">
              <div className="flex items-center justify-between mb-3">
                <label className="text-sm font-medium text-gray-300">Line Items</label>
                <button onClick={() => { setForm((p) => ({ ...p, line_items: [...p.line_items, { description: "", quantity: 1, rate: 0, taxable_value: 0, tax_rate: 0 }] })); setLedgers((p) => [...p, ""]); }} className="btn-secondary text-xs px-3 py-1.5">+ Add Item</button>
              </div>
              {errors.line_items && <p className="text-red-400 text-xs mb-2">{errors.line_items}</p>}
              {form.line_items.map((item, i) => (
                <div key={i} className={`glass rounded-xl p-3 mb-2 space-y-2 border ${form.confidence != null && form.confidence < 0.7 ? "border-yellow-500/15" : "border-white/5"} animate-fadeIn`} style={{ animationDelay: `${i * 0.05}s` }}>
                  <div className="flex justify-between items-center">
                    <span className="text-xs font-medium text-gray-500">Item {i+1}</span>
                    <button onClick={() => { setForm((p) => ({ ...p, line_items: p.line_items.filter((_, j) => j !== i) })); setLedgers((p) => p.filter((_, j) => j !== i)); }} className="text-xs text-red-400 hover:text-red-300">Remove</button>
                  </div>
                  <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                    {[{k:"description",l:"Description"},{k:"quantity",l:"Qty",t:"number"},{k:"rate",l:"Rate",t:"number"},{k:"taxable_value",l:"Taxable",t:"number"},{k:"tax_rate",l:"Tax Rate %",t:"number"},{k:"cgst",l:"CGST",t:"number",n:!0},{k:"sgst",l:"SGST",t:"number",n:!0},{k:"igst",l:"IGST",t:"number",n:!0}].map((f) => (
                      <div key={f.k}>
                        <label className="text-xs text-gray-500 mb-1 block">{f.l}</label>
                        <input className="input text-sm" type={f.t||"text"} step={f.t==="number"?"0.01":void 0}
                          value={f.n ? (item[f.k]??"") : item[f.k]}
                          onChange={(e) => {
                            const items = [...form.line_items];
                            items[i] = { ...items[i], [f.k]: f.n && e.target.value === "" ? null : e.target.value };
                            setForm((p) => ({ ...p, line_items: items }));
                          }} />
                      </div>
                    ))}
                    <div className="col-span-full">
                      <label className="text-xs text-gray-500 mb-1 block flex items-center gap-1">
                        Ledger <span className="text-red-400">*</span>
                        <span className="text-gray-600 font-normal">(required)</span>
                      </label>
                      <select className="input text-sm" value={ledgers[i] || ""} onChange={(e) => { const l = [...ledgers]; l[i] = e.target.value; setLedgers(l); }}>
                        <option value="">-- Select ledger --</option>
                        {tallyLedgers.length > 0 && <optgroup label="Live From Tally Prime ERP">
                          {tallyLedgers.map((l) => <option key={l} value={l}>{l}</option>)}
                        </optgroup>}
                        <optgroup label="Common Ledgers">
                          {COMMON_LEDGERS.map((l) => <option key={l} value={l}>{l}</option>)}
                        </optgroup>
                      </select>
                      {ledgers[i] && <p className="text-[10px] text-green-400/70 mt-0.5">{'\u2713'} {ledgers[i]}</p>}
                    </div>
                  </div>
                </div>
              ))}
              {form.line_items.length > 0 && ledgers.some((l) => !l) && (
                <p className="text-xs text-yellow-400/70 mt-1 flex items-center gap-1">{'\u26A0'} Assign a ledger to each item before confirming</p>
              )}
            </div>

            {showPreview && mastersPreview && (
              <div className="glass-card p-3 space-y-2 border border-indigo-500/20">
                <div className="flex items-center justify-between">
                  <h4 className="text-xs font-semibold text-indigo-300">Pre-Import Report</h4>
                  <button onClick={() => setShowPreview(false)} className="text-xs text-gray-500 hover:text-gray-300">Hide</button>
                </div>

                {showWarnings.length > 0 && (
                  <div className="space-y-1 mb-2">
                    {showWarnings.map((w, i) => {
                      const severity = w.severity || "medium";
                      const bg = severity === "high" ? "bg-red-500/10 border-red-500/20" : severity === "medium" ? "bg-amber-500/10 border-amber-500/20" : "bg-blue-500/10 border-blue-500/20";
                      const text = severity === "high" ? "text-red-300" : severity === "medium" ? "text-amber-300" : "text-blue-300";
                      return (
                        <div key={i} className={`${bg} border rounded-lg p-2`}>
                          <div className="flex items-center gap-1 mb-0.5">
                            <span className={`text-[10px] font-bold ${text}`}>{severity === "high" ? "!" : "\u26A0"}</span>
                            <span className={`text-[10px] font-medium ${text}`}>
                              {w.type === "company_name" ? "Company" : w.type === "company_gstin" ? "GSTIN" : w.type === "vendor_name" ? "Vendor" : w.type === "similar_vendor_exists" ? "Similar Vendor" : w.type === "duplicate_invoice" ? "Duplicate" : "Validation"}
                            </span>
                          </div>
                          <p className="text-[11px] text-gray-300">{w.message}</p>
                        </div>
                      );
                    })}
                  </div>
                )}

                <div className="flex items-center gap-2 text-xs text-gray-500 mb-1">
                  <span className="font-semibold text-indigo-300">{mastersPreview.length}</span> masters
                </div>
                <div className="space-y-1 max-h-36 overflow-y-auto">
                  {mastersPreview.map((m, i) => (
                    <div key={i} className="flex items-center gap-2 text-[11px]">
                      <span className={`px-1.5 py-0.5 rounded font-mono ${m.type === "VoucherType" ? "text-purple-300 bg-purple-500/10" : m.type === "StockItem" || m.type === "StockGroup" ? "text-emerald-300 bg-emerald-500/10" : "text-cyan-300 bg-cyan-500/10"}`}>{m.type}</span>
                      <span className="text-gray-200">{m.name}</span>
                      {m.parent && <span className="text-gray-500">{'\u2192'} {m.parent}</span>}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {reviewErrors && (
              <div className="bg-red-500/10 border border-red-500/20 rounded-xl p-3 space-y-1">
                <p className="text-xs font-medium text-red-400">Review Blocked</p>
                {reviewErrors.map((e, i) => <p key={i} className="text-xs text-red-300/80 pl-2 border-l-2 border-red-500/30">{e}</p>)}
              </div>
            )}

            <div className="flex gap-2 pt-2 flex-wrap">
              <button onClick={previewMasters} disabled={previewLoading} className="btn-secondary text-xs px-3 py-2">
                {previewLoading ? "Loading..." : "Preview Masters"}
              </button>

              {!reviewConfirmed ? (
                <button onClick={doReviewConfirm} className="btn-primary flex-1 py-2.5 text-sm">
                  Review &amp; Confirm
                </button>
              ) : (
                <button onClick={() => downloadXML()} className="btn-primary flex-1 py-2.5 text-sm">
                  Download XML
                </button>
              )}

              <button onClick={resetForm} className="btn-secondary text-xs px-3 py-2">Clear</button>
            </div>
          </div>
        </div>
      )}

      {showValModal && valModalData && (
        <div className="gh-modal-overlay" onClick={() => setShowValModal(false)}>
          <div className="gh-modal" style={{padding:"24px"}} onClick={(e) => e.stopPropagation()}>
            <div style={{display:"flex", justifyContent:"space-between", alignItems:"center", marginBottom:"16px"}}>
              <h3 style={{fontSize:"16px", fontWeight:600}}>Validation Results</h3>
              <button onClick={() => setShowValModal(false)} style={{color:"var(--text-tertiary)", background:"none", border:"none", fontSize:"20px", cursor:"pointer"}}>&times;</button>
            </div>

            {valModalData.warnings.length > 0 && (
              <div style={{marginBottom:"12px"}}>
                <p className="gh-tag gh-tag-yellow" style={{marginBottom:"6px"}}>Warnings</p>
                {valModalData.warnings.map((w, i) => (
                  <p key={i} style={{fontSize:"12px", color:"var(--accent-yellow)", paddingLeft:"8px", borderLeft:"2px solid rgba(210,153,34,0.3)", marginBottom:"4px"}}>{w}</p>
                ))}
              </div>
            )}

            {valModalData.soft.length > 0 && (
              <div style={{marginBottom:"12px"}}>
                <p className="gh-tag gh-tag-yellow" style={{marginBottom:"6px"}}>Soft Errors (overridable)</p>
                {valModalData.soft.map((e, i) => (
                  <p key={i} style={{fontSize:"12px", color:"var(--accent-yellow)", paddingLeft:"8px", borderLeft:"2px solid rgba(210,153,34,0.3)", marginBottom:"4px"}}>{e}</p>
                ))}
              </div>
            )}

            {valModalData.blocking.length > 0 && (
              <div style={{marginBottom:"16px"}}>
                <p className="gh-tag gh-tag-red" style={{marginBottom:"6px"}}>Blocking Errors</p>
                {valModalData.blocking.map((e, i) => (
                  <p key={i} style={{fontSize:"12px", color:"var(--accent-red)", paddingLeft:"8px", borderLeft:"2px solid rgba(248,81,73,0.3)", marginBottom:"4px"}}>{e}</p>
                ))}
              </div>
            )}

            <div style={{display:"flex", gap:"8px", paddingTop:"8px"}}>
              <button onClick={() => { setShowValModal(false); downloadXML(true); }}
                className="gh-btn gh-btn-primary" style={{flex:1, justifyContent:"center", padding:"10px"}}>
                Generate Anyway
              </button>
              <button onClick={() => setShowValModal(false)}
                className="gh-btn gh-btn-secondary" style={{flex:1, justifyContent:"center", padding:"10px"}}>
                Back to Edit
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function ValidationSummary({ validation }) {
  if (!validation) return null;
  const checks = Object.entries(validation.checks || {});
  const passed = checks.filter(([, r]) => r.pass).length;
  const total = checks.length;
  const warnings = validation.warnings || [];
  const softErrors = validation.soft_errors || [];
  const blockingErrors = validation.blocking_errors || [];
  const statutoryChecks = ["statutory_routing", "gst_structure", "gstin", "tax_rates"];
  return (
    <div className="gh-card" style={{padding:"16px"}}>
      <div style={{display:"flex", justifyContent:"space-between", alignItems:"center", marginBottom:"12px"}}>
        <div style={{display:"flex", alignItems:"center", gap:"8px"}}>
          <span style={{fontSize:"12px", color:"var(--text-secondary)"}}>Document:</span>
          <span style={{fontSize:"13px", fontWeight:600, textTransform:"capitalize"}}>{(validation.document_type || "unknown").replace(/_/g, " ")}</span>
        </div>
        <span className={`gh-tag ${validation.passed ? "gh-tag-green" : "gh-tag-red"}`}>
          {validation.passed ? "PASS" : "FAIL"}
        </span>
      </div>
      <div style={{display:"flex", flexWrap:"wrap", gap:"6px", marginBottom:"12px"}}>
        {checks.map(([name, result]) => {
          const isStatutory = statutoryChecks.includes(name);
          return (
            <div key={name} className={`gh-tag ${
              result.pass ? (result.warnings?.length ? "gh-tag-yellow" : isStatutory ? "gh-tag-blue" : "gh-tag-green") : "gh-tag-red"
            }`}>
              <span>{result.pass ? (result.warnings?.length ? "\u26A0" : "\u2713") : "\u2717"}</span>
              <span className="capitalize">{name.replace(/_/g, " ")}</span>
            </div>
          );
        })}
      </div>
      {warnings.length > 0 && (
        <div style={{marginBottom:"8px"}}>
          <p className="gh-tag gh-tag-yellow" style={{marginBottom:"6px"}}>Warnings</p>
          {warnings.map((w, i) => (
            <p key={i} style={{fontSize:"12px", color:"var(--accent-yellow)", paddingLeft:"8px", borderLeft:"2px solid rgba(210,153,34,0.3)", marginBottom:"4px"}}>{w}</p>
          ))}
        </div>
      )}
      {softErrors.length > 0 && (
        <div style={{marginBottom:"8px"}}>
          <p className="gh-tag gh-tag-yellow" style={{marginBottom:"6px"}}>Soft Errors</p>
          {softErrors.map((e, i) => (
            <p key={i} style={{fontSize:"12px", color:"var(--accent-yellow)", paddingLeft:"8px", borderLeft:"2px solid rgba(210,153,34,0.3)", marginBottom:"4px"}}>{e}</p>
          ))}
        </div>
      )}
      {blockingErrors.length > 0 && (
        <div>
          <p className="gh-tag gh-tag-red" style={{marginBottom:"6px"}}>Blocking Errors</p>
          {blockingErrors.map((e, i) => (
            <p key={i} style={{fontSize:"12px", color:"var(--accent-red)", paddingLeft:"8px", borderLeft:"2px solid rgba(248,81,73,0.3)", marginBottom:"4px"}}>{e}</p>
          ))}
        </div>
      )}
    </div>
  );
}

function DashboardPage({ refreshKey, setRefreshKey, onEditInvoice }) {
  const { getAuthHeaders } = useAuth();
  const [invoices, setInvoices] = useState([]);
  const [clients, setClients] = useState([]);
  const [loading, setLoading] = useState(true);
  const [fetchError, setFetchError] = useState(null);
  const [actionMsg, setActionMsg] = useState(null);
  const [filterClient, setFilterClient] = useState("");
  const [showDashModal, setShowDashModal] = useState(false);
  const [dashModalData, setDashModalData] = useState(null);
  const [dashPendingInv, setDashPendingInv] = useState(null);
  const [selectedIds, setSelectedIds] = useState([]);
  const [bulkLedger, setBulkLedger] = useState("");

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
    if (selectedIds.length === invoices.length) { setSelectedIds([]); }
    else { setSelectedIds(invoices.map((i) => i.id)); }
  }

  async function applyBulkMap() {
    if (!selectedIds.length || !bulkLedger.trim()) return;
    const res = await fetch(`${BACKEND}/api/v3/invoices/bulk-map`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...getAuthHeaders() },
      body: JSON.stringify({ invoice_ids: selectedIds, target_ledger: bulkLedger.trim() }),
    });
    if (res.ok) { setActionMsg({ type: "success", text: `${selectedIds.length} invoices mapped to "${bulkLedger}"` }); setSelectedIds([]); setRefreshKey((k) => k + 1); }
    else setActionMsg({ type: "error", text: "Bulk map failed" });
  }

  async function generateXml(inv, force = false) {
    setActionMsg({ type: "info", text: "Validating..." });
    try {
      const res = await fetch(`${BACKEND}/invoices/${inv.id}/generate?force=${force}`, { method: "POST", headers: getAuthHeaders() });
      if (res.status === 422) {
        const body = await res.json();
        setDashModalData({
          blocking: body.blocking_errors || [],
          soft: body.soft_errors || [],
          warnings: body.warnings || [],
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
    setActionMsg({ type: "info", text: "Queueing for Tally sync..." });
    try {
      const res = await fetch(`${BACKEND}/api/v3/invoices/${inv.id}/sync-now`, { method: "POST", headers: getAuthHeaders() });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `HTTP ${res.status}`);
      }
      const result = await res.json();
      setActionMsg({ type: "success", text: result.message || "Queued! Connector will pick it up within 30s." });
      setRefreshKey((k) => k + 1);
    } catch (e) {
      setActionMsg({ type: "error", text: `Sync trigger failed: ${e.message}` });
    }
  }

  if (loading) return <div className="text-center py-20"><div className="w-8 h-8 border-2 border-indigo-400 border-t-transparent rounded-full animate-spin mx-auto" /></div>;

  return (
    <div className="space-y-4 animate-fadeIn">
      {actionMsg && (
        <div className={`glass rounded-xl p-4 text-sm flex items-center gap-2 ${
          actionMsg.type === "error" ? "border-red-500/20 text-red-300"
          : actionMsg.type === "success" ? "border-green-500/20 text-green-300"
          : "border-indigo-500/20 text-indigo-300"
        }`}>{actionMsg.text}</div>
      )}

      <div className="glass rounded-xl px-4 py-3 flex items-center gap-3">
        <label className="text-sm text-gray-300 whitespace-nowrap">Filter by client:</label>
        <select className="input max-w-xs" value={filterClient} onChange={(e) => setFilterClient(e.target.value)}>
          <option value="">All Clients</option>
          {clients.map((c) => (
            <option key={c.client_id} value={c.client_id}>{c.company_name}</option>
          ))}
        </select>
      </div>

      {invoices.length === 0 ? (
        <div className="glass-card p-12 text-center">
          <p className="text-gray-400 text-lg">No invoices yet.</p>
          <p className="text-gray-500 text-sm mt-2">Go to Extract tab to process invoices.</p>
        </div>
      ) : (
        <div>
          {selectedIds.length > 0 && (
            <div className="glass rounded-xl px-4 py-3 mb-3 flex items-center gap-3">
              <span className="text-xs text-gray-400">{selectedIds.length} selected</span>
              <input className="input flex-1 text-xs" value={bulkLedger} onChange={(e) => setBulkLedger(e.target.value)} placeholder="Target ledger name..." />
              <button onClick={applyBulkMap} className="px-3 py-1.5 bg-indigo-500/20 text-indigo-300 rounded-lg text-xs font-medium hover:bg-indigo-500/30">Apply to Selected</button>
              <button onClick={() => setSelectedIds([])} className="text-xs text-gray-500 hover:text-gray-300">Clear</button>
            </div>
          )}
          <div className="glass-card overflow-hidden">
            <table className="w-full text-sm">
              <thead><tr className="border-b border-white/5 text-left text-xs text-gray-500 uppercase">
                <th className="px-2 py-3.5 w-8">
                  <input type="checkbox" className="accent-indigo-500" checked={selectedIds.length === invoices.length && invoices.length > 0} onChange={toggleSelectAll} />
                </th>
                <th className="px-2 py-3.5 font-medium">#</th>
                <th className="px-4 py-3.5 font-medium">Vendor</th>
                <th className="px-4 py-3.5 font-medium">Invoice</th>
                <th className="px-4 py-3.5 font-medium">Date</th>
                <th className="px-4 py-3.5 font-medium">Status</th>
                <th className="px-4 py-3.5 font-medium text-center">Tally</th>
                <th className="px-4 py-3.5 font-medium text-right">Amount</th>
                <th className="px-4 py-3.5 font-medium text-center">XML</th>
              </tr></thead>
              <tbody className="divide-y divide-white/5">
                {invoices.map((inv) => (
                  <tr key={inv.id} className={`table-row cursor-pointer hover:bg-white/[0.03] ${selectedIds.includes(inv.id) ? "bg-indigo-500/5" : ""}`} onClick={() => onEditInvoice(inv.id)}>
                    <td className="px-2 py-3.5">
                      <input type="checkbox" className="accent-indigo-500" checked={selectedIds.includes(inv.id)} onChange={(e) => { e.stopPropagation(); toggleSelect(inv.id); }} onClick={(e) => e.stopPropagation()} />
                    </td>
                    <td className="px-2 py-3.5 text-gray-500 text-xs">{inv.id}</td>
                  <td className="px-4 py-3.5 font-medium text-gray-200">{inv.vendor_name || "-"}</td>
                  <td className="px-4 py-3.5 text-gray-300">{inv.invoice_number || "-"}</td>
                  <td className="px-4 py-3.5 text-gray-400">{inv.date || "-"}</td>
                  <td className="px-4 py-3.5">
                    <div className="flex items-center gap-1.5">
                      {inv.status === "draft" ? (
                        <span className="tag tag-yellow text-[10px]">Draft</span>
                      ) : inv.status === "validated" ? (
                        <span className="tag tag-green text-[10px]">Reviewed</span>
                      ) : inv.status === "exported" ? (
                        <span className="tag tag-blue text-[10px]">Exported</span>
                      ) : (
                        <span className="tag tag-gray text-[10px]">{inv.status || "Pending"}</span>
                      )}
                      {inv.decision_label && inv.decision_label !== "Unknown" && (
                        <span className={`inline-flex items-center gap-1 text-[10px] font-medium px-2 py-0.5 rounded-full`}
                          style={{ backgroundColor: inv.decision_color === "green" ? "rgba(34,197,94,0.15)" : inv.decision_color === "red" ? "rgba(239,68,68,0.15)" : inv.decision_color === "yellow" ? "rgba(234,179,8,0.15)" : "rgba(107,114,128,0.15)", color: inv.decision_color === "green" ? "#22c55e" : inv.decision_color === "red" ? "#ef4444" : inv.decision_color === "yellow" ? "#eab308" : "#9ca3af" }}>
                          {inv.decision_label}
                        </span>
                      )}
                    </div>
                  </td>
                  <td className="px-4 py-3.5 text-center">
                    {(() => {
                      const s = inv.status;
                      if (s === "exported") return <span className="inline-flex items-center gap-1 text-xs font-medium px-2 py-0.5 rounded-full" style={{background:"rgba(34,197,94,0.15)",color:"#4ade80"}}>Synced</span>;
                      if (s === "sync_error") return (
                        <div className="flex items-center gap-1.5 justify-center">
                          <span className="inline-flex items-center gap-1 text-xs font-medium px-2 py-0.5 rounded-full" style={{background:"rgba(239,68,68,0.15)",color:"#f87171"}} title={inv.sync_error || ""}>Failed</span>
                          <button onClick={(e) => { e.stopPropagation(); sendToTally(inv); }}
                            className="text-[10px] text-yellow-400 hover:text-yellow-300 underline" title={inv.sync_error || ""}>Retry</button>
                        </div>
                      );
                      if (s === "validated" && inv.xml_generated) return (
                        <button onClick={(e) => { e.stopPropagation(); sendToTally(inv); }}
                          className="text-xs font-medium text-blue-400 hover:text-blue-300 underline">Send to Tally</button>
                      );
                      return <span className="text-xs text-gray-500">-</span>;
                    })()}
                  </td>
                  <td className="px-4 py-3.5 text-right font-medium text-gray-200">{inv.total_amount ? "\u20B9" + parseFloat(inv.total_amount).toLocaleString() : "-"}</td>
                  <td className="px-4 py-3.5 text-center">
                    {inv.status === "draft" ? (
                      <button onClick={(e) => { e.stopPropagation(); onEditInvoice(inv.id); }}
                        className="text-xs font-medium text-yellow-400 hover:text-yellow-300 underline">Review</button>
                    ) : inv.xml_generated ? (
                      <button onClick={(e) => { e.stopPropagation(); downloadXml(inv.id); }}
                        className="text-xs font-medium text-indigo-400 hover:text-indigo-300 underline">Download</button>
                    ) : (
                      <button onClick={(e) => { e.stopPropagation(); generateXml(inv); }}
                        className="text-xs font-medium text-yellow-400 hover:text-yellow-300 underline">Generate</button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        </div>
      )}

      {showDashModal && dashModalData && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm" onClick={() => { setShowDashModal(false); setDashPendingInv(null); }}>
          <div className="glass-card max-w-lg w-full mx-4 p-6 space-y-4 animate-slideUp" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between">
              <h3 className="text-lg font-semibold text-gray-200">Validation Results</h3>
              <button onClick={() => { setShowDashModal(false); setDashPendingInv(null); }} className="text-gray-500 hover:text-gray-300 text-xl">&times;</button>
            </div>

            {dashModalData.warnings.length > 0 && (
              <div className="space-y-1">
                <p className="text-xs font-medium text-yellow-400">Warnings</p>
                {dashModalData.warnings.map((w, i) => (
                  <p key={i} className="text-xs text-yellow-300/80 pl-2 border-l-2 border-yellow-500/30">{w}</p>
                ))}
              </div>
            )}

            {dashModalData.soft.length > 0 && (
              <div className="space-y-1">
                <p className="text-xs font-medium text-orange-400">Soft Errors (overridable)</p>
                {dashModalData.soft.map((e, i) => (
                  <p key={i} className="text-xs text-orange-300/80 pl-2 border-l-2 border-orange-500/30">{e}</p>
                ))}
              </div>
            )}

            {dashModalData.blocking.length > 0 && (
              <div className="space-y-1">
                <p className="text-xs font-medium text-red-400">Blocking Errors</p>
                {dashModalData.blocking.map((e, i) => (
                  <p key={i} className="text-xs text-red-300/80 pl-2 border-l-2 border-red-500/30">{e}</p>
                ))}
              </div>
            )}

            <div className="flex gap-3 pt-2">
              <button onClick={() => { const inv = dashPendingInv; setShowDashModal(false); setDashPendingInv(null); if (inv) generateXml(inv, true); }}
                className="btn-primary flex-1 py-2.5 text-sm">
                Generate Anyway
              </button>
              <button onClick={() => { setShowDashModal(false); setDashPendingInv(null); }}
                className="btn-secondary flex-1 py-2.5 text-sm">
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function AdminPage() {
  const { getAuthHeaders } = useAuth();
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch(`${BACKEND}/auth/admin/users`, { headers: getAuthHeaders() })
      .then((r) => r.json()).then(setUsers).catch(() => {}).finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="text-center py-20"><div className="w-8 h-8 border-2 border-indigo-400 border-t-transparent rounded-full animate-spin mx-auto" /></div>;

  return (
    <div className="space-y-4 animate-fadeIn">
      <h2 className="text-lg font-bold gradient-text">Users ({users.length})</h2>
      <div className="glass-card overflow-hidden">
        <table className="w-full text-sm">
          <thead><tr className="border-b border-white/5 text-left text-xs text-gray-500 uppercase">
            <th className="px-4 py-3.5 font-medium">Email</th>
            <th className="px-4 py-3.5 font-medium">Name</th>
            <th className="px-4 py-3.5 font-medium">Role</th>
            <th className="px-4 py-3.5 font-medium text-center">Invoices</th>
            <th className="px-4 py-3.5 font-medium">Joined</th>
          </tr></thead>
          <tbody className="divide-y divide-white/5">
            {users.map((u) => (
              <tr key={u.email} className="table-row">
                <td className="px-4 py-3.5 font-medium text-gray-200">{u.email}</td>
                <td className="px-4 py-3.5 text-gray-300">{u.name || "-"}</td>
                <td className="px-4 py-3.5"><span className={`tag ${u.role === "admin" ? "tag-yellow" : "tag-green"}`}>{u.role}</span></td>
                <td className="px-4 py-3.5 text-center text-gray-400">{u.invoice_count || 0}</td>
                <td className="px-4 py-3.5 text-xs text-gray-500">{u.created_at ? u.created_at.slice(0, 10) : "-"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function SettingsPage() {
  const { user, refreshUser, getAuthHeaders, BACKEND } = useAuth();
  const [companyName, setCompanyName] = useState(user?.company_name || "");
  const [companyGstin, setCompanyGstin] = useState(user?.company_gstin || "");
  const [stateCode, setStateCode] = useState(user?.company_state_code || "");
  const [purchaseLedger, setPurchaseLedger] = useState(user?.purchase_ledger || "Purchase");
  const [salesLedger, setSalesLedger] = useState(user?.sales_ledger || "Sales");
  const [bankLedger, setBankLedger] = useState(user?.bank_ledger || "Bank");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const [tallyLedgers, setTallyLedgers] = useState([]);

  function ledgerMismatch(name) {
    if (!name || tallyLedgers.length === 0) return false;
    return !tallyLedgers.some((l) => l.toLowerCase().trim() === name.toLowerCase().trim());
  }

  useEffect(() => {
    fetch(`${BACKEND}/api/v3/sync/ledgers`, { headers: getAuthHeaders() })
      .then((r) => r.json()).then((d) => setTallyLedgers(d.ledgers || [])).catch(() => {});
  }, []);

  async function handleSave(e) {
    e.preventDefault();
    setError(""); setSaved(false);
    if (!companyName || !companyGstin || !stateCode) {
      setError("Company Name, GSTIN, and State Code are required");
      return;
    }
    setBusy(true);
    try {
      const res = await fetch(`${BACKEND}/api/v3/config`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...getAuthHeaders() },
        body: JSON.stringify({
          company_name: companyName,
          company_gstin: companyGstin.toUpperCase(),
          company_state_code: stateCode,
          purchase_ledger: purchaseLedger,
          sales_ledger: salesLedger,
          bank_ledger: bankLedger,
        }),
      });
      if (!res.ok) { let msg = "Failed to save"; try { const e = await res.json(); msg = e.detail || msg; } catch {} throw new Error(msg); }
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } catch (err) { setError(err.message); }
    setBusy(false);
  }

  return (
    <div className="space-y-4 animate-fadeIn">
      <h2 className="text-lg font-bold gradient-text">Company Settings</h2>
      <p className="text-sm text-gray-400">These settings are used for all invoices and XML generation.</p>
      <form onSubmit={handleSave} className="glass-card p-6 space-y-4 max-w-2xl">
        <div>
          <label className="text-xs text-gray-500 mb-1 block">Company Name (as in Tally) *</label>
          <input className="input w-full" value={companyName} onChange={(e) => setCompanyName(e.target.value)} placeholder="e.g. My Firm & Co." />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="text-xs text-gray-500 mb-1 block">Company GSTIN *</label>
            <input className="input w-full font-mono text-sm" value={companyGstin} onChange={(e) => setCompanyGstin(e.target.value.toUpperCase())} placeholder="e.g. 27AABCU1234F1ZP" maxLength={15} />
          </div>
          <div>
            <label className="text-xs text-gray-500 mb-1 block">State Code *</label>
            <select className="input w-full" value={stateCode} onChange={(e) => setStateCode(e.target.value)}>
              <option value="">-- Select --</option>
              {["01-Jammu & Kashmir","02-Himachal Pradesh","03-Punjab","04-Chandigarh","05-Uttarakhand","06-Haryana","07-Delhi","08-Rajasthan","09-Uttar Pradesh","10-Bihar","11-Sikkim","12-Arunachal Pradesh","13-Nagaland","14-Manipur","15-Mizoram","16-Tripura","17-Meghalaya","18-Assam","19-West Bengal","20-Jharkhand","21-Odisha","22-Chhattisgarh","23-Madhya Pradesh","24-Gujarat","25-Daman & Diu","26-Dadra & Nagar Haveli","27-Maharashtra","28-Andhra Pradesh (old)","29-Karnataka","30-Goa","31-Lakshadweep","32-Kerala","33-Tamil Nadu","34-Puducherry","35-Andaman & Nicobar","36-Telangana","37-Andhra Pradesh (new)"].map((s) => (
                <option key={s} value={s.slice(0,2)}>{s}</option>
              ))}
            </select>
          </div>
        </div>
        <div className="pt-2 border-t border-white/5">
          <p className="text-xs text-gray-500 mb-3">Default Tally Ledgers for XML export
            {tallyLedgers.length > 0 && <span className="text-green-400/70 ml-2">({tallyLedgers.length} ledgers synced from Tally)</span>}
          </p>
          {tallyLedgers.length === 0 && (
            <div className="bg-amber-500/10 border border-amber-500/20 rounded-lg p-3 mb-3">
              <p className="text-xs text-amber-300">{'\u26A0'} No ledgers synced yet. Download and run the Tally Connector (below) to pull your live Chart of Accounts.</p>
            </div>
          )}
          <div className="grid grid-cols-3 gap-3">
            <div>
              <label className="text-xs text-gray-500 mb-1 block">Default Purchase Ledger</label>
              <div className="relative">
                {tallyLedgers.length > 0 ? (
                  <select className="input w-full text-sm" value={purchaseLedger} onChange={(e) => setPurchaseLedger(e.target.value)}>
                    <option value="">-- Select --</option>
                    {tallyLedgers.map((l) => <option key={l} value={l}>{l}</option>)}
                  </select>
                ) : (
                  <input className="input w-full text-sm" value={purchaseLedger} onChange={(e) => setPurchaseLedger(e.target.value)} placeholder="e.g. Purchase Accounts" />
                )}
                {tallyLedgers.length > 0 && ledgerMismatch(purchaseLedger) && <span className="absolute right-2 top-1/2 -translate-y-1/2 text-yellow-400 text-xs font-bold">{'\u26A0'}</span>}
              </div>
            </div>
            <div>
              <label className="text-xs text-gray-500 mb-1 block">Default Sales Ledger</label>
              <div className="relative">
                {tallyLedgers.length > 0 ? (
                  <select className="input w-full text-sm" value={salesLedger} onChange={(e) => setSalesLedger(e.target.value)}>
                    <option value="">-- Select --</option>
                    {tallyLedgers.map((l) => <option key={l} value={l}>{l}</option>)}
                  </select>
                ) : (
                  <input className="input w-full text-sm" value={salesLedger} onChange={(e) => setSalesLedger(e.target.value)} placeholder="e.g. Sales Accounts" />
                )}
                {tallyLedgers.length > 0 && ledgerMismatch(salesLedger) && <span className="absolute right-2 top-1/2 -translate-y-1/2 text-yellow-400 text-xs font-bold">{'\u26A0'}</span>}
              </div>
            </div>
            <div>
              <label className="text-xs text-gray-500 mb-1 block">Default Bank Ledger</label>
              <div className="relative">
                {tallyLedgers.length > 0 ? (
                  <select className="input w-full text-sm" value={bankLedger} onChange={(e) => setBankLedger(e.target.value)}>
                    <option value="">-- Select --</option>
                    {tallyLedgers.map((l) => <option key={l} value={l}>{l}</option>)}
                  </select>
                ) : (
                  <input className="input w-full text-sm" value={bankLedger} onChange={(e) => setBankLedger(e.target.value)} placeholder="e.g. Bank" />
                )}
                {tallyLedgers.length > 0 && ledgerMismatch(bankLedger) && <span className="absolute right-2 top-1/2 -translate-y-1/2 text-yellow-400 text-xs font-bold">{'\u26A0'}</span>}
              </div>
            </div>
          </div>
        </div>
        {error && <p className="text-red-400 text-sm">{error}</p>}
        {saved && <p className="text-green-400 text-sm">Settings saved successfully.</p>}
        <button type="submit" disabled={busy} className="btn-primary py-3 px-6">
          {busy ? "Saving..." : "Save Settings"}
        </button>
      </form>

      <div className="glass-card p-6 max-w-2xl">
        <h3 className="text-sm font-semibold text-gray-200 mb-3">Ledger Corrections</h3>
        <p className="text-xs text-gray-500 mb-3">When a description maps to the wrong ledger, add a correction here. It will be remembered for future invoices.</p>
        <CorrectionMemoryUI />
      </div>

      <TallyConnectorPanel />
    </div>
  );
}

function TallyConnectorPanel() {
  const downloadUrl = "/downloads/InvoSyncTallyConnector.exe";
  return (
    <div className="glass-card p-6 max-w-2xl">
      <div className="flex items-start gap-4">
        <div className="p-3 rounded-lg" style={{background:"var(--accent-alpha)", color:"var(--accent)"}}>
          <svg className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
          </svg>
        </div>
        <div className="flex-1">
          <h3 className="text-sm font-semibold text-gray-200">InvoSync Tally Connector</h3>
          <p className="mt-1 text-xs text-gray-500">
            Run this lightweight assistant on the PC that has Tally Prime to auto-import XML vouchers. Tally must be open with connectivity port <strong>9000</strong> enabled (F1 &rarr; Settings &rarr; Connectivity).
          </p>
          <div className="mt-4 flex items-center gap-3">
            <a href={downloadUrl} download
               className="btn-primary inline-flex items-center gap-2 text-sm py-2.5 px-5">
              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
              </svg>
              Download Tally Connector
            </a>
            <span className="text-xs text-gray-600">Version 3.2 &bull; 72 MB</span>
          </div>
        </div>
      </div>
    </div>
  );
}

function BankingPage() {
  const { getAuthHeaders, BACKEND } = useAuth();
  const [rules, setRules] = useState([]);
  const [keyword, setKeyword] = useState("");
  const [voucherType, setVoucherType] = useState("Receipt");
  const [targetLedger, setTargetLedger] = useState("");
  const [txInput, setTxInput] = useState("");
  const [bankLedger, setBankLedger] = useState("Bank");
  const [processed, setProcessed] = useState(null);
  const [xml, setXml] = useState("");
  const [loading, setLoading] = useState(true);

  const fetchRules = () => {
    fetch(`${BACKEND}/api/v3/banking/rules`, { headers: getAuthHeaders() })
      .then((r) => r.json()).then(setRules).catch(() => {}).finally(() => setLoading(false));
  };

  useEffect(() => { fetchRules(); }, []);

  async function addRule() {
    if (!keyword.trim() || !targetLedger.trim()) return;
    await fetch(`${BACKEND}/api/v3/banking/rules`, {
      method: "POST", headers: { "Content-Type": "application/json", ...getAuthHeaders() },
      body: JSON.stringify({ keyword: keyword.trim(), voucher_type: voucherType, target_ledger: targetLedger.trim() }),
    });
    setKeyword(""); setTargetLedger("");
    fetchRules();
  }

  async function deleteRule(id) {
    await fetch(`${BACKEND}/api/v3/banking/rules/${id}`, { method: "DELETE", headers: getAuthHeaders() });
    fetchRules();
  }

  async function processStatement() {
    let txs;
    try { txs = JSON.parse(txInput); } catch { return; }
    const res = await fetch(`${BACKEND}/api/v3/banking/process`, {
      method: "POST", headers: { "Content-Type": "application/json", ...getAuthHeaders() },
      body: JSON.stringify({ transactions: txs, bank_ledger: bankLedger }),
    });
    if (res.ok) { const d = await res.json(); setProcessed(d.processed); setXml(d.xml); }
  }

  return (
    <div className="space-y-4 animate-fadeIn">
      <h2 className="text-lg font-bold gradient-text">Bank Statement Automation</h2>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="glass-card p-5 space-y-3">
          <h3 className="text-sm font-semibold text-gray-200">Keyword Rules</h3>
          <p className="text-xs text-gray-400">Map keywords → voucher type + ledger (e.g. "Razorpay" → Receipt → URD Debtors)</p>
          {loading ? <p className="text-xs text-gray-500">Loading...</p> : (
            <div className="space-y-2 max-h-60 overflow-y-auto">
              {rules.length === 0 && <p className="text-xs text-gray-500">No rules yet.</p>}
              {rules.map((r) => (
                <div key={r.id} className="flex items-center justify-between bg-white/5 rounded-lg px-3 py-2">
                  <div className="text-xs"><span className="font-mono text-yellow-400">{r.keyword}</span> <span className="text-gray-500">→</span> <span className="text-blue-400">{r.voucher_type}</span> <span className="text-gray-500">→</span> <span className="text-green-400">{r.target_ledger}</span></div>
                  <button onClick={() => deleteRule(r.id)} className="text-red-400 hover:text-red-300 text-xs">&times;</button>
                </div>
              ))}
            </div>
          )}
          <div className="flex gap-2 items-end">
            <div className="flex-1 space-y-1">
              <label className="text-[10px] text-gray-500">Keyword</label>
              <input className="input w-full text-xs" value={keyword} onChange={(e) => setKeyword(e.target.value)} placeholder="e.g. Razorpay" />
            </div>
            <div className="w-24 space-y-1">
              <label className="text-[10px] text-gray-500">Type</label>
              <select className="input w-full text-xs" value={voucherType} onChange={(e) => setVoucherType(e.target.value)}>
                <option>Receipt</option><option>Payment</option><option>Journal</option>
              </select>
            </div>
            <div className="flex-1 space-y-1">
              <label className="text-[10px] text-gray-500">Ledger</label>
              <input className="input w-full text-xs" value={targetLedger} onChange={(e) => setTargetLedger(e.target.value)} placeholder="e.g. URD Debtors" />
            </div>
            <button onClick={addRule} className="px-3 py-2 bg-indigo-500/20 text-indigo-300 rounded-lg text-xs font-medium hover:bg-indigo-500/30">Add</button>
          </div>
        </div>
        <div className="glass-card p-5 space-y-3">
          <h3 className="text-sm font-semibold text-gray-200">Process Statement</h3>
          <p className="text-xs text-gray-400">Paste JSON array of transactions, click Process</p>
          <div className="flex gap-2">
            <div className="flex-1">
              <label className="text-[10px] text-gray-500">Bank Ledger in Tally</label>
              <input className="input w-full text-xs" value={bankLedger} onChange={(e) => setBankLedger(e.target.value)} />
            </div>
          </div>
          <textarea className="input w-full h-28 text-xs font-mono" value={txInput} onChange={(e) => setTxInput(e.target.value)} placeholder='[{"transaction_date":"2026-07-09","description":"ACH CRED-RAZORPAY","withdraw_amount":0,"deposit_amount":4247,"balance":50000}]' />
          <button onClick={processStatement} className="px-4 py-2 bg-indigo-500/20 text-indigo-300 rounded-lg text-xs font-medium hover:bg-indigo-500/30">Process</button>
          {processed && (
            <div className="space-y-2">
              <h4 className="text-xs font-semibold text-gray-300">Mapped Transactions ({processed.length})</h4>
              <div className="max-h-40 overflow-y-auto space-y-1">
                {processed.map((tx, i) => (
                  <div key={i} className="text-xs bg-white/5 rounded px-2 py-1 flex gap-2">
                    <span className="text-gray-500 w-20">{tx.transaction_date}</span>
                    <span className="text-gray-300 flex-1 truncate">{tx.description}</span>
                    <span className={tx.voucher_type === "Receipt" ? "text-green-400" : "text-red-400"}>{tx.voucher_type}</span>
                    <span className="text-blue-400">{tx.target_ledger}</span>
                    {tx.rule_applied && <span className="text-yellow-500 text-[10px]">({tx.rule_applied})</span>}
                  </div>
                ))}
              </div>
              {xml && <button onClick={() => { const b = new Blob([xml], {type:"application/xml"}); const a = document.createElement("a"); a.href=URL.createObjectURL(b); a.download="bank_statement.xml"; a.click(); }} className="text-xs text-indigo-400 underline">Download XML</button>}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function CorrectionMemoryUI() {
  const { getAuthHeaders, BACKEND, user } = useAuth();
  const [corrections, setCorrections] = useState({});
  const [newDesc, setNewDesc] = useState("");
  const [newLedger, setNewLedger] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    fetch(`${BACKEND}/corrections`, { headers: getAuthHeaders() })
      .then((r) => r.json())
      .then((d) => setCorrections(d.corrections || {}))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [user]);

  async function addCorrection() {
    if (!newDesc.trim() || !newLedger.trim()) return;
    setSaving(true);
    try {
      const res = await fetch(`${BACKEND}/corrections`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...getAuthHeaders() },
        body: JSON.stringify({ description: newDesc.trim(), ledger: newLedger.trim() }),
      });
      if (res.ok) {
        setCorrections((p) => ({ ...p, [newDesc.trim().toLowerCase()]: newLedger.trim() }));
        setNewDesc(""); setNewLedger("");
      }
    } catch {}
    setSaving(false);
  }

  async function clearAll() {
    if (!window.confirm("Clear all correction memory?")) return;
    await fetch(`${BACKEND}/corrections`, { method: "DELETE", headers: getAuthHeaders() });
    setCorrections({});
  }

  async function removeOne(desc) {
    await fetch(`${BACKEND}/corrections`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...getAuthHeaders() },
      body: JSON.stringify({ description: desc, ledger: "" }),
    });
    setCorrections((p) => { const n = { ...p }; delete n[desc]; return n; });
  }

  const entries = Object.entries(corrections);
  return (
    <div>
      {loading ? (
        <div className="text-xs text-gray-500">Loading...</div>
      ) : entries.length > 0 ? (
        <div className="space-y-1.5 mb-3 max-h-48 overflow-y-auto">
          {entries.map(([desc, ledger]) => (
            <div key={desc} className="flex items-center gap-2 text-xs">
              <span className="text-gray-300 font-mono min-w-0 flex-1 truncate">{desc}</span>
              <span className="text-gray-500">→</span>
              <span className="text-indigo-300 font-mono min-w-0 flex-1 truncate">{ledger}</span>
              <button onClick={() => removeOne(desc)} className="text-red-400 hover:text-red-300 shrink-0">✕</button>
            </div>
          ))}
        </div>
      ) : (
        <p className="text-xs text-gray-600 mb-3">No corrections yet. They will appear here after you save them.</p>
      )}
      <div className="flex gap-2">
        <input className="input flex-1 text-xs" placeholder="Description (e.g. AWS)"
          value={newDesc} onChange={(e) => setNewDesc(e.target.value)} />
        <input className="input flex-1 text-xs" placeholder="Ledger (e.g. Professional Charges)"
          value={newLedger} onChange={(e) => setNewLedger(e.target.value)} />
        <button onClick={addCorrection} disabled={saving || !newDesc.trim() || !newLedger.trim()}
          className="btn-primary text-xs px-3 py-1.5 shrink-0">Save</button>
      </div>
      {entries.length > 0 && (
        <button onClick={clearAll} className="text-xs text-red-400 hover:text-red-300 mt-3">Clear all</button>
      )}
    </div>
  );
}

// AUTH DISABLED - SetupWizard removed

class ErrorBoundary extends React.Component {
  constructor(props) { super(props); this.state = { error: null }; }
  static getDerivedStateFromError(error) { return { error }; }
  render() {
    if (this.state.error) {
      return (
        <div className="min-h-screen flex items-center justify-center p-8">
          <div className="glass-card p-8 max-w-lg text-center space-y-4">
            <p className="text-red-400 text-lg font-semibold">Something went wrong</p>
            <p className="text-gray-400 text-sm">{this.state.error.message}</p>
            <button onClick={() => this.setState({ error: null })} className="btn-primary px-6 py-2">Try Again</button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}

export default function App() {
  const { user, getAuthHeaders } = useAuth();
  const [page, setPage] = useState("extract");
  const [refreshKey, setRefreshKey] = useState(0);
  const [currentId, setCurrentId] = useState(null);
  const [selectedClient, setSelectedClient] = useState("");
  const [tallyStatus, setTallyStatus] = useState(null);
  // Lifted so handleEditInvoice (App scope) can set them without ReferenceError
  const [ledgers, setLedgers] = useState([]);
  const [reviewConfirmed, setReviewConfirmed] = useState(false);
  const [reviewErrors, setReviewErrors] = useState(null);
  const [form, setForm] = useState({
    gstin: "", invoice_number: "", date: "", total_amount: "",
    vendor_name: "", vendor_address: "", buyer_gstin: "", buyer_name: "", confidence: null, line_items: [],
  });

  useEffect(() => {
    fetch(`${BACKEND}/api/v3/tally/status`, { headers: getAuthHeaders() })
      .then((r) => r.json()).then(setTallyStatus).catch(() => {});
    const interval = setInterval(() => {
      fetch(`${BACKEND}/api/v3/tally/status`, { headers: getAuthHeaders() })
        .then((r) => r.json()).then(setTallyStatus).catch(() => {});
    }, 30000);
    return () => clearInterval(interval);
  }, []);

  async function handleEditInvoice(invId) {
    try {
      const res = await fetch(`${BACKEND}/invoices/${invId}`, { headers: getAuthHeaders() });
      if (!res.ok) throw new Error("Failed to load invoice");
      const d = await res.json();
      const items = Array.isArray(d.line_items) ? d.line_items : [];
      setForm({
        gstin: d.gstin || "", invoice_number: d.invoice_number || "", date: d.date || "",
        total_amount: d.total_amount != null ? String(d.total_amount) : "",
        vendor_name: d.vendor_name || "", vendor_address: d.vendor_address || "",
        buyer_gstin: d.buyer_gstin || "", buyer_name: d.buyer_name || "",
        voucher_type: d.voucher_type || "Purchase",
        confidence: d.confidence ?? null,
        freight: d.freight != null ? d.freight : 0,
        round_off: d.round_off != null ? d.round_off : 0,
        tds_amount: d.tds_amount != null ? d.tds_amount : 0,
        line_items: items,
        _provider: d._provider || "", _model: d._model || "",
      });
      setLedgers(items.map(() => ""));
      setReviewConfirmed(false);
      setReviewErrors(null);
      setCurrentId(invId);
      if (d.client_id) setSelectedClient(String(d.client_id));
      setPage("extract");
    } catch (e) {
      alert("Error loading invoice: " + e.message);
    }
  }

  const pageRef = useRef(null);

  useEffect(() => {
    if (pageRef.current) {
      gsap.fromTo(pageRef.current,
        { opacity: 0, y: 20 },
        { opacity: 1, y: 0, duration: 0.4, ease: "power2.out" }
      );
    }
  }, [page]);

  return (
    <ErrorBoundary>
    <div className="min-h-screen">
      <NavBar active={page} onChange={(p) => { setPage(p); if (p === "dashboard") setRefreshKey((k) => k + 1); if (p === "clients") setRefreshKey((k) => k + 1); }} tallyStatus={tallyStatus} />
      <div className="gh-page" ref={pageRef}>
        {page === "extract" ? (
          <ExtractPage form={form} setForm={setForm} currentId={currentId} setCurrentId={setCurrentId} selectedClient={selectedClient} setSelectedClient={setSelectedClient} ledgers={ledgers} setLedgers={setLedgers} reviewConfirmed={reviewConfirmed} setReviewConfirmed={setReviewConfirmed} reviewErrors={reviewErrors} setReviewErrors={setReviewErrors} />
        ) : page === "clients" ? (
          <ClientPage refreshKey={refreshKey} />
        ) : page === "banking" ? (
          <BankingPage />
        ) : page === "settings" ? (
          <SettingsPage />
        ) : (
          <DashboardPage refreshKey={refreshKey} setRefreshKey={setRefreshKey} onEditInvoice={handleEditInvoice} />
        )}
      </div>
    </div>
    </ErrorBoundary>
  );
}
