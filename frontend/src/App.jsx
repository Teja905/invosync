import { useState, useEffect, useRef, lazy, Suspense } from "react";
import { useAuth } from "./auth";
import gsap from "gsap";
import BACKEND from "./api/client";
import ErrorBoundary from "./components/ErrorBoundary";
import NavBar from "./components/NavBar";
import OfflineBanner from "./components/OfflineBanner";
import { useToast } from "./components/Toast";

const ExtractPage = lazy(() => import("./pages/ExtractPage"));
const ClientsPage = lazy(() => import("./pages/ClientsPage"));
const DashboardPage = lazy(() => import("./pages/DashboardPage"));
const AdminPage = lazy(() => import("./pages/AdminPage"));
const SettingsPage = lazy(() => import("./pages/SettingsPage"));
const BankingPage = lazy(() => import("./pages/BankingPage"));
const LearningPage = lazy(() => import("./pages/LearningPage"));

export default function App() {
  const { user, getAuthHeaders } = useAuth();
  const toast = useToast();
  const [page, setPage] = useState("extract");
  const [refreshKey, setRefreshKey] = useState(0);
  const [currentId, setCurrentId] = useState(null);
  const [selectedClient, setSelectedClient] = useState("");
  const [tallyStatus, setTallyStatus] = useState(null);
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
      toast.error("Error loading invoice: " + e.message);
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
      <OfflineBanner />
      <NavBar active={page} onChange={(p) => { setPage(p); if (p === "dashboard") setRefreshKey((k) => k + 1); if (p === "clients") setRefreshKey((k) => k + 1); }} tallyStatus={tallyStatus} />
      <div className="premium-page" ref={pageRef}>
        <Suspense fallback={<div className="premium-card animate-pulse p-8 text-center opacity-60">Loading…</div>}>
        {page === "extract" ? (
          <ErrorBoundary key="extract"><ExtractPage form={form} setForm={setForm} currentId={currentId} setCurrentId={setCurrentId} selectedClient={selectedClient} setSelectedClient={setSelectedClient} ledgers={ledgers} setLedgers={setLedgers} reviewConfirmed={reviewConfirmed} setReviewConfirmed={setReviewConfirmed} reviewErrors={reviewErrors} setReviewErrors={setReviewErrors} /></ErrorBoundary>
        ) : page === "clients" ? (
          <ErrorBoundary key="clients"><ClientsPage refreshKey={refreshKey} /></ErrorBoundary>
        ) : page === "banking" ? (
          <ErrorBoundary key="banking"><BankingPage /></ErrorBoundary>
        ) : page === "learning" ? (
          <ErrorBoundary key="learning"><LearningPage /></ErrorBoundary>
        ) : page === "settings" ? (
          <ErrorBoundary key="settings"><SettingsPage /></ErrorBoundary>
        ) : (
          <ErrorBoundary key="dashboard"><DashboardPage refreshKey={refreshKey} setRefreshKey={setRefreshKey} onEditInvoice={handleEditInvoice} /></ErrorBoundary>
        )}
        </Suspense>
      </div>
    </div>
    </ErrorBoundary>
  );
}
