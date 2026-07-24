"""Extraction routes: upload, queue, status, batch."""

import hashlib
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from bson.objectid import ObjectId
from fastapi import APIRouter, UploadFile, File, HTTPException, Query, Depends, Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.util import get_remote_address

try:
    from PIL import Image  # noqa: F401
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

import database as db
from api.app_state import extraction_pipeline, queue_manager
from api.deps import get_authenticated_user
from background.models import ExtractionJob
from config.settings import user_config_from_current
from core.debug import time_it
from core.logging import get_logger
from ocr_postproc import clean_extracted_invoice_payload

router = APIRouter()
logger = get_logger(__name__)

limiter = Limiter(key_func=get_remote_address)


def _is_valid_image(data: bytes) -> bool:
    if data[:4] == b"%PDF":
        return True
    return any([
        data[:2] == b"\xff\xd8",
        data[:4] == b"\x89PNG",
        data[:4] in (b"GIF8",),
        data[:4] == b"RIFF",
        data[:2] == b"\x42\x4d",
        data[:4] == b"\x00\x00\x00\x0c",
        data[:4] == b"\xff\x4f\xff\x51",
    ])


@router.post("/extract")
@time_it
@limiter.limit("15/minute")
async def extract(
    request: Request,
    file: UploadFile = File(...),
    client_id: int = Query(..., description="Client ID the invoice belongs to"),
    current_user: dict = Depends(get_authenticated_user),
):
    """Upload an invoice image or PDF and queue it for AI extraction."""
    if db.clients is not None:
        client = await db.get_client(client_id)
        if not client:
            raise HTTPException(404, "Client not found")
        user_id = current_user.get("user_id", current_user.get("email", ""))
        if client.get("user_id") != user_id:
            raise HTTPException(403, "Access denied")

    _ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp", "application/pdf"}
    if not file.content_type or file.content_type not in _ALLOWED_TYPES:
        raise HTTPException(400, "Only JPG, PNG, WebP, and PDF files are supported")

    user_config = user_config_from_current(current_user)
    company_gstin = user_config.get("company_gstin") or os.getenv("COMPANY_GSTIN", "")
    if not company_gstin:
        return JSONResponse(
            status_code=400,
            content={
                "error": "company_profile_required",
                "message": "Set up your company profile first (Company Name, GSTIN, State) in Settings before processing invoices.",
            },
        )

    MAX_FILE_SIZE = 15 * 1024 * 1024
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=Path(file.filename or "upload").suffix) as tmp:
            tmp_path = Path(tmp.name)
            bytes_written = 0
            magic_checked = False
            while chunk := await file.read(64 * 1024):
                bytes_written += len(chunk)
                if bytes_written > MAX_FILE_SIZE:
                    return JSONResponse(
                        status_code=413,
                        content={"error": "PAYLOAD_TOO_LARGE", "message": "Invoice file must be under 15MB."},
                    )
                if not magic_checked:
                    if not _is_valid_image(chunk[:16]):
                        raise HTTPException(400, "File content is not a valid image or PDF (magic bytes mismatch)")
                    magic_checked = True
                tmp.write(chunk)
            tmp.flush()

        image_bytes = tmp_path.read_bytes()
        file_hash = hashlib.sha256(image_bytes).hexdigest()
        user_id = current_user.get("user_id", current_user.get("email", ""))

        if db.invoices is not None:
            existing_hash = await db.find_by_file_hash(file_hash, user_id)
            if existing_hash:
                if tmp_path.exists():
                    tmp_path.unlink()
                return JSONResponse(
                    status_code=409,
                    content={
                        "duplicate": True,
                        "existing_id": existing_hash.get("display_id"),
                        "message": "This exact file has already been processed.",
                    },
                )

        if db.invoices is None:
            data = await extraction_pipeline.extract(image_bytes, file.content_type, company_gstin=company_gstin)
            data = clean_extracted_invoice_payload(data)
            usage = data.get("_usage", {})
            if usage:
                from core.metrics import metrics as _metrics
                _metrics.record_ai_usage(data.get("_provider", "unknown"), usage)
            return {**data, "client_id": client_id, "_fallback": True}

        now_utc = datetime.now(timezone.utc).isoformat()
        placeholder = {
            "user_id": user_id,
            "client_id": client_id,
            "file_hash": file_hash,
            "filename": file.filename or "upload",
            "status": "processing_queued",
            "created_at": now_utc,
        }
        insert_result = await db.invoices.insert_one(placeholder)
        invoice_obj_id = str(insert_result.inserted_id)

        job = ExtractionJob(
            invoice_id=ObjectId(invoice_obj_id),
            tmp_path=tmp_path,
            file_content_type=file.content_type,
            user_id=user_id,
            client_id=client_id,
            company_gstin=company_gstin,
            user_config=user_config,
        )
        await queue_manager.submit(job)

        return JSONResponse(
            status_code=202,
            content={
                "status": "queued",
                "invoice_id": invoice_obj_id,
                "message": "File received. Extraction is processing in the background.",
                "client_id": client_id,
            },
        )
    except HTTPException:
        if tmp_path and tmp_path.exists():
            try:
                tmp_path.unlink()
            except Exception:
                pass
        raise
    except Exception as e:
        logger.error("EXTRACT QUEUE ERROR: %s", e)
        if tmp_path and tmp_path.exists():
            try:
                tmp_path.unlink()
            except Exception:
                pass
        raise HTTPException(502, f"Extraction failed: {str(e)}")


@router.get("/extract/status/{invoice_id}")
async def extract_status(invoice_id: str, current_user: dict = Depends(get_authenticated_user)):
    """Polling endpoint for frontend to check extraction progress."""
    try:
        obj_id = ObjectId(invoice_id)
    except Exception:
        raise HTTPException(400, "Invalid invoice ID format")

    user_id = current_user.get("user_id", current_user.get("email", ""))

    if db.invoices is not None:
        doc = await db.invoices.find_one({"_id": obj_id, "user_id": user_id})
        if not doc:
            raise HTTPException(404, "Invoice not found")

        state = queue_manager.get_status(invoice_id) or "queued"
        return {
            "invoice_id": invoice_id,
            "processing_state": state,
            "status": doc.get("status", "processing_queued"),
            "display_id": doc.get("display_id"),
        }

    return {"invoice_id": invoice_id, "processing_state": "unknown", "status": "unknown"}


@router.post("/api/v3/extraction/batch-status")
async def batch_extraction_status(
    request: Request,
    current_user: dict = Depends(get_authenticated_user),
):
    """Get extraction status for multiple invoices at once."""
    body = await request.json()
    invoice_ids = body.get("invoice_ids", [])
    if not invoice_ids or not isinstance(invoice_ids, list):
        raise HTTPException(400, "invoice_ids list is required")
    if len(invoice_ids) > 500:
        raise HTTPException(400, "Maximum 500 invoice IDs per request")

    user_id = current_user.get("user_id", current_user.get("email", ""))
    results = {}

    if db.invoices is not None:
        from bson.objectid import ObjectId as _OID
        valid_ids = []
        oid_map = {}
        for raw_id in invoice_ids:
            try:
                oid = _OID(raw_id)
                valid_ids.append(oid)
                oid_map[str(oid)] = raw_id
            except Exception:
                results[raw_id] = {"status": "invalid_id", "processing_state": "unknown"}

        if valid_ids:
            cursor = db.invoices.find(
                {"_id": {"$in": valid_ids}, "user_id": user_id},
                {"status": 1, "processing_state": 1, "display_id": 1},
            )
            async for doc in cursor:
                sid = str(doc["_id"])
                raw = oid_map.get(sid, sid)
                q_state = queue_manager.get_status(sid) or doc.get("processing_state", "unknown")
                results[raw] = {
                    "status": doc.get("status", "unknown"),
                    "processing_state": q_state,
                    "display_id": doc.get("display_id"),
                }

    for raw_id in invoice_ids:
        if raw_id not in results:
            results[raw_id] = {"status": "not_found", "processing_state": "unknown"}

    return {"results": results}


@router.post("/api/v3/batch/extract")
async def batch_extract(
    request: Request,
    files: list[UploadFile] = File(...),
    client_id: int = Query(..., description="Client ID"),
    current_user: dict = Depends(get_authenticated_user),
):
    """Upload and extract multiple invoice files in a single request."""
    if len(files) > 50:
        raise HTTPException(400, "Maximum 50 files per batch")

    if db.clients is not None:
        client = await db.get_client(client_id)
        if not client:
            raise HTTPException(404, "Client not found")
        user_id = current_user.get("user_id", current_user.get("email", ""))
        if client.get("user_id") != user_id:
            raise HTTPException(403, "Access denied")

    user_config = user_config_from_current(current_user)
    company_gstin = user_config.get("company_gstin") or os.getenv("COMPANY_GSTIN", "")
    if not company_gstin:
        return JSONResponse(
            status_code=400,
            content={
                "error": "company_profile_required",
                "message": "Set up your company profile first.",
            },
        )

    results = []
    errors = []

    for file in files:
        try:
            if not file.filename:
                errors.append({"file": "unknown", "error": "No filename"})
                continue
            file_bytes = await file.read()
            file.file.seek(0)
            if len(file_bytes) > 15 * 1024 * 1024:
                errors.append({"file": file.filename, "error": "File exceeds 15MB"})
                continue
            first_bytes = file_bytes[:16]
            if not _is_valid_image(first_bytes):
                errors.append({"file": file.filename, "error": "Not a valid image or PDF"})
                continue

            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=Path(file.filename).suffix)
            tmp_path = Path(tmp.name)
            tmp.write(file_bytes)
            tmp.close()

            image_bytes = tmp_path.read_bytes()
            try:
                data = await extraction_pipeline.extract(image_bytes, file.content_type or "image/jpeg", company_gstin=company_gstin)
                data = clean_extracted_invoice_payload(data)
                data.pop("_raw_response", None)
                data["filename"] = file.filename
                data["_provider"] = extraction_pipeline.last_provider
                data["_model"] = extraction_pipeline.last_model
                results.append(data)
            finally:
                os.unlink(tmp_path)
        except Exception as e:
            errors.append({"file": file.filename or "unknown", "error": str(e)})

    return {
        "total": len(files),
        "processed": len(results),
        "errors": len(errors),
        "results": results,
        "error_details": errors,
    }
