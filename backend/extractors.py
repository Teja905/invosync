"""Extraction via OpenRouter (primary, uses your API credits) with Gemini fallback."""

import asyncio
import base64
import io
import json
import os
import re
import time
from typing import Optional

import httpx
import google.generativeai as genai
from PIL import Image

from core.logging import get_logger
from core.debug import time_it
from core.pii import redact_pii
from core.ai_cache import SemanticCache
from core.hallucination_guard import compute_independent_confidence
from schemas import StandardizedInvoice, VoucherType
from ocr_postproc import post_process_extracted, validate_invoice_math
from gst_engine import determine_gst_type

logger = get_logger(__name__)


def is_quota_error(exc: Exception) -> bool:
    """Detect quota / rate-limit exhaustion from a provider error.

    Gemini raises google.api_core.exceptions with 'RESOURCE_EXHAUSTED' or
    '429' in the message; OpenRouter returns HTTP 429. We match on the common
    signals so the pipeline can surface a clean, actionable message.
    """
    msg = str(exc).lower()
    return any(s in msg for s in (
        "quota", "resource_exhausted", "429", "rate limit", "rate_limit",
        "exceeded", "billing", "usage limit",
    ))


QUOTA_ERROR_MESSAGE = (
    "AI provider quota exceeded. The free Gemini tier is rate-limited; "
    "add a real OPENROUTER_API_KEY (openrouter.ai) in your deployment env, "
    "or enable billing on GEMINI_API_KEY. Extraction cannot continue until "
    "a working key is configured."
)


def normalize_image(image_bytes: bytes, mime_type: str = "", max_dim: int = 2048) -> tuple[bytes, str]:
    is_pdf = image_bytes[:4] == b"%PDF"
    if is_pdf:
        try:
            import fitz
            doc = fitz.open(stream=image_bytes, filetype="pdf")
            page = doc[0]
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
            img_bytes = pix.tobytes("jpeg")
            doc.close()
            return img_bytes, "image/jpeg"
        except Exception as e:
            raise RuntimeError(f"PDF conversion failed: {e}")
    import cv2 as cv
    import numpy as np
    try:
        arr = np.frombuffer(image_bytes, dtype=np.uint8)
        img = cv.imdecode(arr, cv.IMREAD_COLOR)
        if img is not None:
            h, w = img.shape[:2]
            if max(h, w) > max_dim:
                scale = max_dim / max(h, w)
                new_w, new_h = int(w * scale), int(h * scale)
                img = cv.resize(img, (new_w, new_h), interpolation=cv.INTER_AREA)
            ok, buf = cv.imencode(".jpg", img, [cv.IMWRITE_JPEG_QUALITY, 95])
            if ok:
                return buf.tobytes(), "image/jpeg"
    except Exception:
        pass
    try:
        img = Image.open(io.BytesIO(image_bytes))
        img.verify()
        img = Image.open(io.BytesIO(image_bytes))
        buf = io.BytesIO()
        img = img.convert("RGB")
        if max(img.size) > max_dim:
            scale = max_dim / max(img.size)
            new_size = (int(img.size[0] * scale), int(img.size[1] * scale))
            img = img.resize(new_size, Image.LANCZOS)
        img.save(buf, format="JPEG", quality=95)
        return buf.getvalue(), "image/jpeg"
    except Exception:
        pass
    return image_bytes, mime_type or "image/jpeg"


EXTRACT_PROMPT = """Extract invoice data from this image and return ONLY valid JSON (no markdown, no code fences).
Schema:
{
  "invoice_number": "invoice number",
  "invoice_date": "YYYY-MM-DD or DD/MM/YYYY",
  "vendor_name": "vendor/supplier name (full legal name)",
  "vendor_gstin": "vendor GSTIN (15 chars) or empty string",
  "vendor_address": "vendor address or null",
  "buyer_name": "buyer name if visible",
  "buyer_gstin": "buyer GSTIN if visible (15 chars)",
  "buyer_address": "buyer address if visible",
  "place_of_supply": "state name or code (e.g. 'Maharashtra' or '27')",
  "total_taxable_value": number (total before tax),
  "total_tax": number (total GST amount),
  "total_amount": number (grand total including tax),
  "line_items": [
    {
      "description": "item description (full, do not abbreviate)",
      "quantity": number,
      "rate": number (per unit price),
      "taxable_value": number (quantity x rate - discount),
      "tax_rate": number (GST rate % — must be 0, 0.1, 0.25, 3, 5, 12, 18, or 28),
      "hsn_sac": "HSN code for goods (4/6/8 digits) or SAC code for services (4-6 digits)",
      "is_service": boolean (true if service item),
      "discount": number or 0
    }
  ],
  "taxes": [
    {
      "name": "CGST/SGST/IGST with rate (e.g. 'Input CGST @ 9%')",
      "rate": number (rate %),
      "amount": number (tax amount),
      "type": "cgst" or "sgst" or "igst"
    }
  ],
  "freight": number or 0,
  "round_off": number or 0,
  "tds_amount": number or 0,
  "tds_rate": number (TDS rate % if deducted, e.g. 10 for 194J, 2 for 194C),
  "reverse_charge": boolean,
  "confidence": number between 0 and 1,
  "document_type": "tax_invoice" or "retail_bill" or "expense_receipt" or "proforma" or "credit_note" or "debit_note",
  "is_sez": boolean (true if SEZ supplier/buyer),
  "is_lut": boolean (true if LUT/Bond mentioned),
  "is_composition": boolean (true if composition dealer)
}

CRITICAL RULES:
1. GST rates MUST be from: 0, 0.1, 0.25, 3, 5, 12, 18, 28. Any other rate is invalid.
2. GSTIN must be exactly 15 characters: 2-digit state code + 10-char PAN + 1 entity digit + Z + 1 check digit.
3. HSN codes for goods: 4 digits (turnover <5cr), 6 digits (5-10cr), 8 digits (>10cr). SAC for services: 4-6 digits.
4. TDS sections: 194C (contractor, 1-2%), 194J (professional, 10%), 194H (commission, 5%), 194I (rent, 2-10%).
5. For CGST/SGST: both must be present and equal. For IGST: single entry only.
6. Date format: prefer YYYY-MM-DD. If DD/MM/YYYY, convert it.
7. Read every number carefully — OCR often misreads 8 as 3, 6 as 5, 1 as 7.
Return ONLY the JSON object."""

VERIFY_PROMPT = """You are an audit AI. A previous extraction produced the JSON below from an invoice image.
Your job is to find errors in it. Be adversarial: look for:
1. Numbers that don't add up (line item totals != header, tax math wrong)
2. Generic or made-up vendor names
3. Invalid dates or dates that don't match the image
4. GSTINs that don't look real
5. Line items that seem made up
6. Any field that looks like a hallucination

For each error, provide: field name, what was extracted, what it should be, and why you think so.

Return ONLY a JSON array of errors:
[
  {
    "field": "field_name",
    "extracted": "what the AI extracted",
    "expected": "what you think is correct",
    "reason": "why you think this is wrong"
  }
]

If you find no errors, return an empty array [].

Previous extraction:
{previous_json}"""


def _parse_response(text: str) -> dict:
    text = text.strip()
    # Fast path: direct JSON parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Markdown code block: extract content between ``` fences anywhere in text
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            pass
    # Last resort: find first { and last }
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass
    # If all parsing fails, return a minimal fallback with low confidence
    # This prevents the pipeline from crashing on garbage AI output
    logger.warning("Could not parse AI response as JSON — returning fallback")
    return {
        "vendor_name": "UNABLE TO EXTRACT",
        "total_amount": 0,
        "confidence": 0.0,
        "line_items": [],
        "_extraction_failed": True,
        "_error": "AI response was not valid JSON — manual entry required",
    }


class ExtractionResult:
    def __init__(self, data: dict, confidence: float, provider: str, model: str, usage: dict = None):
        self.data = data
        self.confidence = confidence
        self.provider = provider
        self.model = model
        self.usage = usage or {}


class OpenRouterExtractor:
    # Configurable model: set OPENROUTER_MODEL env var to override
    # Free options: meta-llama/llama-3.2-11b-vision:free (20 RPM, good for testing)
    # Cheap options: google/gemini-2.0-flash-001 ($0.04/1K images, 200 RPM)
    # Best quality: qwen/qwen-2.5-vl-72b-instruct ($0.10/1K images, 200 RPM)
    MODEL = os.getenv("OPENROUTER_MODEL", "meta-llama/llama-3.2-11b-vision:free")

    async def extract(self, image_bytes: bytes, mime_type: str) -> Optional[ExtractionResult]:
        api_key = os.getenv("OPENROUTER_API_KEY")
        if not api_key or api_key == "your_openrouter_key_here":
            return None

        b64 = base64.b64encode(image_bytes).decode("utf-8")
        data_url = f"data:{mime_type};base64,{b64}"

        payload = {
            "model": self.MODEL,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": EXTRACT_PROMPT},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                }
            ],
            "max_tokens": 4096,
            "temperature": 0.1,
        }

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    json=payload,
                    headers=headers,
                )
                if resp.status_code == 429:
                    retry_after = resp.headers.get("retry-after", "60")
                    raise RuntimeError(
                        f"Rate limited by OpenRouter. Retry after {retry_after}s. "
                        f"Model: {self.MODEL}. "
                        f"Tip: Set OPENROUTER_MODEL to a free model like "
                        f"'meta-llama/llama-3.2-11b-vision:free' for testing."
                    )
                if resp.status_code == 402:
                    raise RuntimeError(
                        "OpenRouter credits exhausted. Add credits at openrouter.ai/credits "
                        "or switch to a free model: meta-llama/llama-3.2-11b-vision:free"
                    )
                resp.raise_for_status()
                result = resp.json()
                text = result["choices"][0]["message"]["content"]
                usage = result.get("usage", {})
                data = _parse_response(text)
                conf = float(data.get("confidence") or 0.0)
                return ExtractionResult(data, conf, "openrouter", self.MODEL, usage=usage)
        except Exception as e:
            raise RuntimeError(f"OpenRouter error: {e}")


class GeminiExtractor:
    MODEL = "gemini-2.0-flash-001"

    async def extract(self, image_bytes: bytes, mime_type: str) -> Optional[ExtractionResult]:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key or api_key == "your_key_here":
            return None

        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(self.MODEL)
        try:
            response = await asyncio.wait_for(
                asyncio.to_thread(
                    model.generate_content,
                    [{"mime_type": mime_type, "data": image_bytes}, EXTRACT_PROMPT],
                ),
                timeout=60.0,
            )
            data = _parse_response(response.text)
            conf = float(data.get("confidence") or 0.0)
            usage = {}
            if hasattr(response, "usage_metadata") and response.usage_metadata:
                um = response.usage_metadata
                usage = {
                    "prompt_tokens": getattr(um, "prompt_token_count", 0),
                    "completion_tokens": getattr(um, "candidates_token_count", 0),
                    "total_tokens": getattr(um, "total_token_count", 0),
                }
            return ExtractionResult(data, conf, "gemini", self.MODEL, usage=usage)
        except asyncio.TimeoutError:
            raise TimeoutError("Gemini timed out after 60s")
        except Exception as e:
            err_msg = str(e)
            if not err_msg or err_msg == "Internal Server Error":
                err_msg = f"{type(e).__name__}: {e}"
            raise RuntimeError(f"Gemini API error: {err_msg}")


def _safe_float(val, default=0.0) -> float:
    """Safely convert any value to float. Returns default if conversion fails."""
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _normalize_to_standard(data: dict, provider: str, model: str, company_gstin: str = "") -> StandardizedInvoice:
    data = post_process_extracted(data)

    line_items = []
    for item in data.get("line_items", []):
        line_items.append({
            "description": item.get("description") or "",
            "quantity": _safe_float(item.get("quantity"), 1),
            "rate": _safe_float(item.get("rate")),
            "taxable_value": _safe_float(item.get("taxable_value")),
            "tax_rate": _safe_float(item.get("tax_rate")),
            "hsn_sac": item.get("hsn_sac") or "",
            "is_service": bool(item.get("is_service", False)),
            "discount": _safe_float(item.get("discount")),
            "unit": item.get("unit") or "Nos",
        })

    company_state = os.getenv("COMPANY_STATE_CODE", "27")
    vendor_gstin = data.get("vendor_gstin") or data.get("gstin") or ""
    buyer_gstin = data.get("buyer_gstin") or ""
    is_sez = bool(data.get("is_sez", False))
    is_lut = bool(data.get("is_lut", False))
    is_composition = bool(data.get("is_composition", False))
    gst_type, is_interstate = determine_gst_type(
        vendor_gstin, buyer_gstin, company_state,
        is_sez=is_sez, is_lut=is_lut, is_composition=is_composition,
    )

    total_taxable = _safe_float(data.get("total_taxable_value"))
    total_tax = _safe_float(data.get("total_tax"))
    total_amount = _safe_float(data.get("total_amount"))
    freight = float(data.get("freight", 0) or 0)
    round_off = float(data.get("round_off", 0) or 0)
    tds_amount = float(data.get("tds_amount", 0) or 0)
    tds_rate = float(data.get("tds_rate", 0) or 0)

    doc_type = data.get("document_type", "")
    if not company_gstin:
        company_gstin = os.getenv("COMPANY_GSTIN", "")
    is_service = data.get("is_service", False) or any(
        item.get("is_service", False) for item in data.get("line_items", [])
    )

    # Handle taxes array from AI extraction
    taxes_raw = data.get("taxes", [])
    from schemas import TaxEntry
    taxes = []
    for t in taxes_raw:
        if isinstance(t, dict):
            taxes.append(TaxEntry(
                name=t.get("name", ""),
                rate=float(t.get("rate", 0) or 0),
                amount=float(t.get("amount", 0) or 0),
                type=t.get("type", ""),
                is_input=True,
            ))

    # Handle place_of_supply
    pos = data.get("place_of_supply") or ""
    if not pos and not buyer_gstin:
        pos = company_state  # Fallback to company state

    voucher_type = VoucherType.PURCHASE
    if vendor_gstin and company_gstin and vendor_gstin.upper() == company_gstin.upper():
        voucher_type = VoucherType.SALES
    elif buyer_gstin and company_gstin and buyer_gstin.upper() == company_gstin.upper():
        voucher_type = VoucherType.PURCHASE
    else:
        doc_lower = doc_type.lower()
        if doc_lower in ("retail_bill", "expense_receipt", "proforma", "purchase_invoice"):
            voucher_type = VoucherType.PURCHASE
        elif doc_lower == "service_invoice" and is_service:
            pass
        elif doc_lower == "tax_invoice":
            pass
    logger.info("VOUCHER CLASSIFICATION: document_type=%r is_service=%s vendor_gstin=%r company_gstin=%r > voucher_type=%s",
                doc_type, is_service, redact_pii(vendor_gstin), redact_pii(company_gstin), voucher_type.value)

    return StandardizedInvoice(
        invoice_number=data.get("invoice_number") or "",
        invoice_date=data.get("invoice_date") or data.get("date") or "",
        vendor_name=data.get("vendor_name") or "",
        vendor_gstin=vendor_gstin,
        vendor_address=data.get("vendor_address") or "",
        buyer_name=data.get("buyer_name") or "",
        buyer_gstin=buyer_gstin,
        buyer_address=data.get("buyer_address") or "",
        place_of_supply=pos,
        total_taxable_value=float(total_taxable),
        total_tax=float(total_tax),
        total_amount=float(total_amount),
        freight=freight,
        round_off=round_off,
        tds_amount=tds_amount,
        tds_rate=tds_rate,
        line_items=line_items,
        taxes=taxes,
        is_service=is_service,
        is_interstate=is_interstate,
        is_sez=is_sez,
        is_lut=is_lut,
        is_composition=is_composition,
        gst_type=gst_type,
        confidence=float(data.get("confidence", 0) or 0),
        voucher_type=voucher_type,
        _provider=provider,
        _model=model,
    )


class CircuitBreaker:
    """Tracks consecutive provider failures with cooldown.
    After `threshold` failures, circuit opens for `cooldown_sec` seconds.
    """
    def __init__(self, threshold: int = 3, cooldown_sec: int = 60):
        self.threshold = threshold
        self.cooldown_sec = cooldown_sec
        self._failures = 0
        self._open_until = 0.0

    def record_failure(self):
        self._failures += 1
        if self._failures >= self.threshold:
            self._open_until = time.monotonic() + self.cooldown_sec
            logger.warning("Circuit opened — pausing provider for %ss after %d failures",
                           self.cooldown_sec, self._failures)

    def record_success(self):
        self._failures = 0
        self._open_until = 0.0

    def reset(self):
        """Reset circuit breaker state — allows retry with clean slate."""
        self._failures = 0
        self._open_until = 0.0

    @property
    def is_open(self) -> bool:
        if self._open_until and time.monotonic() < self._open_until:
            return True
        if self._open_until:
            self._failures = 0
            self._open_until = 0.0
        return False


class ExtractionPipeline:
    def __init__(self, cache: SemanticCache = None):
        self.openrouter = OpenRouterExtractor()
        self.gemini = GeminiExtractor()
        self._circuits = {
            "openrouter": CircuitBreaker(),
            "gemini": CircuitBreaker(),
        }
        self.last_provider: str = ""
        self.last_model: str = ""
        self.cache = cache

    @time_it
    async def extract(self, image_bytes: bytes, mime_type: str, company_gstin: str = "") -> dict:
        image_bytes, mime_type = normalize_image(image_bytes, mime_type)

        # --- Cache lookup (skip AI call if exact image hash matches) ---
        if self.cache:
            cached = await self.cache.get(image_bytes)
            if cached is not None:
                logger.info("CACHE HIT: returning cached extraction for sha256=%s", self.cache._make_key(image_bytes)[:12])
                raw_data = cached.get("_raw", cached)
                return self._finalize(raw_data, company_gstin)

        result = None
        max_retries = 3
        base_delay = 1.0

        for attempt in range(max_retries):
            if result is not None:
                break

            if not self._circuits["openrouter"].is_open:
                try:
                    result = await self.openrouter.extract(image_bytes, mime_type)
                    if result:
                        self._circuits["openrouter"].record_success()
                        self.last_provider = result.provider
                        self.last_model = result.model
                        if result.usage:
                            result.data["_usage"] = result.usage
                        logger.info("Extracted via OpenRouter (%s)", result.model)
                except Exception as e:
                    if is_quota_error(e):
                        logger.warning("OpenRouter quota/rate-limit: %s", e)
                    else:
                        self._circuits["openrouter"].record_failure()
                        logger.warning("OpenRouter failed (attempt %d/%d): %s",
                                       attempt + 1, max_retries, e)
                        if attempt < max_retries - 1:
                            delay = base_delay * (2 ** attempt)
                            logger.info("Retrying OpenRouter in %.1fs", delay)
                            await asyncio.sleep(delay)

            if result is None and not self._circuits["gemini"].is_open:
                try:
                    result = await self.gemini.extract(image_bytes, mime_type)
                    if result:
                        self._circuits["gemini"].record_success()
                        self.last_provider = result.provider
                        self.last_model = result.model
                        if result.usage:
                            result.data["_usage"] = result.usage
                        logger.info("Extracted via Gemini (%s)", result.model)
                except Exception as e:
                    self._circuits["gemini"].record_failure()
                    if is_quota_error(e):
                        raise RuntimeError(QUOTA_ERROR_MESSAGE)
                    if attempt < max_retries - 1:
                        delay = base_delay * (2 ** attempt)
                        logger.info("Retrying Gemini in %.1fs", delay)
                        await asyncio.sleep(delay)
                    else:
                        raise RuntimeError(f"Extraction failed after {max_retries} attempts: {e}")

        if result is None and self._circuits["gemini"].is_open:
            raise RuntimeError(
                "Gemini API paused due to repeated failures (circuit breaker open). "
                "Try again in 60s or configure OpenRouter."
            )

        if result is None:
            raise RuntimeError("No API key configured — set OPENROUTER_API_KEY or enable billing on GEMINI_API_KEY")

        # --- Cache store (write-through) ---
        if self.cache:
            await self.cache.set(image_bytes, result.data)
            logger.info("CACHE MISS: stored extraction for sha256=%s", self.cache._make_key(image_bytes)[:12])

        return self._finalize(result.data, company_gstin)

    def _finalize(self, raw_data: dict, company_gstin: str) -> dict:
        """Normalize raw AI data to standard format and build output dict.

        If independent confidence is critically low (<0.40), the extraction
        cannot be trusted. We still return the data but mark it as needing
        manual review — the CA must verify every field.
        """
        # Determine provider/model from raw data or fall back to last known
        provider = raw_data.get("_provider") or self.last_provider or "cache"
        model = raw_data.get("_model") or self.last_model or "cached"
        # Run independent hallucination guard on raw AI data
        ind_conf, ind_scores, ind_issues = compute_independent_confidence(raw_data)
        raw_data["_independent_confidence"] = ind_conf
        raw_data["_independent_scores"] = ind_scores
        raw_data["_independent_issues"] = ind_issues

        # If confidence is critically low, add a clear warning
        if ind_conf < 0.40:
            raw_data["_extraction_warning"] = (
                f"AI extraction confidence is critically low ({ind_conf:.0%}). "
                f"The extracted data may contain significant errors. "
                f"Please review every field carefully or enter data manually."
            )
            raw_data["_needs_manual_review"] = True
        elif ind_conf < 0.70:
            raw_data["_extraction_warning"] = (
                f"AI extraction confidence is moderate ({ind_conf:.0%}). "
                f"Some fields may be incorrect — please verify before generating XML."
            )
            raw_data["_needs_review"] = True

        standard = _normalize_to_standard(raw_data, provider, model, company_gstin)
        return self._to_output(standard, raw_data)

    def _to_output(self, standard: StandardizedInvoice, raw: dict) -> dict:
        line_items_dicts = []
        for item in standard.line_items:
            line_items_dicts.append({
                "description": item.description,
                "quantity": item.quantity,
                "rate": item.rate,
                "taxable_value": item.taxable_value,
                "tax_rate": item.tax_rate,
                "hsn_sac": item.hsn_sac,
                "is_service": item.is_service,
                "discount": item.discount,
                "unit": item.unit,
            })
        result = {
            "invoice_number": standard.invoice_number,
            "date": standard.invoice_date,
            "vendor_name": standard.vendor_name,
            "gstin": standard.vendor_gstin,
            "vendor_gstin": standard.vendor_gstin,
            "vendor_address": standard.vendor_address,
            "buyer_name": standard.buyer_name,
            "buyer_gstin": standard.buyer_gstin or "",
            "buyer_address": standard.buyer_address,
            "total_taxable_value": standard.total_taxable_value,
            "total_tax": standard.total_tax,
            "total_amount": standard.total_amount,
            "line_items": line_items_dicts,
            "freight": standard.freight,
            "round_off": standard.round_off,
            "tds_amount": standard.tds_amount,
            "reverse_charge": standard.reverse_charge,
            "is_service": standard.is_service,
            "is_interstate": standard.is_interstate,
            "gst_type": standard.gst_type.value,
            "voucher_type": standard.voucher_type.value,
            "confidence": standard.confidence,
            "_provider": standard._provider,
            "_model": standard._model,
        }
        # Per-field confidence scoring
        base_conf = standard.confidence or 0.0
        field_conf = {}
        low_risk = ["vendor_name", "buyer_name", "total_amount", "total_taxable_value"]
        med_risk = ["invoice_number", "date", "vendor_address", "buyer_address"]
        high_risk = ["gstin", "vendor_gstin", "buyer_gstin"]
        for f in low_risk:
            field_conf[f] = round(min(base_conf + 0.05, 1.0), 2)
        for f in med_risk:
            field_conf[f] = round(min(base_conf + 0.02, 0.95), 2)
        for f in high_risk:
            field_conf[f] = round(max(base_conf - 0.15, 0.1), 2)
        result["_field_confidences"] = field_conf
        result["_independent_confidence"] = raw.get("_independent_confidence", standard.confidence)
        result["_independent_scores"] = raw.get("_independent_scores", {})
        result["_independent_issues"] = raw.get("_independent_issues", [])
        result["_usage"] = raw.get("_usage", {})
        # Copy independent scores to the standard model for downstream consumption
        standard.ind_confidence = raw.get("_independent_confidence", standard.confidence)
        standard.ind_scores = raw.get("_independent_scores", {})
        standard.ind_issues = raw.get("_independent_issues", [])

        math_issues = validate_invoice_math(result)
        if math_issues:
            result["_math_warnings"] = math_issues
        return result
