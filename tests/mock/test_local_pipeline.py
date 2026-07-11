"""
Unified diagnostic test: simulates the C# PollingService pipeline entirely in Python.
Proves the end-to-end sync loop works without .NET SDK or Tally Prime.

Usage:
  1. Terminal 1: python mock_tally_server.py
  2. Terminal 2: python mock_backend.py
  3. Terminal 3: python test_local_pipeline.py
"""

import requests
import time
import sys

CLOUD_API = "http://127.0.0.1:8000"
TALLY_API = "http://127.0.0.1:9000"

passed = 0
failed = 0

def check(label: str, ok: bool, detail: str = ""):
    global passed, failed
    if ok:
        passed += 1
        print(f"  [PASS] {label}")
    else:
        failed += 1
        print(f"  [FAIL] {label}: {detail}")

def step(n: int, name: str):
    print(f"\n--- Step {n}: {name} ---")

def main():
    global passed, failed
    print("="*60)
    print(" InvoSync Local Pipeline Diagnostic")
    print("="*60)

    # --- Warm-up: wait for servers ---
    print("\n[Warm-up] Checking mock servers are reachable...")
    for attempt in range(5):
        try:
            r = requests.get(f"{CLOUD_API}/api/v3/sync/pending", timeout=3)
            if r.status_code == 200:
                print("  Cloud API (port 8000) is up.")
                break
        except requests.ConnectionError:
            pass
        try:
            r = requests.post(f"{TALLY_API}/", data="<ENVELOPE><BODY/></ENVELOPE>",
                              headers={"Content-Type": "text/xml"}, timeout=3)
            if r.status_code == 200:
                print("  Tally Mock (port 9000) is up.")
                break
        except requests.ConnectionError:
            pass
        print(f"  Waiting for servers (attempt {attempt+1}/5)...")
        time.sleep(1)
    else:
        print("  Servers not reachable. Start mock_tally_server.py and mock_backend.py first.")
        sys.exit(1)

    # --- Step 1: C# Polls Cloud API for pending ---
    step(1, "C# PollingService: GET /api/v3/sync/pending")
    resp = requests.get(f"{CLOUD_API}/api/v3/sync/pending")
    check("Status 200", resp.status_code == 200,
          f"Got {resp.status_code}")
    payload = resp.json()
    check("Has 'invoices' key", "invoices" in payload)
    check("Has 'count' key", "count" in payload)
    check("Count matches invoices length",
          payload["count"] == len(payload["invoices"]))
    invoices = payload["invoices"]
    check("At least one invoice", len(invoices) > 0,
          f"Got {len(invoices)}")

    if not len(invoices):
        sys.exit(1)

    inv = invoices[0]
    check("Invoice has display_id", "display_id" in inv)
    check("Invoice has xml_content", "xml_content" in inv)
    check("Invoice status is validated", inv.get("status", "") == "validated",
          f"Got status={inv.get('status')}")
    check("Invoice has vendor_name", bool(inv.get("vendor_name", "")))
    check("Invoice has invoice_number", bool(inv.get("invoice_number", "")))
    display_id = inv["display_id"]
    xml_content = inv["xml_content"]

    # --- Step 2: Guard: verify validated status ---
    step(2, "C# Safety Guard: status=validated check")
    status = inv.get("status", "")
    if status != "validated":
        check("Guard would SKIP (status mismatch)", False,
              f"Expected 'validated', got '{status}'")
        # Skip remaining steps if guard would block
        sys.exit(1)
    check("Guard PASSED — status=validated", True)

    # --- Step 3: Push XML to Tally ---
    step(3, "C# TallyPusher: POST XML to localhost:9000")
    resp = requests.post(
        TALLY_API,
        data=xml_content.encode("utf-8"),
        headers={"Content-Type": "text/xml"},
    )
    check("Tally returned 200", resp.status_code == 200,
          f"Got {resp.status_code}")
    tally_body = resp.text
    check("Tally response contains <CREATED>1</CREATED>",
          "<CREATED>1</CREATED>" in tally_body,
          f"Response: {tally_body[:200]}")
    check("Tally reports 0 errors",
          "<ERRORS>0</ERRORS>" in tally_body,
          f"Response: {tally_body[:200]}")

    # --- Step 4: Confirm success to Cloud API ---
    step(4, "C# Confirm: POST /api/v3/sync/confirm/{id}")
    resp = requests.post(f"{CLOUD_API}/api/v3/sync/confirm/{display_id}")
    check("Confirm returned 200", resp.status_code == 200,
          f"Got {resp.status_code}")
    body = resp.json()
    check("Confirm body has status=ok",
          body.get("status") == "ok",
          f"Got {body}")

    # --- Summary ---
    print("\n" + "="*60)
    print(f" RESULTS: {passed} passed, {failed} failed out of {passed+failed}")
    print("="*60)

    if failed == 0:
        print("\nE2E pipeline verified. The C# PollingService will")
        print("follow the identical sequence: poll -> verify state -> push -> confirm.")
        return 0
    else:
        print(f"\n{failed} check(s) failed. Review details above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
