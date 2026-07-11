import { createContext, useContext } from "react";

const BACKEND = import.meta.env.VITE_API_URL || (
  window.location.hostname === "localhost" ? "" : "https://invosync-backend-yjfa.onrender.com"
);
const AuthContext = createContext(null);

const DEFAULT_USER = {
  email: "default@local",
  name: "Default User",
  role: "admin",
  company_name: "",
  company_gstin: "",
  company_state_code: "",
  purchase_ledger: "Purchase",
  sales_ledger: "Sales",
  bank_ledger: "Bank",
  tds_ledger: "TDS Payable",
  round_off_ledger: "Round Off",
  freight_ledger: "Freight Expenses",
  suspense_ledger: "Suspense",
  sundry_creditors_group: "Sundry Creditors",
  sundry_debtors_group: "Sundry Debtors",
  purchase_accounts_group: "Purchase Accounts",
  sales_accounts_group: "Sales Accounts",
  bank_accounts_group: "Bank Accounts",
  current_liabilities_group: "Current Liabilities",
  duties_taxes_group: "Duties & Taxes",
};

export function AuthProvider({ children }) {
  const ctx = {
    user: DEFAULT_USER,
    loading: false,
    login: async () => DEFAULT_USER,
    signup: async () => DEFAULT_USER,
    logout: () => {},
    getAuthHeaders: () => ({}),
    refreshUser: async () => {},
    BACKEND,
  };
  return <AuthContext.Provider value={ctx}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  return useContext(AuthContext);
}
