"""South Indian invoice edge cases — Tamil Nadu, Karnataka, Andhra Pradesh, Telangana, Kerala.

Covers:
- Restaurant bills (common in all 5 states)
- IT/software services (Karnataka, Telangana)
- Export/SEZ invoices (Kerala, Tamil Nadu)
- Pharma/healthcare (Andhra Pradesh, Telangana)
- Multi-language vendor names
- UPI payment references
- High-volume retail (Tamil Nadu, Karnataka)
"""

import pytest
from schemas import StandardizedInvoice, LineItem, TaxEntry, VoucherType
from xml_generator import TallyXmlGenerator
from company_config import CompanyConfig
from gst_engine import _compute_gstin_checksum, determine_gst_type, validate_tax_structure
from validation_layer import validate_invoice_for_xml
from validators.tally_simulator import TallySimulator
from voucher_classifier import classify_voucher_type, classify_service_vs_goods
from ocr_postproc import fix_gstin, fix_date, clean_extracted_invoice_payload


# Valid GSTINs generated via _compute_gstin_checksum (15 chars, format: SS+PAN+entity+Z+checksum)
_VALID_GSTIN_29 = "29AABCT1234F1ZM"  # Karnataka
_VALID_GSTIN_33 = "33AABCA1234F1ZG"  # Tamil Nadu
_VALID_GSTIN_36 = "36AABCP1234F1ZV"  # Telangana
_VALID_GSTIN_32 = "32AABCC1234F1ZG"  # Kerala
_VALID_GSTIN_27 = "27AABCM9876K1ZQ"  # Maharashtra


def _make_config(state_code="29", company_name="Test Co"):
    return CompanyConfig(user_config={"company_state_code": state_code, "company_name": company_name})


def _make_generator(state_code="29", company_name="Test Co"):
    return TallyXmlGenerator(_make_config(state_code, company_name))


# =====================================================================
# 1. TAMIL NADU — Restaurant bills (Chennai)
# =====================================================================

class TestTamilNaduRestaurant:
    def test_chennai_restaurant_single_rate(self):
        inv = StandardizedInvoice(
            invoice_number="CHN-2026-001",
            invoice_date="2026-06-15",
            vendor_name="Adyar Ananda Bhavan",
            vendor_gstin=_VALID_GSTIN_33,
            buyer_gstin="",
            place_of_supply="33",
            is_service=True,
            total_taxable_value=1200.0,
            total_tax=216.0,
            total_amount=1416.0,
            line_items=[
                LineItem(description="Masala Dosa", quantity=4, rate=120.0, taxable_value=480.0,
                         tax_rate=18, is_service=True, ledger_name="Food Expenses"),
                LineItem(description="Filter Coffee", quantity=4, rate=30.0, taxable_value=120.0,
                         tax_rate=18, is_service=True, ledger_name="Food Expenses"),
                LineItem(description="Ghee Roast", quantity=2, rate=200.0, taxable_value=400.0,
                         tax_rate=18, is_service=True, ledger_name="Food Expenses"),
                LineItem(description="Parking", quantity=1, rate=200.0, taxable_value=200.0,
                         tax_rate=18, is_service=True, ledger_name="Parking Expenses"),
            ],
            taxes=[
                TaxEntry(name="CGST", rate=9.0, amount=108.0, type="cgst"),
                TaxEntry(name="SGST", rate=9.0, amount=108.0, type="sgst"),
            ],
        )
        result = validate_invoice_for_xml(inv)
        assert result.passed, result.errors
        xml = _make_generator("33", "Test Co").generate(inv)
        assert "CGST" in xml and "SGST" in xml
        assert "Adyar Ananda Bhavan" in xml

    def test_tamil_nadu_multi_rate_restaurant(self):
        inv = StandardizedInvoice(
            invoice_number="CHN-2026-045",
            invoice_date="2026-06-15",
            vendor_name="Hotel Saravana Bhavan",
            vendor_gstin=_VALID_GSTIN_33,
            place_of_supply="33",
            is_service=True,
        total_taxable_value=500.0,
        total_tax=51.0,
        total_amount=551.0,
            line_items=[
                LineItem(description="Plain Dosa", quantity=2, rate=50.0, taxable_value=100.0,
                         tax_rate=5, is_service=True, ledger_name="Food Expenses"),
                LineItem(description="Thali Meal", quantity=2, rate=100.0, taxable_value=200.0,
                         tax_rate=5, is_service=True, ledger_name="Food Expenses"),
                LineItem(description="Fresh Juice", quantity=1, rate=200.0, taxable_value=200.0,
                         tax_rate=18, is_service=True, ledger_name="Food Expenses"),
            ],
            taxes=[
                TaxEntry(name="CGST", rate=2.5, amount=7.5, type="cgst"),
                TaxEntry(name="SGST", rate=2.5, amount=7.5, type="sgst"),
                TaxEntry(name="CGST", rate=9.0, amount=18.0, type="cgst"),
                TaxEntry(name="SGST", rate=9.0, amount=18.0, type="sgst"),
            ],
        )
        result = validate_invoice_for_xml(inv)
        assert result.passed, result.errors
        xml = _make_generator("33", "Test Co").generate(inv)
        assert "CGST 2.5%" in xml
        assert "CGST 9%" in xml


# =====================================================================
# 2. KARNATAKA — IT/Software services (Bangalore)
# =====================================================================

class TestKarnatakaITServices:
    def test_bangalore_it_service_domestic(self):
        inv = StandardizedInvoice(
            invoice_number="BLR-2026-001",
            invoice_date="2026-06-15",
            vendor_name="Tech Solutions Pvt Ltd",
            vendor_gstin=_VALID_GSTIN_29,
            buyer_name="MNC Corporation",
            buyer_gstin=_VALID_GSTIN_27,
            place_of_supply="29",
            is_service=True,
            total_taxable_value=50000.0,
            total_tax=9000.0,
            total_amount=59000.0,
            line_items=[
                LineItem(description="Software Development Services", quantity=1, rate=50000.0,
                         taxable_value=50000.0, tax_rate=18, is_service=True,
                         ledger_name="Professional Charges"),
            ],
            taxes=[
                TaxEntry(name="IGST", rate=18.0, amount=9000.0, type="igst"),
            ],
        )
        result = validate_invoice_for_xml(inv)
        assert result.passed
        xml = _make_generator("29", "Test Co").generate(inv)
        assert "IGST" in xml

    def test_karnataka_sez_invoice(self):
        inv = StandardizedInvoice(
            invoice_number="BLR-SEZ-2026-001",
            invoice_date="2026-06-15",
            vendor_name="Tech Solutions Pvt Ltd",
            vendor_gstin=_VALID_GSTIN_29,
            buyer_name="SEZ Developer Ltd",
            buyer_gstin=_VALID_GSTIN_29,
            place_of_supply="29",
            is_service=True,
            total_taxable_value=100000.0,
            total_tax=0.0,
            total_amount=100000.0,
            line_items=[
                LineItem(description="IT Consulting Services", quantity=1, rate=100000.0,
                         taxable_value=100000.0, tax_rate=0, is_service=True,
                         ledger_name="Professional Charges"),
            ],
            taxes=[],
        )
        result = validate_invoice_for_xml(inv)
        assert result.passed
        xml = _make_generator("29", "Test Co").generate(inv)
        sim = TallySimulator()
        r = sim.simulate_import(xml, expected_vchtype="Purchase")
        assert r.passed, [c.message for c in r.checks if not c.passed]


# =====================================================================
# 3. ANDHRA PRADESH / TELANGANA — Restaurant + Pharma
# =====================================================================

class TestAndhraTelnaganaInvoices:
    def test_hyderabad_restaurant_bill(self):
        inv = StandardizedInvoice(
            invoice_number="HYD-2026-001",
            invoice_date="2026-06-15",
            vendor_name="Paradise Biryani",
            vendor_gstin=_VALID_GSTIN_36,
            place_of_supply="36",
            is_service=True,
            total_taxable_value=1390.0,
            total_tax=250.2,
            total_amount=1640.2,
            line_items=[
                LineItem(description="Chicken Biryani", quantity=2, rate=300.0, taxable_value=600.0,
                         tax_rate=18, is_service=True, ledger_name="Food Expenses"),
                LineItem(description="Mutton Seekh Kebab", quantity=1, rate=350.0, taxable_value=350.0,
                         tax_rate=18, is_service=True, ledger_name="Food Expenses"),
                LineItem(description="Naan", quantity=4, rate=60.0, taxable_value=240.0,
                         tax_rate=18, is_service=True, ledger_name="Food Expenses"),
                LineItem(description="Soft Drink", quantity=4, rate=50.0, taxable_value=200.0,
                         tax_rate=18, is_service=True, ledger_name="Food Expenses"),
            ],
            taxes=[
                TaxEntry(name="CGST", rate=9.0, amount=125.1, type="cgst"),
                TaxEntry(name="SGST", rate=9.0, amount=125.1, type="sgst"),
            ],
        )
        result = validate_invoice_for_xml(inv)
        assert result.passed, result.errors
        xml = _make_generator("36", "Test Co").generate(inv)
        assert "Paradise Biryani" in xml

    def test_pharma_invoice_telangana(self):
        inv = StandardizedInvoice(
            invoice_number="HYD-PHARMA-2026-001",
            invoice_date="2026-06-15",
            vendor_name="Apollo Pharmacy",
            vendor_gstin=_VALID_GSTIN_36,
            place_of_supply="36",
            is_service=False,
            total_taxable_value=2500.0,
            total_tax=375.0,
            total_amount=2875.0,
            line_items=[
                LineItem(description="Paracetamol 500mg", quantity=100, rate=10.0, taxable_value=1000.0,
                         tax_rate=12, hsn_sac="30049099", unit="Strips", is_service=False),
                LineItem(description="Cough Syrup 100ml", quantity=50, rate=20.0, taxable_value=1000.0,
                         tax_rate=12, hsn_sac="30049059", unit="Bottles", is_service=False),
                LineItem(description="Bandages", quantity=20, rate=25.0, taxable_value=500.0,
                         tax_rate=12, hsn_sac="30051010", unit="Packets", is_service=False),
            ],
            taxes=[
                TaxEntry(name="CGST", rate=6.0, amount=150.0, type="cgst"),
                TaxEntry(name="SGST", rate=6.0, amount=225.0, type="sgst"),
            ],
        )
        result = validate_invoice_for_xml(inv)
        assert result.passed
        xml = _make_generator("36", "Test Co").generate(inv)
        assert "STOCKITEM" in xml
        assert "HSNCODE" in xml


# =====================================================================
# 4. KERALA — Export + Tourism
# =====================================================================

class TestKeralaInvoices:
    def test_kerala_export_invoice(self):
        inv = StandardizedInvoice(
            invoice_number="KER-EXP-2026-001",
            invoice_date="2026-06-15",
            vendor_name="Cochin Spice Exports",
            vendor_gstin=_VALID_GSTIN_32,
            buyer_name="Dubai Spice LLC",
            buyer_gstin="",
            place_of_supply="32",
            is_service=False,
            total_taxable_value=200000.0,
            total_tax=0.0,
            total_amount=200000.0,
            line_items=[
                LineItem(description="Black Pepper", quantity=1000, rate=120.0, taxable_value=120000.0,
                         tax_rate=0, hsn_sac="09041100", unit="Kgs", is_service=False),
                LineItem(description="Cardamom", quantity=500, rate=160.0, taxable_value=80000.0,
                         tax_rate=0, hsn_sac="09063200", unit="Kgs", is_service=False),
            ],
            taxes=[],
        )
        result = validate_invoice_for_xml(inv)
        assert result.passed
        xml = _make_generator("32", "Test Co").generate(inv)
        assert "Cochin Spice Exports" in xml

    def test_kerala_tourism_service(self):
        inv = StandardizedInvoice(
            invoice_number="KER-TOUR-2026-001",
            invoice_date="2026-06-15",
            vendor_name="Kerala Tourism Development Corp",
            vendor_gstin=_VALID_GSTIN_32,
            place_of_supply="32",
            is_service=True,
            total_taxable_value=35000.0,
            total_tax=6300.0,
            total_amount=41300.0,
            line_items=[
                LineItem(description="Houseboat Package", quantity=2, rate=10000.0, taxable_value=20000.0,
                         tax_rate=18, is_service=True, ledger_name="Professional Charges"),
                LineItem(description="Ayurveda Spa", quantity=2, rate=5000.0, taxable_value=10000.0,
                         tax_rate=18, is_service=True, ledger_name="Professional Charges"),
                LineItem(description="Hill Station Transfer", quantity=1, rate=5000.0, taxable_value=5000.0,
                         tax_rate=18, is_service=True, ledger_name="Transportation Expenses"),
            ],
            taxes=[
                TaxEntry(name="CGST", rate=9.0, amount=3150.0, type="cgst"),
                TaxEntry(name="SGST", rate=9.0, amount=3150.0, type="sgst"),
            ],
        )
        result = validate_invoice_for_xml(inv)
        assert result.passed, result.errors


# =====================================================================
# 5. COMMON SOUTH INDIAN PATTERNS
# =====================================================================

class TestSouthIndianPatterns:
    def test_upi_payment_reference(self):
        inv = StandardizedInvoice(
            invoice_number="UPI-2026-001",
            invoice_date="2026-06-15",
            vendor_name="Mobile Shop",
            vendor_gstin=_VALID_GSTIN_29,
            place_of_supply="29",
            is_service=False,
            total_taxable_value=15000.0,
            total_tax=2700.0,
            total_amount=17700.0,
            line_items=[
                LineItem(description="Smartphone", quantity=1, rate=15000.0, taxable_value=15000.0,
                         tax_rate=18, hsn_sac="85171200", unit="Pieces", is_service=False),
            ],
            taxes=[
                TaxEntry(name="CGST", rate=9.0, amount=1350.0, type="cgst"),
                TaxEntry(name="SGST", rate=9.0, amount=1350.0, type="sgst"),
            ],
        )
        result = validate_invoice_for_xml(inv)
        assert result.passed

    def test_tamil_vendor_name_romanized(self):
        inv = StandardizedInvoice(
            invoice_number="TAM-2026-001",
            invoice_date="2026-06-15",
            vendor_name="Kumar Electronics Anna Nagar",
            vendor_gstin=_VALID_GSTIN_33,
            place_of_supply="33",
            is_service=False,
            total_taxable_value=5000.0,
            total_tax=900.0,
            total_amount=5900.0,
            line_items=[
                LineItem(description="LED TV 43 inch", quantity=1, rate=5000.0, taxable_value=5000.0,
                         tax_rate=18, hsn_sac="85287200", unit="Pieces", is_service=False),
            ],
            taxes=[
                TaxEntry(name="CGST", rate=9.0, amount=450.0, type="cgst"),
                TaxEntry(name="SGST", rate=9.0, amount=450.0, type="sgst"),
            ],
        )
        result = validate_invoice_for_xml(inv)
        assert result.passed
        xml = _make_generator("33", "Test Co").generate(inv)
        assert "Kumar Electronics Anna Nagar" in xml

    def test_malayalam_vendor_name_romanized(self):
        inv = StandardizedInvoice(
            invoice_number="KER-2026-001",
            invoice_date="2026-06-15",
            vendor_name="Joseph & Sons Thrissur",
            vendor_gstin=_VALID_GSTIN_32,
            place_of_supply="32",
            is_service=False,
            total_taxable_value=3000.0,
            total_tax=540.0,
            total_amount=3540.0,
            line_items=[
                LineItem(description="Coconut Oil 1L", quantity=10, rate=180.0, taxable_value=1800.0,
                         tax_rate=18, hsn_sac="15100000", unit="Pieces", is_service=False),
                LineItem(description="Rice 5kg", quantity=10, rate=120.0, taxable_value=1200.0,
                         tax_rate=18, hsn_sac="10063020", unit="Pieces", is_service=False),
            ],
            taxes=[
                TaxEntry(name="CGST", rate=9.0, amount=270.0, type="cgst"),
                TaxEntry(name="SGST", rate=9.0, amount=270.0, type="sgst"),
            ],
        )
        result = validate_invoice_for_xml(inv)
        assert result.passed
        xml = _make_generator("32", "Test Co").generate(inv)
        assert "Joseph" in xml and "Sons" in xml and "Thrissur" in xml

    def test_telugu_vendor_name_romanized(self):
        inv = StandardizedInvoice(
            invoice_number="TEL-2026-001",
            invoice_date="2026-06-15",
            vendor_name="Sri Rama Book House",
            vendor_gstin=_VALID_GSTIN_36,
            place_of_supply="36",
            is_service=False,
            total_taxable_value=2000.0,
            total_tax=360.0,
            total_amount=2360.0,
            line_items=[
                LineItem(description="Engineering Textbooks Set", quantity=1, rate=2000.0,
                         taxable_value=2000.0, tax_rate=18, hsn_sac="49019900", unit="Sets", is_service=False),
            ],
            taxes=[
                TaxEntry(name="CGST", rate=9.0, amount=180.0, type="cgst"),
                TaxEntry(name="SGST", rate=9.0, amount=180.0, type="sgst"),
            ],
        )
        result = validate_invoice_for_xml(inv)
        assert result.passed
        xml = _make_generator("36", "Test Co").generate(inv)
        assert "Sri Rama Book House" in xml

    def test_kannada_vendor_name_romanized(self):
        inv = StandardizedInvoice(
            invoice_number="KAN-2026-001",
            invoice_date="2026-06-15",
            vendor_name="Mavalli Tiffin Room",
            vendor_gstin=_VALID_GSTIN_29,
            place_of_supply="29",
            is_service=True,
            total_taxable_value=800.0,
            total_tax=144.0,
            total_amount=944.0,
            line_items=[
                LineItem(description="Masala Dosa", quantity=2, rate=80.0, taxable_value=160.0,
                         tax_rate=18, is_service=True, ledger_name="Food Expenses"),
                LineItem(description="Idli Vada", quantity=2, rate=60.0, taxable_value=120.0,
                         tax_rate=18, is_service=True, ledger_name="Food Expenses"),
                LineItem(description="Filter Coffee", quantity=4, rate=30.0, taxable_value=120.0,
                         tax_rate=18, is_service=True, ledger_name="Food Expenses"),
                LineItem(description="Uppitt", quantity=1, rate=80.0, taxable_value=80.0,
                         tax_rate=18, is_service=True, ledger_name="Food Expenses"),
                LineItem(description="Bisibelebath", quantity=1, rate=320.0, taxable_value=320.0,
                         tax_rate=18, is_service=True, ledger_name="Food Expenses"),
            ],
            taxes=[
                TaxEntry(name="CGST", rate=9.0, amount=72.0, type="cgst"),
                TaxEntry(name="SGST", rate=9.0, amount=72.0, type="sgst"),
            ],
        )
        result = validate_invoice_for_xml(inv)
        assert result.passed, result.errors
        xml = _make_generator("29", "Test Co").generate(inv)
        assert "Mavalli Tiffin Room" in xml

    def test_south_indian_high_value_gold_jewellery(self):
        inv = StandardizedInvoice(
            invoice_number="GOLD-2026-001",
            invoice_date="2026-06-15",
            vendor_name="Nakshatra Jewellers",
            vendor_gstin=_VALID_GSTIN_33,
            place_of_supply="33",
            is_service=False,
            total_taxable_value=250000.0,
            total_tax=9800.0,
            total_amount=259800.0,
            line_items=[
                LineItem(description="22K Gold Chain 10g", quantity=1, rate=60000.0, taxable_value=60000.0,
                         tax_rate=3, hsn_sac="71131900", unit="Grams", is_service=False),
                LineItem(description="22K Gold Earrings 5g", quantity=1, rate=30000.0, taxable_value=30000.0,
                         tax_rate=3, hsn_sac="71131100", unit="Grams", is_service=False),
                LineItem(description="Making Charges", quantity=1, rate=160000.0, taxable_value=160000.0,
                         tax_rate=5, hsn_sac="71149000", unit="Pieces", is_service=False),
            ],
            taxes=[
                TaxEntry(name="CGST", rate=1.5, amount=900.0, type="cgst"),
                TaxEntry(name="SGST", rate=1.5, amount=900.0, type="sgst"),
                TaxEntry(name="CGST", rate=2.5, amount=4000.0, type="cgst"),
                TaxEntry(name="SGST", rate=2.5, amount=4000.0, type="sgst"),
            ],
        )
        result = validate_invoice_for_xml(inv)
        assert result.passed, result.errors
        xml = _make_generator("33", "Test Co").generate(inv)
        assert "Gold Chain 10g" in xml

    def test_south_indian_vehicle_purchase(self):
        inv = StandardizedInvoice(
            invoice_number="VEH-2026-001",
            invoice_date="2026-06-15",
            vendor_name="Honda Showroom",
            vendor_gstin=_VALID_GSTIN_29,
            place_of_supply="29",
            is_service=False,
            total_taxable_value=85000.0,
            total_tax=15300.0,
            total_amount=100300.0,
            line_items=[
                LineItem(description="Honda Activa 6G", quantity=1, rate=85000.0, taxable_value=85000.0,
                         tax_rate=18, hsn_sac="87111000", unit="Pieces", is_service=False),
            ],
            taxes=[
                TaxEntry(name="CGST", rate=9.0, amount=7650.0, type="cgst"),
                TaxEntry(name="SGST", rate=9.0, amount=7650.0, type="sgst"),
            ],
        )
        result = validate_invoice_for_xml(inv)
        assert result.passed
        xml = _make_generator("29", "Test Co").generate(inv)
        assert "Honda Activa 6G" in xml


# =====================================================================
# 6. OCR POST-PROCESSING — South Indian date formats
# =====================================================================

class TestSouthIndianOCR:
    def test_fix_gstin_ocr_confusion(self):
        assert fix_gstin("29AACCT3705E1ZM") == "29AACCT3705E1ZM"
        assert fix_gstin("29AACCT3705E1Z") == "29AACCT3705E1Z"
        assert fix_gstin("29AACT3705E1ZZ") == "29AACT3705E12Z"

    def test_fix_date_dd_mm_yyyy(self):
        assert fix_date("15/06/2026") == "2026-06-15"
        assert fix_date("15-06-2026") == "2026-06-15"

    def test_clean_extracted_payload(self):
        raw = {
            "invoice_number": "INV-001",
            "vendor_name": "Test Supplier",
            "total_amount": 1000.0,
            "line_items": [{"description": "Item 1", "quantity": 2, "rate": 100.0, "taxable_value": 200.0}],
        }
        cleaned = clean_extracted_invoice_payload(raw)
        assert cleaned["invoice_number"] == "INV-001"
        assert cleaned["total_amount"] == 1000.0


# =====================================================================
# 7. VOUCHER CLASSIFICATION — South Indian scenarios
# =====================================================================

class TestVoucherClassification:
    def test_classify_south_indian_restaurant_as_purchase(self):
        data = {
            "vendor_name": "Hotel Saravana Bhavan",
            "invoice_number": "SB-123",
            "total_amount": 1000,
            "vendor_gstin": _VALID_GSTIN_33,
            "document_type": "retail_bill",
        }
        vt, reason = classify_voucher_type(data, "33")
        assert vt == VoucherType.PURCHASE

    def test_classify_bangalore_company_selling_as_sales(self):
        data = {
            "vendor_name": "My Company",
            "invoice_number": "INV-001",
            "total_amount": 50000,
            "vendor_gstin": _VALID_GSTIN_29,
            "document_type": "tax_invoice",
        }
        vt, reason = classify_voucher_type(data, "29", company_gstin=_VALID_GSTIN_29)
        assert vt == VoucherType.SALES
