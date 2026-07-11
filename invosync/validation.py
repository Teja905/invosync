import re
from models import InvoiceRequest, ValidationResult, ValidationError


GSTIN_PATTERN = re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z]{1}\d{1}[Z]{1}[A-Z\d]{1}$")
DATE_PATTERN_1 = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DATE_PATTERN_2 = re.compile(r"^\d{2}/\d{2}/\d{4}$")


def validate_invoice(data: InvoiceRequest) -> ValidationResult:
    errors = []
    warnings = []

    e = _check_required("company_gstin", data.company_gstin)
    if e:
        errors.append(e)
    else:
        gst_err = _validate_gstin("company_gstin", data.company_gstin)
        if gst_err:
            errors.append(gst_err)

    e = _check_required("party_gstin", data.party_gstin)
    if e:
        errors.append(e)
    else:
        gst_err = _validate_gstin("party_gstin", data.party_gstin)
        if gst_err:
            errors.append(gst_err)

    e = _check_required("party_name", data.party_name)
    if e:
        errors.append(e)

    e = _check_required("invoice_number", data.invoice_number)
    if e:
        errors.append(e)

    date_err = _validate_date(data.invoice_date)
    if date_err:
        errors.append(date_err)

    amt_errs = _validate_amounts(data)
    errors.extend(amt_errs)

    rate_err = _validate_tax_rate(data.tax_rate)
    if rate_err:
        errors.append(rate_err)

    if data.line_items:
        item_errs = _validate_line_items(data)
        errors.extend(item_errs)

    line_item_total = sum(li.taxable_amount for li in data.line_items) if data.line_items else data.taxable_total
    if data.line_items and abs(line_item_total - data.taxable_total) > 0.02:
        warnings.append(
            f"Line item total ({line_item_total:.2f}) differs from taxable_total ({data.taxable_total:.2f})"
        )

    expected_tax = round(data.taxable_total * data.tax_rate / 100.0, 2)
    if abs(expected_tax - data.tax_total) > 0.02:
        warnings.append(
            f"Expected tax at {data.tax_rate}%: {expected_tax:.2f}, but tax_total is {data.tax_total:.2f}"
        )

    expected_grand = round(data.taxable_total + data.tax_total, 2)
    if abs(expected_grand - data.grand_total) > 0.02:
        warnings.append(
            f"Expected grand total (taxable + tax): {expected_grand:.2f}, but grand_total is {data.grand_total:.2f}"
        )

    return ValidationResult(valid=len(errors) == 0, errors=errors, warnings=warnings)


def _check_required(field: str, value: str) -> ValidationError | None:
    if not value or not value.strip():
        return ValidationError(field=field, message=f"{field} is required")
    return None


def _validate_gstin(field: str, gstin: str) -> ValidationError | None:
    cleaned = gstin.strip().upper()
    if not GSTIN_PATTERN.match(cleaned):
        return ValidationError(
            field=field,
            message=f"Invalid GSTIN format: {gstin}. Expected 15 chars: 2-digit state + 10-char PAN + 1 entity + Z + 1 check digit"
        )
    codepoints = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    total = 0
    for i, ch in enumerate(cleaned[:-1]):
        if ch not in codepoints:
            return ValidationError(field=field, message=f"Invalid character in GSTIN: {ch}")
        val = codepoints.index(ch)
        factor = 1 if i % 2 == 0 else 2
        product = val * factor
        total += product // 36 + product % 36
    remainder = total % 36
    expected_cd = codepoints[(36 - remainder) % 36]
    if cleaned[-1] != expected_cd:
        return ValidationError(
            field=field,
            message=f"GSTIN checksum failed: expected check digit '{expected_cd}', got '{cleaned[-1]}'"
        )
    return None


def _validate_date(date_str: str) -> ValidationError | None:
    if DATE_PATTERN_1.match(date_str) or DATE_PATTERN_2.match(date_str):
        return None
    return ValidationError(
        field="invoice_date",
        message=f"Invalid date format: {date_str}. Use YYYY-MM-DD or DD/MM/YYYY"
    )


def _validate_amounts(data: InvoiceRequest) -> list[ValidationError]:
    errors = []
    if data.taxable_total < 0:
        errors.append(ValidationError(field="taxable_total", message="taxable_total cannot be negative"))
    if data.tax_total < 0:
        errors.append(ValidationError(field="tax_total", message="tax_total cannot be negative"))
    if data.grand_total < 0:
        errors.append(ValidationError(field="grand_total", message="grand_total cannot be negative"))
    if data.tax_rate < 0:
        errors.append(ValidationError(field="tax_rate", message="tax_rate cannot be negative"))
    if abs(data.taxable_total + data.tax_total - data.grand_total) > 0.02:
        errors.append(ValidationError(
            field="grand_total",
            message=f"grand_total ({data.grand_total:.2f}) != taxable_total ({data.taxable_total:.2f}) + tax_total ({data.tax_total:.2f}) = {data.taxable_total + data.tax_total:.2f}"
        ))
    return errors


def _validate_tax_rate(rate: float) -> ValidationError | None:
    allowed = {0, 0.1, 0.25, 3, 5, 12, 18, 28}
    if rate in allowed:
        return None
    near = min(allowed, key=lambda x: abs(x - rate))
    if abs(rate - near) <= 0.5:
        return None
    return ValidationError(
        field="tax_rate",
        message=f"Tax rate {rate}% is not a valid Indian GST slab. Allowed: {sorted(allowed)}%. Nearest: {near}%"
    )


def _validate_line_items(data: InvoiceRequest) -> list[ValidationError]:
    errors = []
    for i, item in enumerate(data.line_items):
        if not item.description:
            errors.append(ValidationError(
                field=f"line_items[{i}].description",
                message=f"Line item {i}: description is required"
            ))
        if item.quantity <= 0:
            errors.append(ValidationError(
                field=f"line_items[{i}].quantity",
                message=f"Line item {i}: quantity must be > 0"
            ))
        if item.rate < 0:
            errors.append(ValidationError(
                field=f"line_items[{i}].rate",
                message=f"Line item {i}: rate cannot be negative"
            ))
        if item.taxable_amount < 0:
            errors.append(ValidationError(
                field=f"line_items[{i}].taxable_amount",
                message=f"Line item {i}: taxable_amount cannot be negative"
            ))
    return errors
