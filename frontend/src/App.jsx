import { lazy, Suspense, useState, useEffect, useRef } from "react";
import { BrowserRouter, Routes, Route, Navigate, useNavigate, useLocation } from "react-router-dom";
import { useAuth } from "./auth";
import gsap from "gsap";
import BACKEND from "./api/client";
import ErrorBoundary from "./components/ErrorBoundary";
import NavBar from "./components/NavBar";
import OfflineBanner from "./components/OfflineBanner";
import { useToast } from "./components/Toast";
import { ExtractProvider } from "./contexts/ExtractContext";

function OnboardingScreen({ user, onComplete }) {
  const { getAuthHeaders } = useAuth();
  const [step, setStep] = useState(1);
  const [userType, setUserType] = useState("");
  const [companyName, setCompanyName] = useState("");
  const [companyGstin, setCompanyGstin] = useState("");
  const [stateCode, setStateCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const STATE_CODES = [
    "01-Jammu & Kashmir", "02-Himachal Pradesh", "03-Punjab", "04-Chandigarh",
    "05-Uttarakhand", "06-Haryana", "07-Delhi", "08-Rajasthan", "09-Uttar Pradesh",
    "10-Bihar", "11-Sikkim", "12-Arunachal Pradesh", "13-Nagaland", "14-Manipur",
    "15-Mizoram", "16-Tripura", "17-Meghalaya", "18-Assam", "19-West Bengal",
    "20-Jharkhand", "21-Odisha", "22-Chhattisgarh", "23-Madhya Pradesh",
    "24-Gujarat", "25-Daman & Diu", "26-Dadra & Nagar Haveli", "27-Maharashtra",
    "28-Andhra Pradesh (Old)", "29-Karnataka", "30-Goa", "31-Lakshadweep",
    "32-Kerala", "33-Tamil Nadu", "34-Puducherry", "35-Andaman & Nicobar",
    "36-Telangana", "37-Andhra Pradesh (New)",
  ];

  async function handleComplete() {
    if (!companyName || !stateCode) {
      setError("Company name and state are required");
      return;
    }
    setBusy(true);
    try {
      await fetch(`${BACKEND}/api/v3/config`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...getAuthHeaders() },
        body: JSON.stringify({
          company_name: companyName,
          company_gstin: companyGstin.toUpperCase(),
          company_state_code: stateCode,
          user_type: userType,
        }),
      });
      onComplete();
    } catch (err) {
      setError("Failed to save: " + err.message);
    }
    setBusy(false);
  }

  return (
    <div className="min-h-screen flex items-center justify-center p-4">
      <div className="premium-card p-8 max-w-lg w-full space-y-6 animate-fadeInUp">
        {step === 1 && (
          <>
            <div className="text-center">
              <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center text-2xl font-bold text-white mx-auto mb-4">I</div>
              <h1 className="text-xl font-bold premium-gradient-text">Welcome to InvoSync</h1>
              <p className="text-sm text-gray-400 mt-2">Let's set up your account in 30 seconds</p>
            </div>
            <div>
              <label className="text-xs text-gray-500 mb-2 block">I am a</label>
              <div className="flex gap-3">
                <button type="button" className={`flex-1 py-4 px-4 rounded-lg border text-sm font-medium transition-all ${userType === "ca_firm" ? "bg-indigo-500/20 border-indigo-500/50 text-indigo-300" : "bg-white/5 border-white/10 text-gray-400 hover:border-white/20"}`} onClick={() => setUserType("ca_firm")}>
                  CA Firm
                  <span className="block text-[10px] font-normal mt-1 opacity-70">Manage multiple clients</span>
                </button>
                <button type="button" className={`flex-1 py-4 px-4 rounded-lg border text-sm font-medium transition-all ${userType === "msme" ? "bg-green-500/20 border-green-500/50 text-green-300" : "bg-white/5 border-white/10 text-gray-400 hover:border-white/20"}`} onClick={() => setUserType("msme")}>
                  MSME / Business
                  <span className="block text-[10px] font-normal mt-1 opacity-70">My own company</span>
                </button>
              </div>
            </div>
            <button disabled={!userType} className="premium-btn-primary w-full py-3" onClick={() => setStep(2)}>Continue</button>
          </>
        )}
        {step === 2 && (
          <>
            <h2 className="text-lg font-bold premium-gradient-text">Company Details</h2>
            <p className="text-sm text-gray-400">These settings are used for all invoices and XML generation.</p>
            <div>
              <label className="text-xs text-gray-500 mb-1 block">Company Name (as in Tally) *</label>
              <input className="premium-input w-full" value={companyName} onChange={(e) => setCompanyName(e.target.value)} placeholder="e.g. My Firm & Co." />
            </div>
            <div>
              <label className="text-xs text-gray-500 mb-1 block">Company GSTIN (optional)</label>
              <input className="premium-input w-full font-mono" value={companyGstin} onChange={(e) => setCompanyGstin(e.target.value.toUpperCase())} placeholder="e.g. 27AABCU1234F1ZP" maxLength={15} />
            </div>
            <div>
              <label className="text-xs text-gray-500 mb-1 block">State *</label>
              <select className="premium-input w-full" value={stateCode} onChange={(e) => setStateCode(e.target.value)}>
                <option value="">-- Select your state --</option>
                {STATE_CODES.map((s) => <option key={s} value={s.slice(0,2)}>{s}</option>)}
              </select>
            </div>
            {error && <p className="text-red-400 text-sm">{error}</p>}
            <div className="flex gap-3">
              <button className="premium-btn-secondary py-3 px-6" onClick={() => setStep(1)}>Back</button>
              <button disabled={busy || !companyName || !stateCode} className="premium-btn-primary flex-1 py-3" onClick={handleComplete}>
                {busy ? "Setting up..." : "Start Using InvoSync"}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

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
const DiffViewPage = lazy(() => import("./pages/DiffViewPage"));
const BurnDashboard = lazy(() => import("./pages/BurnDashboard"));
const FirmDashboard = lazy(() => import("./pages/FirmDashboard"));

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
  const [tallyStatus, setTallyStatus] = useState(null);

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

  const pageRef = useRef(null);
  useEffect(() => {
    if (pageRef.current) {
      gsap.fromTo(pageRef.current,
        { opacity: 0, y: 20 },
        { opacity: 1, y: 0, duration: 0.4, ease: "power2.out" }
      );
    }
  }, [location.pathname]);

  const handleEditInvoice = (invId) => {
    navigate(`/extract?id=${invId}`);
  };

  if (!user) return <LoginScreen />;

  const needsOnboarding = !user.company_name && !user.user_type;

  return (
    <>
      <OfflineBanner />
      {!needsOnboarding && <NavBar tallyStatus={tallyStatus} />}
      <div className="premium-page" ref={pageRef}>
        <Suspense fallback={<LoadingSpinner />}>
          {needsOnboarding ? (
            <OnboardingScreen user={user} onComplete={() => { refreshUser(); }} />
          ) : (
          <Routes>
            <Route path="/" element={<Navigate to="/extract" replace />} />
            <Route path="/extract" element={
              <ErrorBoundary>
                <ExtractProvider>
                  <ExtractPage />
                </ExtractProvider>
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
            <Route path="/reports/diff" element={
              <ErrorBoundary><DiffViewPage /></ErrorBoundary>
            } />
            <Route path="/firm" element={
              <ErrorBoundary><FirmDashboard /></ErrorBoundary>
            } />
            <Route path="/admin/burn" element={
              <ErrorBoundary><BurnDashboard /></ErrorBoundary>
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
          )}
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
