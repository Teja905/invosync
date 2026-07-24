"""Frankenstein Invoice — stress test against all 6 accounting traps."""
import os
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))

# Set env before any imports — Ladakh (state code 37)
os.environ["COMPANY_STATE_CODE"] = "37"
os.environ["COMPANY_GSTIN"] = "37AAACM5678E2Z0"
os.environ["COMPANY_NAME"] = "InvoSync Test Co"

from schemas import StandardizedInvoice, VoucherType, DocumentClass, GSTType, LineItem, TaxEntry
from validation_layer import validate_invoice_for_xml
from xml_generator import TallyXmlGenerator
from company_config import CompanyConfig


def main():
    print("=" * 80)
    print(" FRANKENSTEIN INVOICE STRESS TEST — 6 ACCOUNTING TRAPS")
    print("=" * 80)

    cfg = CompanyConfig()
    gen = TallyXmlGenerator(cfg)

    # Line items
    # Trap 5: Multi-slab mixture (18%, 5%, 0%)
    line_items = [
        LineItem(
            description='Premium Alloy Turbines',
            quantity=2.0, rate=15000.45, taxable_value=30000.90, tax_rate=18.0,
            hsn_sac="8411", unit="NOS", is_service=False,
        ),
        LineItem(
            description='Industrial Synthetic Oil',
            quantity=1.0, rate=4550.40, taxable_value=4550.40, tax_rate=5.0,
            hsn_sac="2710", unit="CAN", is_service=False,
        ),
        LineItem(
            description='Retainer Consultation Fees (RCM)',
            quantity=1.0, rate=5000.00, taxable_value=5000.00, tax_rate=18.0,
            hsn_sac="9982", unit="NOS", is_service=True,
        ),
        LineItem(
            description='Zero-Rated Safety Decals',
            quantity=100.0, rate=4.00, taxable_value=400.00, tax_rate=0.0,
            hsn_sac="4908", unit="PCS", is_service=False,
        ),
    ]

    # Tax entries — SEZ forces IGST (Trap 3), RCM suffix (Trap 4)
    # Trap 6: Penny drift: true total = 46478.98, stated = 46478.00 → round_off = -0.98
    taxes = [
        TaxEntry(name="Input IGST @ 18%", rate=18.0, amount=5400.16, type="igst", is_input=True),
        TaxEntry(name="Input IGST @ 5%",  rate=5.0,  amount=227.52,  type="igst", is_input=True),
        TaxEntry(name="Input IGST (RCM) @ 18%", rate=18.0, amount=900.00, type="igst", is_input=True),
    ]

    # Trap 1: Special chars in vendor name
    # Trap 2: Same-state (37/37) but SEZ → should be IGST
    vendor_name = 'M/S D\'Souza & "Sons" (Industrial) <Manufacturing> Pvt. Ltd.'
    vendor_gstin = "37AAACD1111A1Z1"
    buyer_gstin = "37AAACM5678E2Z0"

    print(f"\n Vendor: {vendor_name}")
    print(f" Vendor GSTIN: {vendor_gstin} (Ladakh, 37)")
    print(f" Buyer GSTIN:  {buyer_gstin} (Ladakh, 37)")
    print(" SEZ: True (forces IGST despite same state)")
    print(" RCM: True (legal fee 18% -> RCM isolation)")
    print()

    inv = StandardizedInvoice(
        voucher_type=VoucherType.PURCHASE,
        document_class=DocumentClass.GST_INVOICE,
        invoice_number="INV-FRK-2026-X99",
        invoice_date="2026-07-10",
        vendor_name=vendor_name,
        vendor_gstin=vendor_gstin,
        vendor_address="Leh, Ladakh",
        buyer_gstin=buyer_gstin,
        buyer_name="InvoSync Test Co",
        place_of_supply="37",
        is_sez=True,
        is_rcm=True,
        gst_type=GSTType.IGST,
        is_interstate=True,
        line_items=line_items,
        taxes=taxes,
        total_taxable_value=39951.30,
        total_tax=6527.68,
        total_amount=46478.00,
        round_off=-0.98,
    )

    # ── Pass 1: Validation Firewall ──
    print("─" * 80)
    print(" PASS 1: 11-Layer Statutory Validation Firewall")
    print("─" * 80)
    result = validate_invoice_for_xml(inv)

    print(f" Overall: {'PASSED' if result.passed else 'FAILED'}")
    for name, check in result.checks.items():
        status = "OK" if check.get("pass") else "FAIL"
        print(f"  [{status}] {name}: {check.get('message', '')}")
    if result.warnings:
        print(f"  Warnings: {result.warnings}")
    if result.errors:
        print(f"  Errors: {result.errors}")

    # ── Pass 2: XML Generation ──
    print()
    print("─" * 80)
    print(" PASS 2: XML Generation & Sanitization Checks")
    print("─" * 80)

    try:
        xml = gen.generate(inv)
        print(" [OK] XML generated successfully")
        print()

        # Trap 1: XML entity escaping
        has_amp = "&amp;" in xml
        has_lt = "&lt;" in xml
        has_gt = "&gt;" in xml
        has_quot = "&quot;" in xml
        has_apos = "&apos;" in xml
        no_raw_amp = xml.count("&") == sum([has_amp, has_lt, has_gt, has_quot, has_apos])  # only entity refs
        print(f" [{'OK' if has_amp else 'FAIL'}] Ampersand escaped: &amp; {'present' if has_amp else 'MISSING'}")
        print(f" [{'OK' if has_lt else 'FAIL'}] Less-than escaped: &lt; {'present' if has_lt else 'MISSING'}")
        print(f" [{'OK' if has_gt else 'FAIL'}] Greater-than escaped: &gt; {'present' if has_gt else 'MISSING'}")
        print(f" [{'OK' if has_quot else 'FAIL'}] Double-quote escaped: &quot; {'present' if has_quot else 'MISSING'}")

        # Trap 2 & 3: SEZ → IGST, no CGST/SGST/UTGST
        print(f" [{'OK' if 'Input IGST' in xml else 'FAIL'}] IGST routing: {'present' if 'Input IGST' in xml else 'MISSING'}")
        print(f" [{'OK' if 'CGST' not in xml and 'SGST' not in xml and 'UTGST' not in xml else 'FAIL'}] No CGST/SGST/UTGST: {'CLEAN' if 'CGST' not in xml and 'SGST' not in xml and 'UTGST' not in xml else 'CONTAMINATED'}")

        # Trap 4: RCM ledger naming
        print(f" [{'OK' if '(RCM)' in xml else 'FAIL'}] RCM isolation suffix: {'present' if '(RCM)' in xml else 'MISSING'}")

        # Trap 6: Round Off present for -0.98 drift
        print(f" [{'OK' if 'Round Off' in xml else 'FAIL'}] Round Off ledger for -0.98 drift: {'present' if 'Round Off' in xml else 'MISSING'}")

        # Balance check
        import re
        cleaned = re.sub(r"<ALLINVENTORYENTRIES\.LIST>.*?</ALLINVENTORYENTRIES\.LIST>", "", xml, flags=re.DOTALL)
        cleaned = re.sub(r"<BILLALLOCATIONS\.LIST>.*?</BILLALLOCATIONS\.LIST>", "", cleaned, flags=re.DOTALL)
        amounts = [float(a) for a in re.findall(r"<AMOUNT>(-?\d+\.?\d*)</AMOUNT>", cleaned)]
        total = sum(amounts)
        print(f" [{'OK' if abs(total) < 0.01 else 'FAIL'}] Voucher balance: {total:.4f} {'(balanced)' if abs(total) < 0.01 else '(IMBALANCED!)'}")

        # Print a snippet
        print()
        print("─" * 80)
        print(" XML SNIPPET (first 2000 chars):")
        print("─" * 80)
        print(xml[:2000])
        if len(xml) > 2000:
            print("...")

    except Exception as e:
        print(f" [FAIL] XML generation crashed: {e}")
        import traceback
        traceback.print_exc()
        return 1

    print()
    print("=" * 80)
    print(" FRANKENSTEIN TEST COMPLETE")
    print("=" * 80)
    return 0


if __name__ == "__main__":
    sys.exit(main())
