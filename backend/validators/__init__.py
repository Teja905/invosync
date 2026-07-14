"""Validators package — deterministic accounting validation engine.

Architecture:
  StandardizedInvoice → AccountingValidator → XML Generator → XMLValidator
  → RoundTripTest → TallyValidator → PostImportValidator

Every validator returns a ValidationScore (0-100) with structured results.
"""

from validators.base import ValidationResult, ValidationScore
from validators.accounting_validator import AccountingValidator
from validators.xml_validator import XMLValidator
from validators.round_trip import RoundTripValidator

__all__ = [
    "ValidationResult",
    "ValidationScore",
    "AccountingValidator",
    "XMLValidator",
    "RoundTripValidator",
]
