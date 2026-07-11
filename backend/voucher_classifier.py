"""Conservative voucher type classification.

V1 rule: Default everything to Purchase Voucher.
This covers ~85% of real CA office invoices.
Edge cases (credit notes, payments, etc.) require explicit user override.
"""

from typing import Optional

from schemas import VoucherType, DocumentClass


SERVICE_KEYWORDS = [
    "consulting", "consultation", "professional", "service", "fees",
    "charges", "audit", "legal", "advisory", "retainer", "honorarium",
    "commission", "brokerage", "subscription", "membership", "license",
    "licence", "rent", "lease", "royalty", "maintenance", "support",
    "software", "hosting", "cloud", "training", "seminar", "workshop",
    "advertisement", "advertising", "telephone", "internet", "broadband",
    "insurance", "premium", "electricity", "power", "salary", "wages",
    "interest", "bank charge", "consultancy", "architect", "engineer",
    "doctor", "advocate", "ca fees", "accounting", "bookkeeping",
    "design", "development", "management", "administration",
]


GOODS_KEYWORDS = [
    "goods", "product", "item", "material", "stock", "inventory",
    "hardware", "equipment", "furniture", "machinery", "spare",
    "parts", "accessories", "consumables", "supplies", "stationery",
    "printing", "paper", "cartridge", "toner", "chemical", "raw material",
    "packaging", "finish goods", "trading", "merchandise",
]


def classify_document_detailed(data: dict) -> DocumentClass:
    gstin = (data.get("vendor_gstin") or data.get("gstin") or "").strip()
    vendor = (data.get("vendor_name") or "").strip()
    items = data.get("line_items") or []
    total = float(data.get("total_amount") or 0)
    has_gst = bool(gstin)
    has_items = len(items) > 0
    has_vendor = bool(vendor)
    is_service_doc = any(
        any(kw in (item.get("description", "") or "").lower()
            for kw in SERVICE_KEYWORDS)
        for item in items
    ) if items else False
    is_goods_doc = any(
        any(kw in (item.get("description", "") or "").lower()
            for kw in GOODS_KEYWORDS)
        for item in items
    ) if items else False
    if has_gst and has_vendor and has_items:
        if is_service_doc and not is_goods_doc:
            return DocumentClass.SERVICE_INVOICE
        return DocumentClass.GST_INVOICE
    if not has_gst and has_vendor and has_items:
        return DocumentClass.RETAIL_BILL
    if not has_gst and has_vendor and not has_items and total > 0:
        return DocumentClass.EXPENSE_RECEIPT
    if has_gst and has_vendor and not has_items:
        return DocumentClass.PURCHASE_INVOICE
    return DocumentClass.UNKNOWN


_VOUCHER_KEYWORDS: list[tuple[list[str], VoucherType, str]] = [
    (["client", "consulting", "professional fees", "audit fees", "ca fees",
      "legal fees", "advisory", "retainer"], VoucherType.SALES, "Service/client billing"),
    (["medicine", "pharma", "drug", "supplier", "vendor", "raw material",
      "stock", "inventory", "purchase", "goods"], VoucherType.PURCHASE, "Goods/supplier invoice"),
]


def classify_voucher_type(
    data: dict,
    company_state_code: str = "27",
    default_type: VoucherType = VoucherType.PURCHASE,
    is_service: Optional[bool] = None,
    company_gstin: str = "",
) -> tuple[VoucherType, str]:
    """Return (voucher_type, rationale). Checks GSTIN direction first, then keyword fallback."""
    vendor_gstin = (data.get("vendor_gstin") or data.get("gstin") or "").strip()
    buyer_gstin = (data.get("buyer_gstin") or "").strip()
    if company_gstin:
        company_gstin = company_gstin.strip().upper()
        if vendor_gstin and vendor_gstin.upper() == company_gstin:
            return VoucherType.SALES, f"GSTIN match: vendor={vendor_gstin} is company's own GSTIN → Sales"
        if buyer_gstin and buyer_gstin.upper() == company_gstin:
            return VoucherType.PURCHASE, f"GSTIN match: buyer={buyer_gstin} is company's own GSTIN → Purchase"
    vendor = (data.get("vendor_name") or "").lower()
    items = data.get("line_items") or []
    descriptions = " ".join(
        (item.get("description") or "") for item in items
    ).lower()
    text = f"{vendor} {descriptions}"
    for keywords, vtype, reason in _VOUCHER_KEYWORDS:
        if any(kw in text for kw in keywords):
            return vtype, f"Keyword match: {reason}"
    return default_type, f"Defaulted to {default_type.value} (covers ~85% of invoices)"


def classify_service_vs_goods(line_items: list) -> bool:
    if not line_items:
        return False
    service_score = 0
    goods_score = 0
    for item in line_items:
        desc = (item.get("description", "") or "").lower()
        hsn = (item.get("hsn_sac", "") or "").strip()
        if hsn.startswith("99"):
            service_score += 2
        elif hsn and not hsn.startswith("99"):
            goods_score += 2
        service_score += sum(1 for kw in SERVICE_KEYWORDS if kw in desc)
        goods_score += sum(1 for kw in GOODS_KEYWORDS if kw in desc)
    if service_score > goods_score:
        return True
    if goods_score > service_score:
        return False
    return False
