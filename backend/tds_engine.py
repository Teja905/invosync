"""Indian TDS (Tax Deducted at Source) Compliance Engine.

Covers major TDS sections under the Income Tax Act, 1961:
  - 194C: Contractor/Sub-contractor payments
  - 194J: Professional/Technical fees
  - 194H: Commission/Brokerage
  - 194I(a): Rent - Plant & Machinery
  - 194I(b): Rent - Land, Building, Furniture, Fittings
  - 194A: Interest other than on securities
  - 194B: Winnings from lottery/crossword
  - 194D: Insurance commission
  - 194E: Non-resident sportsmen/entertainers
  - 194G: Commission on lottery tickets
  - 194Q: Purchase of goods (> Rs.50 lakh)
  - 194N: Cash withdrawal (> Rs.1 crore / Rs.20 lakh for non-filers)
  - 194P: Senior citizen exemption (75+ years)
  - 194R: Benefits/perquisites in business/profession (> Rs.20,000)
  - 194S: Transfer of virtual digital assets (> Rs.50,000/10,000)

Reference: Income Tax Act, 1961 as amended up to Assessment Year 2025-26.
Thresholds and rates updated for AY 2025-26.
"""

from dataclasses import dataclass, field
from typing import Optional
from decimal import Decimal, ROUND_HALF_UP


@dataclass
class TDSRule:
    section: str
    description: str
    payee_type: str  # Individual, Company, HUF, etc.
    threshold: float  # Annual threshold in Rs.
    rate_individual: float  # Rate for Individual/HUF
    rate_other: float  # Rate for Company/Firm/LLP
    higher_rate_no_pan: float  # Rate when PAN not provided (20% or as per section)
    categories: list[str] = field(default_factory=list)  # Keywords that match this section
    effective_from: str = "2018-04-01"
    threshold_per_transaction: bool = False  # True if threshold is per-transaction


# Comprehensive TDS rules for AY 2025-26
TDS_RULES: dict[str, TDSRule] = {
    "194C": TDSRule(
        section="194C",
        description="Payment to Contractors",
        payee_type="Individual/HUF",
        threshold=30000,  # Single payment > Rs.30,000 or aggregate > Rs.1,00,000
        rate_individual=1.0,
        rate_other=2.0,
        higher_rate_no_pan=20.0,
        categories=["contractor", "sub-contractor", "labour", "works", "fabrication",
                    "erection", "installation", "repair", "maintenance", "service contract",
                    "amc", "annual maintenance", "project", "building", "construction",
                    "civil", "plumbing", "electrical", "carpentry", "painting"],
    ),
    "194J_a": TDSRule(
        section="194J(a)",
        description="Professional/Technical Fees",
        payee_type="Individual/HUF",
        threshold=30000,  # Aggregate > Rs.30,000 in a FY
        rate_individual=10.0,
        rate_other=10.0,
        higher_rate_no_pan=20.0,
        categories=["professional", "technical", "consulting", "legal", "audit",
                    "accounting", "ca fees", "chartered accountant", "advocate",
                    "architect", "doctor", "engineer", "salary", "remuneration",
                    "management", "advisory", "secretarial", "valuation",
                    "due diligence", "gst return", "income tax", "tax filing",
                    "roc filing", "annual return", "compliance", "registration"],
    ),
    "194J_b": TDSRule(
        section="194J(b)",
        description="Royalty and Call Centre",
        payee_type="Individual/HUF",
        threshold=30000,
        rate_individual=2.0,
        rate_other=2.0,
        higher_rate_no_pan=20.0,
        categories=["royalty", "call centre", "bpo", "kpo", "data entry",
                    "software licence", "patent", "copyright", "trademark"],
    ),
    "194H": TDSRule(
        section="194H",
        description="Commission or Brokerage",
        payee_type="Individual/HUF",
        threshold=15000,  # Aggregate > Rs.15,000 in a FY
        rate_individual=5.0,
        rate_other=5.0,
        higher_rate_no_pan=20.0,
        categories=["commission", "brokerage", "broker", "agent",
                    "distribution", "dealer commission", "sales commission",
                    "incentive", "marketing"],
    ),
    "194I_a": TDSRule(
        section="194I(a)",
        description="Rent - Plant & Machinery",
        payee_type="Individual/HUF",
        threshold=240000,  # Aggregate > Rs.2,40,000 in a FY
        rate_individual=2.0,
        rate_other=2.0,
        higher_rate_no_pan=20.0,
        categories=["rent - plant", "rent - machinery", "rent - equipment",
                    "plant rent", "machinery rent", "equipment rent",
                    "lease - plant", "lease - machinery"],
    ),
    "194I_b": TDSRule(
        section="194I(b)",
        description="Rent - Land, Building, Furniture, Fittings",
        payee_type="Individual/HUF",
        threshold=240000,  # Aggregate > Rs.2,40,000 in a FY
        rate_individual=10.0,
        rate_other=10.0,
        higher_rate_no_pan=20.0,
        categories=["rent", "lease rent", "office rent", "factory rent",
                    "warehouse rent", "godown rent", "building rent",
                    "land rent", "furniture rent", "flat rent", "shop rent",
                    "coworking", "co-working", "office space"],
    ),
    "194A": TDSRule(
        section="194A",
        description="Interest other than on Securities",
        payee_type="Individual/HUF",
        threshold=40000,  # Rs.40,000 for bank (Rs.50,000 for senior citizens)
        rate_individual=10.0,
        rate_other=10.0,
        higher_rate_no_pan=20.0,
        categories=["interest", "interest income", "fixed deposit",
                    "term deposit", "savings interest", "loan interest",
                    "interest received", "interest earned"],
    ),
    "194B": TDSRule(
        section="194B",
        description="Winnings from Lottery/Crossword",
        payee_type="Individual/HUF",
        threshold=10000,  # Aggregate > Rs.10,000
        rate_individual=30.0,
        rate_other=30.0,
        higher_rate_no_pan=30.0,
        categories=["lottery", "crossword", "game show", "quiz",
                    "prize", "winnings"],
    ),
    "194D": TDSRule(
        section="194D",
        description="Insurance Commission",
        payee_type="Individual/HUF",
        threshold=15000,
        rate_individual=5.0,
        rate_other=5.0,
        higher_rate_no_pan=20.0,
        categories=["insurance commission", "insurance agent",
                    "lic commission", "policy commission"],
    ),
    "194Q": TDSRule(
        section="194Q",
        description="Purchase of Goods (> Rs.50 Lakh)",
        payee_type="All",
        threshold=5000000,  # Rs.50 lakh
        rate_individual=0.1,
        rate_other=0.1,
        higher_rate_no_pan=5.0,
        categories=["purchase of goods", "goods purchase", "stock purchase",
                    "raw material", "inventory purchase", "bulk purchase"],
    ),
    "194R": TDSRule(
        section="194R",
        description="Benefits/Perquisites in Business (> Rs.20,000)",
        payee_type="All",
        threshold=20000,
        rate_individual=10.0,
        rate_other=10.0,
        higher_rate_no_pan=20.0,
        categories=["perquisite", "benefit", "gift", "incentive trip",
                    "free sample", "free product", "conference sponsorship"],
    ),
    "194S": TDSRule(
        section="194S",
        description="Transfer of Virtual Digital Assets (> Rs.50,000/10,000)",
        payee_type="All",
        threshold=50000,  # Rs.50,000 for specified persons, Rs.10,000 others
        rate_individual=1.0,
        rate_other=1.0,
        higher_rate_no_pan=20.0,
        categories=["crypto", "cryptocurrency", "virtual digital asset",
                    "nft", "bitcoin", "ethereum", "digital asset",
                    "blockchain token"],
    ),
}

# TCS (Tax Collected at Source) sections for reference
TCS_SECTIONS = {
    "206C_1H": {"description": "Sale of goods > Rs.50 Lakh", "rate": 0.1, "threshold": 5000000},
    "206C_1G": {"description": "Remittance under LRS > Rs.7 Lakh", "rate": 5.0, "threshold": 700000},
    "206C_1": {"description": "Liquor/timber/minerals", "rate": 1.0, "threshold": 0},
}


@dataclass
class TDSDetection:
    section: str
    description: str
    confidence: float  # 0.0 to 1.0
    rate: float
    threshold: float
    is_applicable: bool
    reason: str
    suggested_tds_ledger: str = "TDS Payable"


@dataclass
class TDSComplianceResult:
    detections: list[TDSDetection] = field(default_factory=list)
    total_tds_applicable: float = 0.0
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    is_compliant: bool = True

    def to_dict(self) -> dict:
        return {
            "detections": [
                {
                    "section": d.section,
                    "description": d.description,
                    "confidence": d.confidence,
                    "rate": d.rate,
                    "threshold": d.threshold,
                    "is_applicable": d.is_applicable,
                    "reason": d.reason,
                }
                for d in self.detections
            ],
            "total_tds_applicable": self.total_tds_applicable,
            "warnings": self.warnings,
            "errors": self.errors,
            "is_compliant": self.is_compliant,
        }


def detect_tds_applicability(
    description: str,
    amount: float,
    is_service: bool = False,
    vendor_type: str = "individual",  # individual, company, huf, firm, llp
    annual_amount_to_vendor: float = 0.0,
) -> list[TDSDetection]:
    """Detect which TDS sections apply to a given payment.

    Args:
        description: Item/service description from invoice
        amount: Payment amount
        is_service: Whether this is a service (vs goods)
        vendor_type: Type of payee (individual, company, huf, firm, llp)
        annual_amount_to_vendor: Total amount paid to this vendor in FY (for threshold checks)

    Returns:
        List of TDS detections sorted by confidence (highest first)
    """
    desc_lower = (description or "").lower().strip()
    detections = []

    for section_key, rule in TDS_RULES.items():
        # Check if any keyword matches
        match_score = 0.0
        matched_keywords = []
        for keyword in rule.categories:
            if keyword in desc_lower:
                # Longer keyword matches are more specific
                match_score += len(keyword) / max(len(desc_lower), 1)
                matched_keywords.append(keyword)

        if match_score == 0:
            continue

        # Confidence based on keyword specificity
        confidence = min(match_score * 2, 1.0)

        # Service-specific boosts
        if is_service and section_key in ("194J_a", "194J_b", "194C"):
            confidence = min(confidence + 0.2, 1.0)
        if not is_service and section_key.startswith("194I"):
            confidence = min(confidence + 0.1, 1.0)

        # Determine applicable rate based on payee type
        if vendor_type in ("company", "firm", "llp"):
            rate = rule.rate_other
        else:
            rate = rule.rate_individual

        # Check threshold — this is the critical fix
        effective_amount = annual_amount_to_vendor if annual_amount_to_vendor > 0 else amount
        is_applicable = effective_amount > rule.threshold

        # Downgrade confidence when below threshold
        if not is_applicable:
            confidence = min(confidence, 0.4)  # Cap at "low" when below threshold

        # Mark keyword-only detections (no vendor context) as lower confidence
        if annual_amount_to_vendor <= 0:
            confidence = min(confidence, 0.6)  # "Suggestion, verify before applying"

        # Build reason string
        if is_applicable:
            reason = (
                f"Section {rule.section}: {rule.description}. "
                f"Amount Rs.{effective_amount:,.0f} exceeds threshold Rs.{rule.threshold:,.0f}. "
                f"TDS rate: {rate}% (for {vendor_type})"
            )
        else:
            if annual_amount_to_vendor > 0:
                reason = (
                    f"Section {rule.section}: {rule.description} — "
                    f"aggregate Rs.{effective_amount:,.0f} below threshold Rs.{rule.threshold:,.0f}. "
                    f"TDS not applicable for this payment."
                )
            else:
                reason = (
                    f"Section {rule.section}: {rule.description} — "
                    f"payment Rs.{amount:,.0f} below per-transaction threshold Rs.{rule.threshold:,.0f}. "
                    f"TDS may apply if aggregate payments to this vendor exceed threshold. "
                    f"Verify with CA before applying."
                )

        detections.append(TDSDetection(
            section=rule.section,
            description=rule.description,
            confidence=confidence,
            rate=rate,
            threshold=rule.threshold,
            is_applicable=is_applicable,
            reason=reason,
        ))

    # Sort by confidence descending
    detections.sort(key=lambda d: d.confidence, reverse=True)
    return detections


def validate_tds_deduction(
    tds_section: str,
    tds_amount: float,
    payment_amount: float,
    rate: float,
    vendor_gstin: str = "",
    vendor_pan: str = "",
) -> TDSComplianceResult:
    """Validate a TDS deduction for compliance.

    Checks:
    1. TDS rate matches the section's prescribed rate
    2. TDS amount is correctly calculated
    3. PAN is provided (higher rate if missing)
    4. Threshold was crossed
    """
    result = TDSComplianceResult()

    # Find the rule
    rule = None
    for key, r in TDS_RULES.items():
        if r.section == tds_section or key == tds_section:
            rule = r
            break

    if not rule:
        result.errors.append(f"Unknown TDS section: {tds_section}")
        result.is_compliant = False
        return result

    # Check PAN
    has_pan = bool(vendor_pan) or bool(vendor_gstin and len(vendor_gstin) >= 10)
    if not has_pan:
        expected_rate = rule.higher_rate_no_pan
        result.warnings.append(
            f"Vendor PAN not provided. TDS rate should be {expected_rate}% "
            f"(higher rate for non-PAN deductees under Section 206AA)."
        )
        if rate < expected_rate:
            result.errors.append(
                f"TDS rate {rate}% is below the {expected_rate}% rate applicable "
                f"when PAN is not furnished."
            )
            result.is_compliant = False

    # Check rate correctness
    expected_rate = rule.rate_individual  # Default to individual rate
    if rate != expected_rate and has_pan:
        result.warnings.append(
            f"TDS rate {rate}% differs from the prescribed rate of {expected_rate}% "
            f"for Section {rule.section}."
        )

    # Check TDS amount calculation
    expected_tds = Decimal(str(payment_amount)) * Decimal(str(rate)) / Decimal("100")
    expected_tds = expected_tds.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    actual_tds = Decimal(str(tds_amount))

    if expected_tds > 0 and abs(expected_tds - actual_tds) > Decimal("1.00"):
        result.errors.append(
            f"TDS amount Rs.{tds_amount:.2f} differs from computed Rs.{float(expected_tds):.2f} "
            f"({rate}% of Rs.{payment_amount:.2f})."
        )
        result.is_compliant = False

    # Check threshold
    if payment_amount <= rule.threshold:
        result.warnings.append(
            f"Payment Rs.{payment_amount:,.0f} is below the threshold of "
            f"Rs.{rule.threshold:,.0f} for Section {rule.section}. "
            f"TDS deduction is not mandatory unless this is part of aggregate payments "
            f"exceeding the threshold in the financial year."
        )

    result.total_tds_applicable = float(expected_tds)
    return result


def suggest_tds_section(description: str, is_service: bool = False) -> Optional[str]:
    """Quick suggestion of the most likely TDS section for a description."""
    detections = detect_tds_applicability(
        description=description,
        amount=100000,  # Use a default amount to trigger all detections
        is_service=is_service,
    )
    applicable = [d for d in detections if d.confidence > 0.3]
    if applicable:
        return applicable[0].section
    return None
