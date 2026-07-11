"""Live port-9000 Tally Prime injection diagnostic.

Sends a balanced Purchase voucher directly to Tally Prime's XML listener
to verify the double-entry sign convention and envelope structure.
Requires Tally Prime running locally with Connectivity -> Port 9000 enabled.
"""

import sys
import requests

TALLY_URL = "http://localhost:9000"

TEST_PAYLOAD = """<ENVELOPE>
<HEADER>
<TALLYREQUEST>Import Data</TALLYREQUEST>
</HEADER>
<BODY>
<IMPORTDATA>
<REQUESTDESC>
<REPORTNAME>Vouchers</REPORTNAME>
</REQUESTDESC>
<REQUESTDATA>
<TALLYMESSAGE xmlns:UDF="TallyUDF">
<VOUCHER VCHTYPE="Purchase" ACTION="Create">
<DATE>20260710</DATE>
<VOUCHERNUMBER>INV-DIAG-2026-99</VOUCHERNUMBER>
<PARTYLEDGERNAME>InvoSync Test Supplier Ltd</PARTYLEDGERNAME>

<ALLLEDGERENTRIES.LIST>
<LEDGERNAME>InvoSync Test Supplier Ltd</LEDGERNAME>
<ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
<AMOUNT>11800.00</AMOUNT>
</ALLLEDGERENTRIES.LIST>

<ALLLEDGERENTRIES.LIST>
<LEDGERNAME>Purchase Accounts</LEDGERNAME>
<ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>
<AMOUNT>-10000.00</AMOUNT>
</ALLLEDGERENTRIES.LIST>

<ALLLEDGERENTRIES.LIST>
<LEDGERNAME>Input CGST @ 9%</LEDGERNAME>
<ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>
<AMOUNT>-900.00</AMOUNT>
</ALLLEDGERENTRIES.LIST>

<ALLLEDGERENTRIES.LIST>
<LEDGERNAME>Input SGST @ 9%</LEDGERNAME>
<ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>
<AMOUNT>-900.00</AMOUNT>
</ALLLEDGERENTRIES.LIST>
</VOUCHER>
</TALLYMESSAGE>
</REQUESTDATA>
</IMPORTDATA>
</BODY>
</ENVELOPE>"""


def main():
    print("=" * 70)
    print(" INVOSYNC CORE: LIVE PORT 9000 TALLY IMPORTER DIAGNOSTIC")
    print("=" * 70)
    print()
    print("Sending balanced Purchase voucher to", TALLY_URL)
    print("  Party (Cr): InvoSync Test Supplier Ltd  = +11,800.00")
    print("  Purchase (Dr): Purchase Accounts         = -10,000.00")
    print("  CGST (Dr): Input CGST @ 9%               = -900.00")
    print("  SGST (Dr): Input SGST @ 9%               = -900.00")
    print("  Sum: 11800 - 10000 - 900 - 900 = 0.00 (balanced)")
    print()

    try:
        resp = requests.post(
            TALLY_URL,
            data=TEST_PAYLOAD.encode("utf-8"),
            headers={"Content-Type": "text/xml"},
            timeout=15,
        )
    except requests.exceptions.ConnectionError:
        print("CONNECTIVITY ERROR: Could not reach Tally Prime on port 9000.")
        print("  Ensure Tally Prime is running and port 9000 is open.")
        print("  F1 -> Settings -> Connectivity -> Port 9000")
        return 1
    except requests.exceptions.Timeout:
        print("TIMEOUT: Tally did not respond within 15 seconds.")
        return 1

    print("RAW RESPONSE FROM TALLY PRIME:")
    print("-" * 60)
    print(resp.text.strip())
    print("-" * 60)
    print()

    if "<CREATED>1</CREATED>" in resp.text or "<CREATED>2</CREATED>" in resp.text:
        print("SUCCESS: Tally Prime accepted the voucher.")
        return 0
    elif "<ERRORS>" in resp.text:
        print("TALLY REJECTION: XML parsed but accounting failed.")
        print("  Likely causes:")
        print("    - Ledger 'InvoSync Test Supplier Ltd' does not exist")
        print("    - Ledger 'Purchase Accounts' does not exist")
        print("    - GST ledgers 'Input CGST @ 9%' / 'Input SGST @ 9%' missing")
        print("  Run the XML with masters creation (ledger + stock + voucher type) first.")
        return 1
    else:
        print("UNKNOWN RESPONSE — check Tally's import summary.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
