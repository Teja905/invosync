"""Centralized configuration — env vars, company config fields, default user builder."""

import os

from crypto_utils import encrypt, decrypt
from company_config import CompanyConfig
from xml_generator import TallyXmlGenerator
from schemas import StandardizedInvoice
from validators.pipeline import ValidationPipeline

COMPANY_CONFIG_FIELDS = [
    "company_name", "company_gstin", "company_state_code",
    "purchase_ledger", "sales_ledger", "bank_ledger",
    "tds_ledger", "round_off_ledger", "freight_ledger", "suspense_ledger",
    "sundry_creditors_group", "sundry_debtors_group",
    "purchase_accounts_group", "sales_accounts_group",
    "bank_accounts_group", "current_liabilities_group",
    "duties_taxes_group",
    "correction_memory",
    "masters_created",
    "active_company",
    "active_company_id",
    "tally_password",
]

ENCRYPTED_FIELDS = {"tally_password"}

# Per-user in-memory config overrides (auth disabled in demo)
config_overrides: dict[str, dict] = {}


def user_config_from_current(current_user: dict) -> dict:
    """Extract company config fields from current_user (enriched from DB)."""
    cfg = {}
    for field in COMPANY_CONFIG_FIELDS:
        val = current_user.get(field)
        if val:
            if field in ENCRYPTED_FIELDS:
                val = decrypt(val)
            cfg[field] = val.strip() if isinstance(val, str) else val
    return cfg


def make_xml_generator(user_cfg: dict, default_config: CompanyConfig) -> tuple[TallyXmlGenerator, CompanyConfig, str]:
    """Create a per-request XML generator with user config overrides.
    Returns (generator, config, active_company).
    Automatically sets reuse_masters=True if masters already created for this company."""
    active_company = ""
    masters_created = False
    if user_cfg:
        masters_created = bool(user_cfg.pop("masters_created", False))
        active_company = user_cfg.pop("active_company", "") or ""
    cfg = default_config
    if user_cfg:
        cfg = CompanyConfig(user_config=user_cfg)
    gen = TallyXmlGenerator(cfg)
    gen.masters_created = masters_created
    return gen, cfg, active_company


def run_validation_pipeline(standard: StandardizedInvoice, xml_str: str) -> dict:
    """Run the full validation pipeline and return a validation report dict.
    Called automatically on every XML generation — no user action needed.
    """
    from core.logging import get_logger
    logger = get_logger(__name__)
    try:
        pipeline = ValidationPipeline()
        report = pipeline.run(standard, xml_str)
        return report.to_dict()
    except Exception as e:
        logger.error("VALIDATION PIPELINE ERROR: %s", e)
        return {
            "scores": {"total": 0},
            "passed": False,
            "ready_for_tally": False,
            "errors": [f"Pipeline error: {str(e)}"],
            "warnings": [],
            "error_count": 1,
            "warning_count": 0,
        }


async def default_user() -> dict:
    """Return default user config from env vars + any in-memory overrides (no auth required)."""
    import database as db
    base = {
        "email": "default@local",
        "user_id": "default",
        "role": "admin",
        "company_name": os.getenv("COMPANY_NAME", ""),
        "company_gstin": os.getenv("COMPANY_GSTIN", ""),
        "company_state_code": os.getenv("COMPANY_STATE_CODE", ""),
        "purchase_ledger": os.getenv("PURCHASE_LEDGER", "Purchase"),
        "sales_ledger": os.getenv("SALES_LEDGER", "Sales"),
        "bank_ledger": os.getenv("BANK_LEDGER", "Bank"),
        "tds_ledger": os.getenv("TDS_PAYABLE_LEDGER", "TDS Payable"),
        "round_off_ledger": os.getenv("ROUND_OFF_LEDGER", "Round Off"),
        "freight_ledger": os.getenv("FREIGHT_LEDGER", "Freight Expenses"),
        "suspense_ledger": os.getenv("SUSPENSE_LEDGER", "Suspense"),
        "sundry_creditors_group": os.getenv("SUNDRY_CREDITORS_GROUP", "Sundry Creditors"),
        "sundry_debtors_group": os.getenv("SUNDRY_DEBTORS_GROUP", "Sundry Debtors"),
        "purchase_accounts_group": os.getenv("PURCHASE_ACCOUNTS_GROUP", "Purchase Accounts"),
        "sales_accounts_group": os.getenv("SALES_ACCOUNTS_GROUP", "Sales Accounts"),
        "bank_accounts_group": os.getenv("BANK_ACCOUNTS_GROUP", "Bank Accounts"),
        "current_liabilities_group": os.getenv("CURRENT_LIABILITIES_GROUP", "Current Liabilities"),
        "duties_taxes_group": os.getenv("DUTIES_TAXES_GROUP", "Duties & Taxes"),
        "correction_memory": {},
        "tally_password": os.getenv("TALLY_PASSWORD", ""),
    }
    user_id = "default"
    base.update({k: v for k, v in config_overrides.get(user_id, {}).items() if v})
    if db.organizations is not None:
        try:
            org = await db.organizations.find_one({"org_id": user_id})
            if org:
                if org.get("active_company"):
                    base["active_company"] = org["active_company"]
                if org.get("active_company_id"):
                    base["active_company_id"] = org["active_company_id"]
        except Exception:
            pass
    return base
