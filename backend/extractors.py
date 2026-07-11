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
from schemas import StandardizedInvoice, VoucherType
from ocr_postproc import post_process_extracted, validate_invoice_math
from gst_engine import determine_gst_type

logger = get_logger(__name__)


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
  "invoice_date": "YYYY-MM-DD",
  "vendor_name": "vendor/supplier name",
  "vendor_gstin": "vendor GSTIN or empty string",
  "vendor_address": "vendor address or null",
  "buyer_name": "buyer name if visible",
  "buyer_gstin": "buyer GSTIN if visible",
  "buyer_address": "buyer address if visible",
  "total_taxable_value": number (total before tax),
  "total_tax": number (total GST amount),
  "total_amount": number (grand total including tax),
  "line_items": [
    {
      "description": "item description",
      "quantity": number,
      "rate": number,
      "taxable_value": number,
      "tax_rate": number (GST rate %),
      "hsn_sac": "HSN/SAC code if visible",
      "is_service": boolean (true if service item),
      "discount": number or 0
    }
  ],
  "freight": number or 0,
  "round_off": number or 0,
  "tds_amount": number or 0,
  "reverse_charge": boolean,
  "confidence": number between 0 and 1,
  "document_type": "tax_invoice" or "retail_bill" or "expense_receipt" or "proforma"
}
Return ONLY the JSON object."""


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
        return json.loads(m.group(1).strip())
    # Last resort: find first { and last }
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        return json.loads(text[start:end + 1])
    raise ValueError("Could not extract JSON from AI response")


class ExtractionResult:
    def __init__(self, data: dict, confidence: float, provider: str, model: str):
        self.data = data
        self.confidence = confidence
        self.provider = provider
        self.model = model


class OpenRouterExtractor:
    MODEL = os.getenv("OPENROUTER_MODEL", "google/gemini-2.0-flash-001")

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
                resp.raise_for_status()
                result = resp.json()
                text = result["choices"][0]["message"]["content"]
                data = _parse_response(text)
                conf = float(data.get("confidence") or 0.0)
                return ExtractionResult(data, conf, "openrouter", self.MODEL)
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
            return ExtractionResult(data, conf, "gemini", self.MODEL)
        except asyncio.TimeoutError:
            raise TimeoutError("Gemini timed out after 60s")
        except Exception as e:
            err_msg = str(e)
            if not err_msg or err_msg == "Internal Server Error":
                err_msg = f"{type(e).__name__}: {e}"
            raise RuntimeError(f"Gemini API error: {err_msg}")


def _normalize_to_standard(data: dict, provider: str, model: str, company_gstin: str = "") -> StandardizedInvoice:
    data = post_process_extracted(data)

    line_items = []
    for item in data.get("line_items", []):
        line_items.append({
            "description": item.get("description") or "",
            "quantity": float(item.get("quantity", 1) or 1),
            "rate": float(item.get("rate", 0) or 0),
            "taxable_value": float(item.get("taxable_value", 0) or 0),
            "tax_rate": float(item.get("tax_rate", 0) or 0),
            "hsn_sac": item.get("hsn_sac") or "",
            "is_service": bool(item.get("is_service", False)),
            "discount": float(item.get("discount", 0) or 0),
            "unit": item.get("unit") or "Nos",
        })

    company_state = os.getenv("COMPANY_STATE_CODE", "27")
    vendor_gstin = data.get("vendor_gstin") or data.get("gstin") or ""
    buyer_gstin = data.get("buyer_gstin") or ""
    gst_type, is_interstate = determine_gst_type(vendor_gstin, buyer_gstin, company_state)

    total_taxable = data.get("total_taxable_value", 0) or 0
    total_tax = data.get("total_tax", 0) or 0
    total_amount = data.get("total_amount", 0) or 0
    freight = float(data.get("freight", 0) or 0)
    round_off = float(data.get("round_off", 0) or 0)
    tds_amount = float(data.get("tds_amount", 0) or 0)

    doc_type = data.get("document_type", "")
    if not company_gstin:
        company_gstin = os.getenv("COMPANY_GSTIN", "")
    is_service = data.get("is_service", False) or any(
        item.get("is_service", False) for item in data.get("line_items", [])
    )

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
                doc_type, is_service, vendor_gstin, company_gstin, voucher_type.value)

    return StandardizedInvoice(
        invoice_number=data.get("invoice_number") or "",
        invoice_date=data.get("invoice_date") or data.get("date") or "",
        vendor_name=data.get("vendor_name") or "",
        vendor_gstin=vendor_gstin,
        vendor_address=data.get("vendor_address") or "",
        buyer_name=data.get("buyer_name") or "",
        buyer_gstin=buyer_gstin,
        buyer_address=data.get("buyer_address") or "",
        total_taxable_value=float(total_taxable),
        total_tax=float(total_tax),
        total_amount=float(total_amount),
        freight=freight,
        round_off=round_off,
        tds_amount=tds_amount,
        line_items=line_items,
        is_service=is_service,
        is_interstate=is_interstate,
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

    @property
    def is_open(self) -> bool:
        if self._open_until and time.monotonic() < self._open_until:
            return True
        if self._open_until:
            self._failures = 0
            self._open_until = 0.0
        return False


class ExtractionPipeline:
    def __init__(self):
        self.openrouter = OpenRouterExtractor()
        self.gemini = GeminiExtractor()
        self._circuits = {
            "openrouter": CircuitBreaker(),
            "gemini": CircuitBreaker(),
        }
        self.last_provider: str = ""
        self.last_model: str = ""

    @time_it
    async def extract(self, image_bytes: bytes, mime_type: str, company_gstin: str = "") -> dict:
        image_bytes, mime_type = normalize_image(image_bytes, mime_type)

        result = None
        if not self._circuits["openrouter"].is_open:
            try:
                result = await self.openrouter.extract(image_bytes, mime_type)
                if result:
                    self._circuits["openrouter"].record_success()
                    self.last_provider = result.provider
                    self.last_model = result.model
                    logger.info("Extracted via OpenRouter (%s)", result.model)
            except Exception as e:
                self._circuits["openrouter"].record_failure()
                logger.warning("OpenRouter failed (%d): %s",
                               self._circuits["openrouter"]._failures, e)

        if result is None and not self._circuits["gemini"].is_open:
            try:
                result = await self.gemini.extract(image_bytes, mime_type)
                if result:
                    self._circuits["gemini"].record_success()
                    self.last_provider = result.provider
                    self.last_model = result.model
                    logger.info("Extracted via Gemini (%s)", result.model)
            except Exception as e:
                self._circuits["gemini"].record_failure()
                raise RuntimeError(f"Extraction failed: {e}")
        elif result is None and self._circuits["gemini"].is_open:
            raise RuntimeError(
                "Gemini API paused due to repeated failures (circuit breaker open). "
                "Try again in 60s or configure OpenRouter."
            )

        if result is None:
            raise RuntimeError("No API key configured — set OPENROUTER_API_KEY or enable billing on GEMINI_API_KEY")

        standard = _normalize_to_standard(result.data, result.provider, result.model, company_gstin)
        return self._to_output(standard, result.data)

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
        math_issues = validate_invoice_math(result)
        if math_issues:
            result["_math_warnings"] = math_issues
        return result
