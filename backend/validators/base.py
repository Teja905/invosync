"""Base classes for the validation engine — ValidationResult and ValidationScore."""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ValidationCheck:
    name: str
    passed: bool
    message: str
    category: str = "general"
    severity: str = "error"  # error, warning, info
    details: Optional[dict] = None


@dataclass
class ValidationResult:
    passed: bool = True
    checks: list[ValidationCheck] = field(default_factory=list)

    @property
    def errors(self) -> list[str]:
        return [c.message for c in self.checks if not c.passed and c.severity == "error"]

    @property
    def warnings(self) -> list[str]:
        return [c.message for c in self.checks if c.severity == "warning"]

    @property
    def blocking_errors(self) -> list[str]:
        """Errors that hard-block XML generation regardless of force."""
        return [c.message for c in self.checks if not c.passed and c.severity == "error" and c.category in ("balance", "date", "mandatory")]

    @property
    def soft_errors(self) -> list[str]:
        """Errors that allow override via force=true."""
        return [c.message for c in self.checks if not c.passed and c.severity == "error" and c.category not in ("balance", "date", "mandatory")]

    def add_error(self, name: str, message: str, category: str = "general", details: Optional[dict] = None):
        self.checks.append(ValidationCheck(name=name, passed=False, message=message, category=category, severity="error", details=details))
        self.passed = False

    def add_warning(self, message: str, category: str = "general", details: Optional[dict] = None):
        self.checks.append(ValidationCheck(name="", passed=True, message=message, category=category, severity="warning", details=details))

    def add_info(self, message: str, category: str = "general", details: Optional[dict] = None):
        self.checks.append(ValidationCheck(name="", passed=True, message=message, category=category, severity="info", details=details))

    def to_legacy_dict(self) -> dict:
        """Convert to the old flat dict format for backward compatibility."""
        errors = self.errors
        warnings = self.warnings
        return {
            "passed": self.passed,
            "errors": errors,
            "warnings": warnings,
            "checks": {c.name: {"pass": c.passed, "message": c.message} for c in self.checks if c.name},
            "blocking_errors": self.blocking_errors,
            "soft_errors": self.soft_errors,
        }


@dataclass
class ValidationScore:
    """Overall readiness score for an invoice.

    score: 0-100 (100 = production ready)
    breakdown: dict of category → score
    blocking: list of blocking issues (score = 0 until resolved)
    warnings: list of non-blocking issues
    """
    score: float = 100.0
    breakdown: dict[str, float] = field(default_factory=dict)
    blocking: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    passed: bool = True

    WEIGHTS = {
        "accounting": 0.30,
        "gst": 0.25,
        "voucher": 0.20,
        "xml": 0.15,
        "masters": 0.10,
    }

    @classmethod
    def from_validation(cls, result: ValidationResult) -> "ValidationScore":
        """Compute score from a ValidationResult."""
        total_checks = len(result.checks)
        if total_checks == 0:
            return cls(score=100.0, passed=True)

        failed = sum(1 for c in result.checks if not c.passed)
        warnings = [c.message for c in result.checks if c.severity == "warning"]

        if failed == 0:
            base_score = 100.0
        else:
            base_score = max(0, 100.0 - (failed / total_checks) * 100.0)

        # Penalize for blocking errors
        blocking = result.blocking_errors
        if blocking:
            base_score = min(base_score, 50.0)
            base_score *= 0.5

        # Penalize for soft errors
        soft = result.soft_errors
        soft_penalty = len(soft) * 5.0
        base_score = max(0, base_score - soft_penalty)

        # Categorize
        categories = {}
        for c in result.checks:
            cat = c.category
            if cat not in categories:
                categories[cat] = {"total": 0, "failed": 0}
            categories[cat]["total"] += 1
            if not c.passed:
                categories[cat]["failed"] += 1

        breakdown = {}
        for cat, counts in categories.items():
            if counts["total"] > 0:
                cat_score = max(0, 100.0 - (counts["failed"] / counts["total"]) * 100.0)
                breakdown[cat] = round(cat_score, 1)

        return cls(
            score=round(base_score, 1),
            breakdown=breakdown,
            blocking=blocking,
            warnings=warnings,
            passed=base_score >= 80.0,
        )

    def to_dict(self) -> dict:
        return {
            "score": self.score,
            "breakdown": self.breakdown,
            "blocking": self.blocking,
            "warnings": self.warnings,
            "passed": self.passed,
            "production_ready": self.score >= 90.0,
            "needs_review": 80.0 <= self.score < 90.0,
            "blocked": self.score < 80.0,
        }
