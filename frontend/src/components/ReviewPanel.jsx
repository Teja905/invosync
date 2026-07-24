import { useState, useEffect, useCallback, useRef } from "react";
import BACKEND from "../api/client";
import COMMON_LEDGERS from "../constants/ledgers";
import Field from "./Field";
import WarningBanner from "./WarningBanner";

const VOUCHER_TYPES = [
  "Purchase", "Sales", "Payment", "Receipt", "Journal", "Credit Note", "Debit Note",
];

export default function ReviewPanel({
  form, setForm, ledgers, setLedgers, errors, reviewConfirmed, reviewErrors,
  currentId, imageUrl, tallyLedgers, validation, getAuthHeaders, companyGstin, companyName,
  onReviewConfirm, onDownloadXML, onPreviewMasters, onReset, onUndo, submitting,
}) {
  const [activeTab, setActiveTab] = useState("basic");
  const [showMastersPreview, setShowMastersPreview] = useState(false);
  const [mastersPreview, setMastersPreview] = useState(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewWarnings, setPreviewWarnings] = useState([]);
  const [vendorLedgerMap, setVendorLedgerMap] = useState({});
  const [autoMapped, setAutoMapped] = useState(false);
  const lastVendorRef = useRef("");

  // Day 2: Auto-ledger mapping — load vendor→ledger mappings on mount
  useEffect(() => {
    fetch(`${BACKEND}/api/v3/learning/vendor-map`, { headers: getAuthHeaders() })
      .then((r) => r.json())
      .then((d) => setVendorLedgerMap(d.mappings || {}))
      .catch(() => {});
  }, []);

  // Day 2: Auto-fill ledgers when vendor name changes (normalized + GSTIN match)
  useEffect(() => {
    const vendor = (form.vendor_name || "").trim().toLowerCase();
    const gstin = (form.gstin || "").trim().toUpperCase();
    if (!vendor && !gstin) return;
    if (vendor === lastVendorRef.current) return;
    lastVendorRef.current = vendor;

    if (autoMapped) return;

    // Priority 1: GSTIN match (most reliable)
    if (gstin && gstin.length === 15) {
      fetch(`${BACKEND}/api/v3/learning/vendor-map-by-gstin/${gstin}`, { headers: getAuthHeaders() })
        .then((r) => r.json())
        .then((d) => {
          if (d.found && d.ledger_name) {
            const items = form.line_items || [];
            if (items.length > 0) setLedgers(items.map(() => d.ledger_name));
            setAutoMapped(true);
          }
        })
        .catch(() => {});
      return;
    }

    // Priority 2: Normalized name match
    const savedLedger = vendorLedgerMap[vendor];
    if (savedLedger) {
      const items = form.line_items || [];
      if (items.length > 0) {
        setLedgers(items.map(() => typeof savedLedger === "object" ? savedLedger.ledger : savedLedger));
        setAutoMapped(true);
      }
    }
  }, [form.vendor_name, form.gstin, vendorLedgerMap]);

  // Day 2: Save vendor→ledger mapping when user picks a ledger (with GSTIN)
  const saveVendorLedger = useCallback(async (vendorName, ledgerName, gstin) => {
    if (!vendorName || !ledgerName) return;
    try {
      await fetch(`${BACKEND}/api/v3/learning/vendor-map`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...getAuthHeaders() },
        body: JSON.stringify({ vendor_name: vendorName, ledger_name: ledgerName, gstin: gstin || "" }),
      });
      setVendorLedgerMap((prev) => ({ ...prev, [vendorName.trim().toLowerCase()]: ledgerName }));
    } catch {}
  }, [getAuthHeaders]);

  useEffect(() => {
    setShowMastersPreview(false);
    setMastersPreview(null);
  }, [currentId]);

  const tabs = [
    { id: "basic", label: "Basic Details" },
    { id: "items", label: `Items (${form.line_items?.length || 0})` },
    { id: "totals", label: "Totals" },
  ];

  function doPreviewMasters() {
    setPreviewLoading(true);
    setMastersPreview(null);
    setPreviewWarnings([]);

    const payload = {
      ...form, total_amount: parseFloat(form.total_amount),
      buyer_gstin: form.buyer_gstin || companyGstin || "",
      buyer_name: form.buyer_name || companyName || "",
      line_items: (form.line_items || []).map((item) => ({
        ...item, quantity: parseFloat(item.quantity), rate: parseFloat(item.rate || 0),
        taxable_value: parseFloat(item.taxable_value), tax_rate: parseFloat(item.tax_rate || 0),
      })),
    };

    fetch(`${BACKEND}/preview-masters`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...getAuthHeaders() },
      body: JSON.stringify(payload),
    })
      .then((r) => r.json())
      .then((body) => {
        setMastersPreview(body.masters || []);
        setPreviewWarnings(body.warnings || []);
        setShowMastersPreview(true);
      })
      .catch(() => {})
      .finally(() => setPreviewLoading(false));
  }

  function computeTotals() {
    const items = form.line_items || [];
    const taxableTotal = items.reduce((s, it) => s + parseFloat(it.taxable_value || 0), 0);
    const cgstTotal = items.reduce((s, it) => s + parseFloat(it.cgst || 0), 0);
    const sgstTotal = items.reduce((s, it) => s + parseFloat(it.sgst || 0), 0);
    const igstTotal = items.reduce((s, it) => s + parseFloat(it.igst || 0), 0);
    const taxTotal = cgstTotal + sgstTotal + igstTotal;
    const freight = parseFloat(form.freight || 0);
    const roundOff = parseFloat(form.round_off || 0);
    const tds = parseFloat(form.tds_amount || 0);
    const grandTotal = taxableTotal + taxTotal + freight + roundOff - tds;
    return { taxableTotal, cgstTotal, sgstTotal, igstTotal, taxTotal, freight, roundOff, tds, grandTotal };
  }

  const totals = computeTotals();

  function isHighConfidence() {
    return form.confidence == null || form.confidence >= 0.7;
  }

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 animate-fadeInUp">
      {/* Left: Invoice Image */}
      <div className="space-y-4">
        <div className="premium-card" style={{ padding: "16px" }}>
          <h3 className="text-xs font-medium uppercase tracking-wider mb-3" style={{ color: "var(--text-secondary)", letterSpacing: "0.5px" }}>
            Invoice Document
          </h3>
          {imageUrl ? (
            <div className="rounded-lg overflow-hidden bg-black/20">
              <img
                src={imageUrl}
                alt="Invoice"
                className="w-full h-auto object-contain max-h-[600px]"
                onError={(e) => { e.target.style.display = "none"; e.target.nextSibling.style.display = "flex"; }}
              />
              <div className="hidden items-center justify-center h-48 text-gray-500 text-sm">
                <span>Image not available</span>
              </div>
            </div>
          ) : (
            <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "192px", background: "var(--bg-primary)", borderRadius: "6px", border: "1px dashed var(--border-primary)" }}>
              <div style={{ textAlign: "center" }}>
                <svg width="32" height="32" viewBox="0 0 24 24" fill="none" style={{ margin: "0 auto 8px", opacity: 0.3 }}>
                  <rect x="3" y="3" width="18" height="18" rx="2" stroke="currentColor" strokeWidth="1.5"/>
                  <circle cx="8.5" cy="8.5" r="1.5" fill="currentColor" opacity="0.5"/>
                  <path d="M3 16l4-4 3 3 5-5 6 6" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
                </svg>
                <p style={{ fontSize: "13px", color: "var(--text-tertiary)" }}>Invoice preview</p>
                <p style={{ fontSize: "11px", color: "var(--text-tertiary)", opacity: 0.6 }}>shown after extraction</p>
              </div>
            </div>
          )}
        </div>

        {form.confidence != null && (
          <div className="premium-card-flat p-4">
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
            {form.ind_confidence != null && (
              <div className="flex items-center gap-2 text-sm mt-2">
                <span className="text-gray-400">Independent:</span>
                <div className="flex-1 h-2 bg-white/10 rounded-full overflow-hidden max-w-[200px]">
                  <div className="h-full rounded-full transition-all duration-500" style={{
                    width: `${Math.min(form.ind_confidence * 100, 100)}%`,
                    background: form.ind_confidence >= 0.7 ? "linear-gradient(90deg, #22c55e, #4ade80)"
                      : form.ind_confidence >= 0.4 ? "linear-gradient(90deg, #eab308, #facc15)"
                      : "linear-gradient(90deg, #ef4444, #f87171)"
                  }} />
                </div>
                <span className={`font-semibold text-xs ${form.ind_confidence >= 0.7 ? "text-green-400" : form.ind_confidence >= 0.4 ? "text-yellow-400" : "text-red-400"}`}>
                  {(form.ind_confidence * 100).toFixed(1)}%
                </span>
              </div>
            )}
          </div>
        )}

        {/* Warnings Section */}
        {!isHighConfidence() && (
          <WarningBanner
            warning={{
              type: "Confidence",
              severity: "medium",
              message: `AI confidence is ${(form.confidence * 100).toFixed(0)}%. Verify all fields carefully before confirming.`,
            }}
            getAuthHeaders={getAuthHeaders}
          />
        )}
      </div>

      {/* Right: Fields */}
      <div className="premium-card" style={{ padding: "20px" }}>
        <div className="flex items-center justify-between mb-3">
          <div className="flex gap-1">
            {tabs.map((tab) => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`text-[10px] px-3 py-1.5 rounded-lg font-medium transition-colors ${
                  activeTab === tab.id
                    ? "bg-indigo-500/20 text-indigo-300"
                    : "text-gray-500 hover:text-gray-300"
                }`}
              >
                {tab.label}
              </button>
            ))}
          </div>
          {!isHighConfidence() && (
            <span className="premium-badge premium-badge-warning text-[10px]">{'\u26A0'} Needs Review</span>
          )}
        </div>

        {/* ===== TAB: Basic Details ===== */}
        {activeTab === "basic" && (
          <div className={`space-y-3 ${!isHighConfidence() ? "ring-1 ring-yellow-500/20 rounded-lg p-3 -mx-1" : ""}`}>
            <Field label="Voucher Type">
              <select
                className="input"
                value={form.voucher_type || "Purchase"}
                onChange={(e) => setForm((p) => ({ ...p, voucher_type: e.target.value }))}
              >
                {VOUCHER_TYPES.map((vt) => (
                  <option key={vt} value={vt}>{vt}</option>
                ))}
              </select>
            </Field>

            <Field label="Seller GSTIN" error={errors.gstin} optional>
              <input
                className={`input ${form.confidence != null && form.confidence < 0.6 ? "border-yellow-500/30" : ""}`}
                value={form.gstin}
                onChange={(e) => setForm((p) => ({ ...p, gstin: e.target.value }))}
                placeholder="Leave empty if not on invoice"
              />
            </Field>

            <div className="grid grid-cols-2 gap-3">
              <Field label="Invoice Number" error={errors.invoice_number}>
                <input
                  className={`input ${form.confidence != null && form.confidence < 0.6 ? "border-yellow-500/30" : ""}`}
                  value={form.invoice_number}
                  onChange={(e) => setForm((p) => ({ ...p, invoice_number: e.target.value }))}
                />
              </Field>
              <Field label="Date" error={errors.date}>
                <input
                  className={`input ${form.confidence != null && form.confidence < 0.6 ? "border-yellow-500/30" : ""}`}
                  value={form.date}
                  onChange={(e) => setForm((p) => ({ ...p, date: e.target.value }))}
                  placeholder="YYYY-MM-DD"
                />
              </Field>
            </div>

            <Field label="Total Amount" error={errors.total_amount}>
              <input
                className="input"
                type="number"
                step="0.01"
                value={form.total_amount}
                onChange={(e) => setForm((p) => ({ ...p, total_amount: e.target.value }))}
              />
            </Field>

            <Field label="Vendor Name" error={errors.vendor_name}>
              <input
                className={`input ${form.confidence != null && form.confidence < 0.6 ? "border-yellow-500/30" : ""}`}
                value={form.vendor_name}
                onChange={(e) => setForm((p) => ({ ...p, vendor_name: e.target.value }))}
              />
            </Field>

            <Field label="Vendor Address" optional>
              <input
                className="input"
                value={form.vendor_address || ""}
                onChange={(e) => setForm((p) => ({ ...p, vendor_address: e.target.value }))}
              />
            </Field>

            <div className="grid grid-cols-2 gap-3">
              <Field label="Buyer GSTIN" optional>
                <input
                  className="input"
                  value={form.buyer_gstin || ""}
                  onChange={(e) => setForm((p) => ({ ...p, buyer_gstin: e.target.value }))}
                />
              </Field>
              <Field label="Buyer Name" optional>
                <input
                  className="input"
                  value={form.buyer_name || ""}
                  onChange={(e) => setForm((p) => ({ ...p, buyer_name: e.target.value }))}
                />
              </Field>
            </div>

            <div className="grid grid-cols-3 gap-3">
              <Field label="Freight" optional>
                <input
                  className="input"
                  type="number"
                  step="0.01"
                  value={form.freight || 0}
                  onChange={(e) => setForm((p) => ({ ...p, freight: parseFloat(e.target.value) || 0 }))}
                />
              </Field>
              <Field label="Round Off" optional>
                <input
                  className="input"
                  type="number"
                  step="0.01"
                  value={form.round_off || 0}
                  onChange={(e) => setForm((p) => ({ ...p, round_off: parseFloat(e.target.value) || 0 }))}
                />
              </Field>
              <Field label="TDS" optional>
                <input
                  className="input"
                  type="number"
                  step="0.01"
                  value={form.tds_amount || 0}
                  onChange={(e) => setForm((p) => ({ ...p, tds_amount: parseFloat(e.target.value) || 0 }))}
                />
              </Field>
            </div>
          </div>
        )}

        {/* ===== TAB: Line Items ===== */}
        {activeTab === "items" && (
          <div>
            <div className="flex items-center justify-between mb-3">
              <label className="text-sm font-medium text-gray-300">Line Items</label>
              <button
                onClick={() => {
                  setForm((p) => ({
                    ...p,
                    line_items: [...(p.line_items || []), { description: "", quantity: 1, rate: 0, taxable_value: 0, tax_rate: 0, ledger_name: "" }],
                  }));
                  setLedgers((p) => [...p, ""]);
                }}
                className="premium-btn-secondary text-xs px-3 py-1.5"
              >
                + Add Item
              </button>
            </div>
            {errors.line_items && <p className="text-red-400 text-xs mb-2">{errors.line_items}</p>}
            {(form.line_items || []).map((item, i) => (
              <div
                key={i}
                className={`premium-card rounded-xl p-3 mb-2 space-y-2 border ${
                  !isHighConfidence() ? "border-yellow-500/15" : "border-white/5"
                } animate-fadeInUp`}
                style={{ animationDelay: `${i * 0.05}s` }}
              >
                <div className="flex justify-between items-center">
                  <span className="text-xs font-medium text-gray-500">Item {i + 1}</span>
                  <button
                    onClick={() => {
                      setForm((p) => ({ ...p, line_items: (p.line_items || []).filter((_, j) => j !== i) }));
                      setLedgers((p) => p.filter((_, j) => j !== i));
                    }}
                    className="text-xs text-red-400 hover:text-red-300"
                  >
                    Remove
                  </button>
                </div>
                <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                  <div className="col-span-full">
                    <label className="text-xs text-gray-500 mb-1 block">Description</label>
                    <input
                      className={`input text-sm ${form.confidence != null && form.confidence < 0.6 ? "border-yellow-500/30" : ""}`}
                      value={item.description}
                      onChange={(e) => {
                        const items = [...(form.line_items || [])];
                        items[i] = { ...items[i], description: e.target.value };
                        setForm((p) => ({ ...p, line_items: items }));
                      }}
                    />
                  </div>
                  <div>
                    <label className="text-xs text-gray-500 mb-1 block">Qty</label>
                    <input className="input text-sm" type="number" step="0.01" value={item.quantity}
                      onChange={(e) => {
                        const items = [...(form.line_items || [])];
                        items[i] = { ...items[i], quantity: e.target.value };
                        setForm((p) => ({ ...p, line_items: items }));
                      }} />
                  </div>
                  <div>
                    <label className="text-xs text-gray-500 mb-1 block">Rate</label>
                    <input className="input text-sm" type="number" step="0.01" value={item.rate}
                      onChange={(e) => {
                        const items = [...(form.line_items || [])];
                        items[i] = { ...items[i], rate: e.target.value };
                        setForm((p) => ({ ...p, line_items: items }));
                      }} />
                  </div>
                  <div>
                    <label className="text-xs text-gray-500 mb-1 block">Taxable</label>
                    <input className="input text-sm" type="number" step="0.01" value={item.taxable_value}
                      onChange={(e) => {
                        const items = [...(form.line_items || [])];
                        items[i] = { ...items[i], taxable_value: e.target.value };
                        setForm((p) => ({ ...p, line_items: items }));
                      }} />
                  </div>
                  <div>
                    <label className="text-xs text-gray-500 mb-1 block">Tax Rate %</label>
                    <input className="input text-sm" type="number" step="0.01" value={item.tax_rate}
                      onChange={(e) => {
                        const items = [...(form.line_items || [])];
                        items[i] = { ...items[i], tax_rate: e.target.value };
                        setForm((p) => ({ ...p, line_items: items }));
                      }} />
                  </div>
                  <div>
                    <label className="text-xs text-gray-500 mb-1 block">CGST</label>
                    <input className="input text-sm" type="number" step="0.01" value={item.cgst ?? ""}
                      onChange={(e) => {
                        const items = [...(form.line_items || [])];
                        items[i] = { ...items[i], cgst: e.target.value === "" ? null : e.target.value };
                        setForm((p) => ({ ...p, line_items: items }));
                      }} />
                  </div>
                  <div>
                    <label className="text-xs text-gray-500 mb-1 block">SGST</label>
                    <input className="input text-sm" type="number" step="0.01" value={item.sgst ?? ""}
                      onChange={(e) => {
                        const items = [...(form.line_items || [])];
                        items[i] = { ...items[i], sgst: e.target.value === "" ? null : e.target.value };
                        setForm((p) => ({ ...p, line_items: items }));
                      }} />
                  </div>
                  <div>
                    <label className="text-xs text-gray-500 mb-1 block">IGST</label>
                    <input className="input text-sm" type="number" step="0.01" value={item.igst ?? ""}
                      onChange={(e) => {
                        const items = [...(form.line_items || [])];
                        items[i] = { ...items[i], igst: e.target.value === "" ? null : e.target.value };
                        setForm((p) => ({ ...p, line_items: items }));
                      }} />
                  </div>
                  <div className="col-span-full">
                    <label className="text-xs text-gray-500 mb-1 block flex items-center gap-1">
                      Ledger <span className="text-red-400">*</span>
                      <span className="text-gray-600 font-normal">(required)</span>
                    </label>
                    <select
                      className="input text-sm"
                      value={ledgers[i] || ""}
                      onChange={(e) => {
                        const l = [...ledgers];
                        l[i] = e.target.value;
                        setLedgers(l);
                        if (e.target.value && form.vendor_name) {
                          saveVendorLedger(form.vendor_name, e.target.value, form.gstin);
                        }
                      }}
                    >
                      <option value="">-- Select ledger --</option>
                      {tallyLedgers.length > 0 && (
                        <optgroup label="Live From Tally Prime ERP">
                          {tallyLedgers.map((l) => <option key={l} value={l}>{l}</option>)}
                        </optgroup>
                      )}
                      <optgroup label="Common Ledgers">
                        {COMMON_LEDGERS.map((l) => <option key={l} value={l}>{l}</option>)}
                      </optgroup>
                    </select>
                    {ledgers[i] && (
                      <p className="text-[10px] text-green-400/70 mt-0.5">{'\u2713'} {ledgers[i]}</p>
                    )}
                  </div>
                </div>
              </div>
            ))}
            {(form.line_items || []).length > 0 && ledgers.some((l) => !l) && (
              <p className="text-xs text-yellow-400/70 mt-1 flex items-center gap-1">
                {'\u26A0'} Assign a ledger to each item before confirming
              </p>
            )}
          </div>
        )}

        {/* ===== TAB: Totals ===== */}
        {activeTab === "totals" && (
          <div className="space-y-2">
            <div className="premium-card-flat p-4 space-y-2">
              <div className="flex justify-between text-sm">
                <span className="text-gray-400">Total Taxable Value</span>
                <span className="text-gray-200 font-medium">{'\u20B9'}{totals.taxableTotal.toFixed(2)}</span>
              </div>
              <div className="flex justify-between text-sm">
                <span className="text-gray-400">CGST</span>
                <span className="text-blue-300 font-medium">{'\u20B9'}{totals.cgstTotal.toFixed(2)}</span>
              </div>
              <div className="flex justify-between text-sm">
                <span className="text-gray-400">SGST</span>
                <span className="text-blue-300 font-medium">{'\u20B9'}{totals.sgstTotal.toFixed(2)}</span>
              </div>
              <div className="flex justify-between text-sm">
                <span className="text-gray-400">IGST</span>
                <span className="text-blue-300 font-medium">{'\u20B9'}{totals.igstTotal.toFixed(2)}</span>
              </div>
              <div className="border-t border-white/5 pt-2 flex justify-between text-sm">
                <span className="text-gray-400">Total Tax</span>
                <span className="text-gray-200 font-medium">{'\u20B9'}{totals.taxTotal.toFixed(2)}</span>
              </div>
              <div className="flex justify-between text-sm">
                <span className="text-gray-400">Freight</span>
                <span className="text-gray-200 font-medium">{'\u20B9'}{totals.freight.toFixed(2)}</span>
              </div>
              <div className="flex justify-between text-sm">
                <span className="text-gray-400">Round Off</span>
                <span className="text-gray-200 font-medium">{'\u20B9'}{totals.roundOff.toFixed(2)}</span>
              </div>
              <div className="flex justify-between text-sm">
                <span className="text-gray-400">TDS</span>
                <span className="text-red-300 font-medium">-{'\u20B9'}{totals.tds.toFixed(2)}</span>
              </div>
              <div className="border-t border-indigo-500/30 pt-2 flex justify-between text-sm">
                <span className="text-gray-200 font-semibold">Grand Total</span>
                <span className="text-indigo-300 font-bold">{'\u20B9'}{totals.grandTotal.toFixed(2)}</span>
              </div>
            </div>

            {totals.grandTotal > 0 && parseFloat(form.total_amount || 0) > 0 && (
              <div className={`flex items-center gap-2 p-2 rounded-lg text-xs ${
                Math.abs(totals.grandTotal - parseFloat(form.total_amount)) <= 0.5
                  ? "bg-green-500/10 text-green-300"
                  : "bg-amber-500/10 text-amber-300"
              }`}>
                <span>{'\u26A0'}</span>
                <span>
                  Computed: {'\u20B9'}{totals.grandTotal.toFixed(2)} vs Header: {'\u20B9'}{parseFloat(form.total_amount).toFixed(2)}
                  {Math.abs(totals.grandTotal - parseFloat(form.total_amount)) <= 0.5
                    ? " (\u2713 within tolerance)"
                    : ""}
                </span>
              </div>
            )}

            {/* Masters Preview */}
            {showMastersPreview && mastersPreview && (
              <div className="premium-card-flat p-3 space-y-2 border border-indigo-500/20">
                <div className="flex items-center justify-between">
                  <h4 className="text-xs font-semibold text-indigo-300">Pre-Import Report</h4>
                  <button onClick={() => setShowMastersPreview(false)} className="text-xs text-gray-500 hover:text-gray-300">Hide</button>
                </div>

                {previewWarnings.length > 0 && (
                  <div className="space-y-1 mb-2">
                    {previewWarnings.map((w, i) => (
                      <WarningBanner key={i} warning={w} getAuthHeaders={getAuthHeaders} />
                    ))}
                  </div>
                )}

                <div className="flex items-center gap-2 text-xs text-gray-500 mb-1">
                  <span className="font-semibold text-indigo-300">{mastersPreview.length}</span> masters
                </div>
                <div className="space-y-1 max-h-36 overflow-y-auto">
                  {mastersPreview.map((m, i) => (
                    <div key={i} className="flex items-center gap-2 text-[11px]">
                      <span className={`px-1.5 py-0.5 rounded font-mono ${
                        m.type === "VoucherType" ? "text-purple-300 bg-purple-500/10"
                        : m.type === "StockItem" || m.type === "StockGroup" ? "text-emerald-300 bg-emerald-500/10"
                        : "text-cyan-300 bg-cyan-500/10"
                      }`}>{m.type}</span>
                      <span className="text-gray-200">{m.name}</span>
                      {m.parent && <span className="text-gray-500">{'\u2192'} {m.parent}</span>}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {/* Validation / Review Errors */}
        {validation && activeTab !== "totals" && (
          <div className="mt-3">
            {Object.entries(validation?.checks || {}).filter(([, c]) => !c.pass).slice(0, 3).map(([name, check]) => (
              <WarningBanner
                key={name}
                warning={{
                  type: name,
                  severity: "medium",
                  message: check.message,
                }}
                getAuthHeaders={getAuthHeaders}
              />
            ))}
          </div>
        )}

        {reviewErrors && (
          <div className="mt-3 bg-red-500/10 border border-red-500/20 rounded-xl p-3 space-y-1">
            <p className="text-xs font-medium text-red-400">Review Blocked</p>
            {reviewErrors.map((e, i) => (
              <p key={i} className="text-xs text-red-300/80 pl-2 border-l-2 border-red-500/30">{e}</p>
            ))}
          </div>
        )}

        {/* Actions */}
        <div className="flex gap-2 pt-3 flex-wrap">
          <button
            onClick={() => {
              doPreviewMasters();
              onPreviewMasters && onPreviewMasters();
            }}
            disabled={previewLoading}
            className="premium-btn-secondary text-xs px-3 py-2"
          >
            {previewLoading ? "Loading..." : "Preview Masters"}
          </button>

          {!reviewConfirmed ? (
            <button onClick={onReviewConfirm} disabled={submitting} className="premium-btn-primary flex-1 py-2.5 text-sm disabled:opacity-60 flex items-center justify-center gap-2">
              {submitting ? (<><span className="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin" />Confirming…</>) : "Review & Confirm"}
            </button>
          ) : (
            <>
              <button onClick={onDownloadXML} className="premium-btn-primary flex-1 py-2.5 text-sm">
                Download XML
              </button>
              <button disabled={submitting} onClick={onUndo} className="premium-btn-secondary text-xs px-3 py-2 border-yellow-500/40 text-yellow-400 hover:bg-yellow-500/10 disabled:opacity-60">
                Undo Review
              </button>
            </>
          )}

          <button onClick={onReset} className="premium-btn-secondary text-xs px-3 py-2">Clear</button>
        </div>
      </div>
    </div>
  );
}
