import { createContext, useContext, useState, useEffect, useCallback, useRef } from "react";

const BACKEND = import.meta.env.VITE_API_URL || (
  window.location.hostname === "localhost" ? "" : "https://invosync-backend-yjfa.onrender.com"
);
const AuthContext = createContext(null);

const TOKEN_KEY = "invosync_token";
const REFRESH_KEY = "invosync_refresh";
const USER_KEY = "invosync_user";

function loadToken() {
  try { return localStorage.getItem(TOKEN_KEY); } catch { return null; }
}

function loadRefreshToken() {
  try { return localStorage.getItem(REFRESH_KEY); } catch { return null; }
}

function loadUser() {
  try {
    const raw = localStorage.getItem(USER_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch { return null; }
}

/**
 * Persist session. Always pass three args: access token, refresh token (or null), user object.
 * Never pass a user object as the refresh token — that corrupted sessions on /auth/me restore.
 */
function saveSession(token, refreshToken, user) {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    if (refreshToken) localStorage.setItem(REFRESH_KEY, refreshToken);
    if (user != null) localStorage.setItem(USER_KEY, JSON.stringify(user));
  } catch {}
}

function clearSession() {
  try {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(REFRESH_KEY);
    localStorage.removeItem(USER_KEY);
  } catch {}
}

export function AuthProvider({ children }) {
  const [user, setUser] = useState(() => loadUser());
  const [token, setToken] = useState(() => loadToken());
  const [loading, setLoading] = useState(true);
  const refreshInFlight = useRef(null);

  useEffect(() => {
    const storedToken = loadToken();
    if (!storedToken) { setLoading(false); return; }
    fetch(`${BACKEND}/auth/me`, { headers: { Authorization: `Bearer ${storedToken}` } })
      .then((r) => {
        if (!r.ok) throw new Error("Invalid");
        return r.json();
      })
      .then((data) => {
        setUser(data);
        setToken(storedToken);
        // Preserve existing refresh token; only update user profile
        saveSession(storedToken, loadRefreshToken(), data);
      })
      .catch(async () => {
        // Access token may be expired — try refresh once before logout
        const rt = loadRefreshToken();
        if (rt) {
          try {
            const res = await fetch(`${BACKEND}/auth/refresh`, {
              method: "POST",
              headers: { Authorization: `Bearer ${rt}` },
            });
            if (res.ok) {
              const data = await res.json();
              const existingUser = loadUser();
              saveSession(data.token, data.refresh_token || rt, existingUser);
              setToken(data.token);
              // Re-fetch profile with new token
              const me = await fetch(`${BACKEND}/auth/me`, {
                headers: { Authorization: `Bearer ${data.token}` },
              });
              if (me.ok) {
                const profile = await me.json();
                setUser(profile);
                saveSession(data.token, data.refresh_token || rt, profile);
                setLoading(false);
                return;
              }
            }
          } catch {}
        }
        clearSession();
        setToken(null);
        setUser(null);
      })
      .finally(() => setLoading(false));
  }, []);

  const login = useCallback(async (email, password) => {
    const res = await fetch(`${BACKEND}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Login failed");
    }
    const data = await res.json();
    saveSession(data.token, data.refresh_token, data.user);
    setToken(data.token);
    setUser(data.user);
    return data.user;
  }, []);

  const signup = useCallback(async (email, password, name) => {
    const res = await fetch(`${BACKEND}/auth/signup`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password, name }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Signup failed");
    }
    const data = await res.json();
    saveSession(data.token, data.refresh_token, data.user);
    setToken(data.token);
    setUser(data.user);
    return data.user;
  }, []);

  const refreshAccessToken = useCallback(async () => {
    // Deduplicate concurrent refresh calls (Suvit-class session stickiness)
    if (refreshInFlight.current) return refreshInFlight.current;

    refreshInFlight.current = (async () => {
      const rt = loadRefreshToken();
      if (!rt) return false;
      try {
        const res = await fetch(`${BACKEND}/auth/refresh`, {
          method: "POST",
          headers: { Authorization: `Bearer ${rt}` },
        });
        if (!res.ok) return false;
        const data = await res.json();
        const currentUser = loadUser();
        saveSession(data.token, data.refresh_token || rt, currentUser);
        setToken(data.token);
        return true;
      } catch {
        return false;
      } finally {
        refreshInFlight.current = null;
      }
    })();

    return refreshInFlight.current;
  }, []);

  const logout = useCallback(() => {
    clearSession();
    setToken(null);
    setUser(null);
  }, []);

  const getAuthHeaders = useCallback(() => {
    const t = token || loadToken();
    if (!t) return {};
    return { Authorization: `Bearer ${t}` };
  }, [token]);

  const hasRole = useCallback((role) => {
    return user?.role === role;
  }, [user]);

  const refreshUser = useCallback(async () => {
    const t = token || loadToken();
    if (!t) return;
    try {
      const res = await fetch(`${BACKEND}/auth/me`, { headers: { Authorization: `Bearer ${t}` } });
      if (res.ok) {
        const data = await res.json();
        setUser(data);
        saveSession(t, loadRefreshToken(), data);
      }
    } catch {}
  }, [token]);

  /**
   * Authenticated fetch with automatic 401 → refresh → retry once.
   * Use this for all API calls that need a stable CA session.
   */
  const authFetch = useCallback(async (path, options = {}) => {
    const url = path.startsWith("http") ? path : `${BACKEND}${path}`;
    const headers = {
      ...(options.headers || {}),
      ...getAuthHeaders(),
    };
    let res = await fetch(url, { ...options, headers });
    if (res.status === 401) {
      const ok = await refreshAccessToken();
      if (ok) {
        const retryHeaders = {
          ...(options.headers || {}),
          ...getAuthHeaders(),
        };
        res = await fetch(url, { ...options, headers: retryHeaders });
      }
    }
    return res;
  }, [getAuthHeaders, refreshAccessToken]);

  const ctx = {
    user,
    token,
    loading,
    isAuthenticated: !!user,
    login,
    signup,
    logout,
    getAuthHeaders,
    hasRole,
    refreshUser,
    refreshAccessToken,
    authFetch,
    BACKEND,
  };

  return <AuthContext.Provider value={ctx}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  return useContext(AuthContext);
}
