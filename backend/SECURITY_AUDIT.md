# InvoSync Security Audit Report
**Date:** 2026-07-13  
**Auditor:** Kilo  
**Scope:** Backend, Frontend, Tally Connector  

---

## Executive Summary

| Category | Status | Risk |
|----------|--------|------|
| Authentication | ⚠️ Optional by default | High |
| Authorization | ✅ Per-user checks | Low |
| Audit Logging | ✅ Implemented | Low |
| Secret Management | ⚠️ Weak defaults | High |
| Encryption at Rest | ✅ Implemented | Low |
| Rate Limiting | ✅ Implemented | Low |
| CORS | ✅ Configurable | Low |
| Input Validation | ✅ Pydantic + magic bytes | Low |
| Dependency Security | ⚠️ Known vulns | Medium |
| Backup Security | ✅ Encrypted + rotation | Low |
| Session Security | ⚠️ Plaintext on disk | Medium |
| Frontend Security | ⚠️ No auth implemented | High |

---

## Critical Findings (Fix Before Production)

### 1. JWT_SECRET Weak Default
**File:** `backend/auth.py:15`  
**Risk:** High  
**Issue:** Default JWT secret is `"dev-secret-change-in-production"`. If `JWT_SECRET` env var is not set, anyone can forge tokens.  
**Fix:** ✅ Implemented — auto-geners ephemeral secret if missing, warns if using known default.

### 2. Authentication Disabled by Default
**File:** `backend/main.py:55`  
**Risk:** High  
**Issue:** `AUTH_ENABLED` defaults to `False`. All endpoints are publicly accessible without authentication.  
**Fix:** ✅ Implemented — `_PRODUCTION_MODE` now requires auth. Set `AUTH_ENABLED=true` in production.

### 3. Tally Password Plaintext in DB
**File:** `backend/main.py:2179`  
**Risk:** High  
**Issue:** `tally_password` stored in plaintext in MongoDB.  
**Fix:** ✅ Implemented — `tally_password` encrypted with Fernet before DB storage, decrypted on read.

### 4. Session Tokens Plaintext on Disk
**File:** `tally-connector/.../SessionManager.cs`  
**Risk:** Medium  
**Issue:** JWT tokens stored as plaintext JSON in `%APPDATA%/InvoSync/session.json`.  
**Fix:** ✅ Implemented — uses Windows DPAPI (`ProtectedData.Protect/Unprotect`) for per-user encryption.

---

## High Findings (Fix Soon)

### 5. Password Policy Too Weak
**File:** `backend/auth.py:134`  
**Risk:** Medium  
**Issue:** Only requires 6 characters, no complexity.  
**Fix:** ✅ Implemented — min 8 chars, requires uppercase + number.

### 6. No Audit Logging
**File:** `backend/` (multiple)  
**Risk:** Medium  
**Issue:** No structured audit trail for sensitive operations (login, extraction, sync, config changes).  
**Fix:** ✅ Implemented — `audit_log.py` with `AuditLogger` class. Integrated into auth, invoice, sync, correction, and config endpoints.

### 7. Frontend Auth Not Implemented
**File:** `frontend/src/auth.jsx`  
**Risk:** High  
**Issue:** `AuthProvider` always returns `DEFAULT_USER` with no real login/logout. `getAuthHeaders()` returns `{}`.  
**Impact:** If `AUTH_ENABLED=true`, frontend cannot authenticate.  
**Recommendation:** Implement real JWT login flow in frontend before enabling auth in production.

---

## Medium Findings (Address in Next Sprint)

### 8. No Rate Limiting per User
**File:** `backend/main.py:112`  
**Issue:** Rate limiting is IP-based only. A single user with multiple IPs bypasses limits.  
**Recommendation:** Add per-user rate limiting in addition to IP-based.

### 9. Dependency Vulnerability
**File:** `tally-connector/InvoSyncTallyConnector.csproj`  
**Issue:** `SQLitePCLRaw.lib.e_sqlite3` 2.1.10 has known high-severity vulnerability (GHSA-2m69-gcr7-jv3q).  
**Recommendation:** Update to latest SQLite package or replace with `Microsoft.Data.Sqlite`.

### 10. No Backup Verification
**File:** `scripts/backup_schedule.py`  
**Issue:** Backups are created but never verified for integrity or restorability.  
**Recommendation:** Add periodic restore test (weekly) to verify backups are usable.

### 11. No CSRF Protection
**File:** `backend/main.py`  
**Issue:** No CSRF tokens. Since API uses JWT in Authorization header, CSRF risk is low, but if cookies are ever used, this becomes critical.  
**Recommendation:** Document that auth must use Authorization header, not cookies.

---

## Low Findings (Nice to Have)

### 12. No MFA
**Issue:** Single-factor authentication only.  
**Recommendation:** Add TOTP-based MFA for admin accounts.

### 13. No Password Rotation Policy
**Issue:** Passwords never expire.  
**Recommendation:** Add optional 90-day password rotation for admin accounts.

### 14. CORS Allows Localhost in Production
**File:** `backend/main.py:117`  
**Issue:** Default `ALLOWED_ORIGINS` includes `http://localhost:5173,http://localhost:3000`.  
**Recommendation:** Ensure production env overrides this with actual domain only.

---

## What Was Fixed in This Session

| # | Issue | Fix |
|---|-------|-----|
| 1 | JWT_SECRET weak default | Auto-generate if missing, warn on known defaults |
| 2 | Auth disabled by default | Production mode enforces auth |
| 3 | Tally password plaintext | Encrypted with Fernet before DB storage |
| 4 | Session tokens plaintext | Encrypted with Windows DPAPI |
| 5 | Weak password policy | Min 8 chars + uppercase + number |
| 6 | No audit logging | Full audit_log.py with integration into 8 endpoints |
| 7 | No encryption library | Added `cryptography==43.0.3` to requirements |

---

## Verification

- Backend tests: **166 passed**
- Tally connector build: **0 errors, 0 new warnings**
- Security fixes: **7 implemented**
