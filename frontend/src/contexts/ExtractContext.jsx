import { useState, useCallback, useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../auth";
import BACKEND from "../api/client";
import { useToast } from "../components/Toast";

const ExtractContext = createContext(null);

export function ExtractProvider({ children }) {
  const navigate = useNavigate();
  const { user, getAuthHeaders } = useAuth();
  const toast = useToast();

  const [form, setForm] = useState({
    gstin: "", invoice_number: "", date: "", total_amount: "",
    vendor_name: "", vendor_address: "", buyer_gstin: "", buyer_name: "",
    confidence: null, ind_confidence: null, line_items: [], voucher_type: "Purchase",
    freight: 0, round_off: 0, tds_amount: 0,
    _provider: "", _model: "",
  });
  const [currentId, setCurrentId] = useState(null);
  const [selectedClient, setSelectedClient] = useState("");
  const [ledgers, setLedgers] = useState([]);
  const [reviewConfirmed, setReviewConfirmed] = useState(false);
  const [reviewErrors, setReviewErrors] = useState(null);

  const editInvoice = useCallback(async (invId) => {
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
      navigate("/extract");
    } catch (e) {
      toast.error("Error loading invoice: " + e.message);
    }
  }, [navigate, toast, getAuthHeaders]);

  const resetForm = useCallback(() => {
    setForm({
      gstin: "", invoice_number: "", date: "", total_amount: "",
      vendor_name: "", vendor_address: "", buyer_gstin: "", buyer_name: "",
      confidence: null, ind_confidence: null, line_items: [], voucher_type: "Purchase",
      freight: 0, round_off: 0, tds_amount: 0,
      _provider: "", _model: "",
    });
    setCurrentId(null);
    setLedgers([]);
    setReviewConfirmed(false);
    setReviewErrors(null);
  }, []);

  const value = {
    user, getAuthHeaders,
    form, setForm, currentId, setCurrentId, selectedClient, setSelectedClient,
    ledgers, setLedgers, reviewConfirmed, setReviewConfirmed, reviewErrors, setReviewErrors,
    editInvoice, resetForm,
  };

  return <ExtractContext.Provider value={value}>{children}</ExtractContext.Provider>;
}

export function useExtract() {
  const ctx = useContext(ExtractContext);
  if (!ctx) throw new Error("useExtract must be used within ExtractProvider");
  return ctx;
}
