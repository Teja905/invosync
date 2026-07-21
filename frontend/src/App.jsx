import { lazy, Suspense, useState, useEffect, useRef } from "react";
import { BrowserRouter, Routes, Route, Navigate, useNavigate, useLocation } from "react-router-dom";
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
const TrialBalancePage = lazy(() => import("./pages/TrialBalancePage"));
const PnLPage = lazy(() => import("./pages/PnLPage"));
const BalanceSheetPage = lazy(() => import("./pages/BalanceSheetPage"));
const BillingPage = lazy(() => import("./pages/BillingPage"));
const ClientLoginPage = lazy(() => import("./pages/ClientLoginPage"));
const ClientDashboardPage = lazy(() => import("./pages/ClientDashboardPage"));

function LoadingSpinner() {
  return (
    <div className="flex items-center justify-center min-h-[60vh]">
      <div className="text-gray-400 text-sm animate-pulse">Loading...</div>
    </div>
  );
}

function LoginScreen() {
  const { login, signup } = useAuth();
  const toast = useToast();
  const [isSignup, setIsSignup] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e) {
    e.preventDefault();
    setLoading(true);
    try {
      if (isSignup) {
        await signup(email, password, name);
        toast.success("Account created!");
      } else {
        await login(email, password);
        toast.success("Logged in!");
      }
    } catch (err) {
      toast.error(err.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center p-4">
      <div className="premium-card-flat p-8 w-full max-w-md space-y-6">
        <div className="text-center">
          <div className="premium-logo-icon mx-auto mb-2">I</div>
          <h1 className="text-xl font-semibold text-white">InvoSync</h1>
          <p className="text-gray-400 text-sm mt-1">Invoice to Tally XML</p>
        </div>
        <form onSubmit={handleSubmit} className="space-y-4">
          {isSignup && (
            <input type="text" placeholder="Full Name" value={name} onChange={(e) => setName(e.target.value)}
              className="premium-input w-full" required />
          )}
          <input type="email" placeholder="Email" value={email} onChange={(e) => setEmail(e.target.value)}
            className="premium-input w-full" required />
          <input type="password" placeholder="Password (min 8 chars, 1 uppercase, 1 number)" value={password}
            onChange={(e) => setPassword(e.target.value)} className="premium-input w-full" required minLength={8} />
          <button type="submit" disabled={loading} className="premium-btn-primary w-full py-2.5">
            {loading ? "Please wait..." : isSignup ? "Create Account" : "Sign In"}
          </button>
        </form>
        <button onClick={() => setIsSignup(!isSignup)}
          className="text-gray-400 text-sm hover:text-white transition-colors w-full text-center">
          {isSignup ? "Already have an account? Sign in" : "Don't have an account? Sign up"}
        </button>
      </div>
    </div>
  );
}

function AppInner() {
  const navigate = useNavigate();
  const location = useLocation();
  const { user, getAuthHeaders } = useAuth();
  const toast = useToast();
  const [refreshKey, setRefreshKey] = useState(0);
  const [currentId, setCurrentId] = useState(null);
  const [selectedClient, setSelectedClient] = useState("");
  const [tallyStatus, setTallyStatus] = useState(null);
  const [ledgers, setLedgers] = useState([]);
  const [reviewConfirmed, setReviewConfirmed] = useState(false);
  const [reviewErrors, setReviewErrors] = useState(null);
  const [form, setForm] = useState({
    gstin: "", invoice_number: "", date: "", total_amount: "",
    vendor_name: "", vendor_address: "", buyer_gstin: "", buyer_name: "",
    confidence: null, line_items: [],
  });

  useEffect(() => {
    if (location.pathname === "/dashboard" || location.pathname === "/clients") {
      setRefreshKey((k) => k + 1);
    }
  }, [location.pathname]);

  useEffect(() => {
    if (!user) return;
    fetch(`${BACKEND}/api/v3/tally/status`, { headers: getAuthHeaders() })
      .then((r) => r.json()).then(setTallyStatus).catch(() => {});
    const interval = setInterval(() => {
      fetch(`${BACKEND}/api/v3/tally/status`, { headers: getAuthHeaders() })
        .then((r) => r.json()).then(setTallyStatus).catch(() => {});
    }, 30000);
    return () => clearInterval(interval);
  }, [user]);

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
      navigate("/extract");
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
  }, [location.pathname]);

  if (!user) return <LoginScreen />;

  return (
    <>
      <OfflineBanner />
      <NavBar tallyStatus={tallyStatus} />
      <div className="premium-page" ref={pageRef}>
        <Suspense fallback={<LoadingSpinner />}>
          <Routes>
            <Route path="/" element={<Navigate to="/extract" replace />} />
            <Route path="/extract" element={
              <ErrorBoundary>
                <ExtractPage form={form} setForm={setForm} currentId={currentId} setCurrentId={setCurrentId}
                  selectedClient={selectedClient} setSelectedClient={setSelectedClient}
                  ledgers={ledgers} setLedgers={setLedgers}
                  reviewConfirmed={reviewConfirmed} setReviewConfirmed={setReviewConfirmed}
                  reviewErrors={reviewErrors} setReviewErrors={setReviewErrors} />
              </ErrorBoundary>
            } />
            <Route path="/dashboard" element={
              <ErrorBoundary>
                <DashboardPage refreshKey={refreshKey} setRefreshKey={setRefreshKey} onEditInvoice={handleEditInvoice} />
              </ErrorBoundary>
            } />
            <Route path="/clients" element={
              <ErrorBoundary>
                <ClientsPage refreshKey={refreshKey} />
              </ErrorBoundary>
            } />
            <Route path="/banking" element={
              <ErrorBoundary><BankingPage /></ErrorBoundary>
            } />
            <Route path="/learning" element={
              <ErrorBoundary><LearningPage /></ErrorBoundary>
            } />
            <Route path="/settings" element={
              <ErrorBoundary><SettingsPage /></ErrorBoundary>
            } />
            <Route path="/admin" element={
              <ErrorBoundary><AdminPage /></ErrorBoundary>
            } />
            <Route path="/reports/trial-balance" element={
              <ErrorBoundary><TrialBalancePage /></ErrorBoundary>
            } />
            <Route path="/reports/pnl" element={
              <ErrorBoundary><PnLPage /></ErrorBoundary>
            } />
            <Route path="/reports/balance-sheet" element={
              <ErrorBoundary><BalanceSheetPage /></ErrorBoundary>
            } />
            <Route path="/billing" element={
              <ErrorBoundary><BillingPage /></ErrorBoundary>
            } />
            <Route path="/client/login" element={
              <ErrorBoundary><ClientLoginPage /></ErrorBoundary>
            } />
            <Route path="/client/dashboard" element={
              <ErrorBoundary><ClientDashboardPage /></ErrorBoundary>
            } />
            <Route path="*" element={<Navigate to="/extract" replace />} />
          </Routes>
        </Suspense>
      </div>
    </>
  );
}

export default function App() {
  return (
    <ErrorBoundary>
      <BrowserRouter>
        <AppInner />
      </BrowserRouter>
    </ErrorBoundary>
  );
}
