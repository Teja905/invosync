export default function ManualEntryModal({ show, onClose, manualForm, setManualForm, onSubmit }) {
  if (!show) return null;

  function validateGstinFormat(gstin) {
    return /^\d{2}[A-Z]{5}\d{4}[A-Z]\d[Z][A-Z\d]$/.test(gstin);
  }

  function updateTaxFromRate() {
    const rate = parseFloat(manualForm.tax_rate) || 0;
    const taxable = parseFloat(manualForm.taxable_amount || manualForm.total_amount) || 0;
    const tax = taxable * rate / 100;
    setManualForm((p) => ({
      ...p,
      taxable_amount: taxable ? String(taxable) : p.taxable_amount,
      cgst: "", sgst: "", igst: "",
    }));
  }

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4" onClick={onClose}>
      <div className="premium-card-flat rounded-xl p-6 w-full max-w-lg max-h-[90vh] overflow-y-auto space-y-4" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-gray-200">Manual Data Entry</h3>
          <button onClick={onClose} className="text-gray-500 hover:text-gray-300 text-sm">✕</button>
        </div>
        <p className="text-xs text-gray-400">Extraction failed. Enter invoice details manually.</p>
        <div className="space-y-3">
          <div>
            <label className="text-xs text-gray-500 mb-1 block">Vendor Name *</label>
            <input className="input text-sm w-full" value={manualForm.vendor_name}
              onChange={(e) => setManualForm((p) => ({ ...p, vendor_name: e.target.value }))} />
          </div>
          <div>
            <label className="text-xs text-gray-500 mb-1 block">Vendor GSTIN</label>
            <div className="flex items-center gap-2">
              <input className="input text-sm flex-1" value={manualForm.gstin}
                onChange={(e) => {
                  const v = e.target.value.toUpperCase();
                  setManualForm((p) => ({ ...p, gstin: v, gstin_valid: validateGstinFormat(v) }));
                }}
                placeholder="15-char GSTIN" maxLength={15} />
              {manualForm.gstin && (
                <span className={`text-xs ${manualForm.gstin_valid ? "text-green-400" : "text-red-400"}`}>
                  {manualForm.gstin_valid ? "Valid" : "Invalid"}
                </span>
              )}
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-gray-500 mb-1 block">Invoice Number *</label>
              <input className="input text-sm w-full" value={manualForm.invoice_number}
                onChange={(e) => setManualForm((p) => ({ ...p, invoice_number: e.target.value }))} />
            </div>
            <div>
              <label className="text-xs text-gray-500 mb-1 block">Date *</label>
              <input className="input text-sm w-full" type="date" value={manualForm.date}
                onChange={(e) => setManualForm((p) => ({ ...p, date: e.target.value }))} />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-gray-500 mb-1 block">Total Amount *</label>
              <input className="input text-sm w-full" type="number" step="0.01" value={manualForm.total_amount}
                onChange={(e) => setManualForm((p) => ({ ...p, total_amount: e.target.value }))} />
            </div>
            <div>
              <label className="text-xs text-gray-500 mb-1 block">Taxable Amount</label>
              <input className="input text-sm w-full" type="number" step="0.01" value={manualForm.taxable_amount}
                onChange={(e) => setManualForm((p) => ({ ...p, taxable_amount: e.target.value }))}
                placeholder="defaults to total" />
            </div>
          </div>
          <div className="grid grid-cols-4 gap-2">
            <div>
              <label className="text-xs text-gray-500 mb-1 block">Tax %</label>
              <input className="input text-sm" type="number" step="0.01" value={manualForm.tax_rate}
                onChange={(e) => setManualForm((p) => ({ ...p, tax_rate: e.target.value }))}
                onBlur={updateTaxFromRate} />
            </div>
            <div>
              <label className="text-xs text-gray-500 mb-1 block">CGST</label>
              <input className="input text-sm" type="number" step="0.01" value={manualForm.cgst}
                onChange={(e) => setManualForm((p) => ({ ...p, cgst: e.target.value }))} />
            </div>
            <div>
              <label className="text-xs text-gray-500 mb-1 block">SGST</label>
              <input className="input text-sm" type="number" step="0.01" value={manualForm.sgst}
                onChange={(e) => setManualForm((p) => ({ ...p, sgst: e.target.value }))} />
            </div>
            <div>
              <label className="text-xs text-gray-500 mb-1 block">IGST</label>
              <input className="input text-sm" type="number" step="0.01" value={manualForm.igst}
                onChange={(e) => setManualForm((p) => ({ ...p, igst: e.target.value }))} />
            </div>
          </div>
          <div>
            <label className="text-xs text-gray-500 mb-1 block">Item Description *</label>
            <input className="input text-sm w-full" value={manualForm.line_items[0]?.description || ""}
              onChange={(e) => {
                const items = [...manualForm.line_items];
                items[0] = { ...items[0], description: e.target.value, taxable_value: manualForm.taxable_amount || manualForm.total_amount || 0 };
                setManualForm((p) => ({ ...p, line_items: items }));
              }} />
          </div>
          <div className="grid grid-cols-3 gap-2">
            <div>
              <label className="text-xs text-gray-500 mb-1 block">Qty</label>
              <input className="input text-sm" type="number" step="0.01" value={manualForm.line_items[0]?.quantity || 1}
                onChange={(e) => {
                  const items = [...manualForm.line_items];
                  items[0] = { ...items[0], quantity: e.target.value };
                  setManualForm((p) => ({ ...p, line_items: items }));
                }} />
            </div>
            <div>
              <label className="text-xs text-gray-500 mb-1 block">Rate</label>
              <input className="input text-sm" type="number" step="0.01" value={manualForm.line_items[0]?.rate || ""}
                onChange={(e) => {
                  const items = [...manualForm.line_items];
                  items[0] = { ...items[0], rate: e.target.value };
                  setManualForm((p) => ({ ...p, line_items: items }));
                }} />
            </div>
            <div>
              <label className="text-xs text-gray-500 mb-1 block">Amount</label>
              <input className="input text-sm" type="number" step="0.01" value={manualForm.line_items[0]?.taxable_value || ""}
                onChange={(e) => {
                  const items = [...manualForm.line_items];
                  items[0] = { ...items[0], taxable_value: e.target.value };
                  setManualForm((p) => ({ ...p, line_items: items }));
                }} />
            </div>
          </div>
        </div>
        <div className="flex gap-2 pt-2">
          <button onClick={onSubmit}
            disabled={!manualForm.vendor_name || !manualForm.invoice_number || !manualForm.date || !manualForm.total_amount}
            className="premium-btn-primary flex-1 py-2 text-sm disabled:opacity-50">
            Save & Continue
          </button>
          <button onClick={onClose} className="premium-btn-secondary px-4 py-2 text-sm">
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}
