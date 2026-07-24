"""Background extraction worker — dequeues jobs, runs AI extraction, persists results.

Imports global singletons directly so the worker loop stays self-contained.
"""

import asyncio

import database as db
import validation as val
from audit_log import audit as audit_logger
from core.logging import get_logger
from ocr_postproc import clean_extracted_invoice_payload
from storage import store as storage_store
from core.metrics import metrics
from .queue_manager import ExtractionQueueManager
from .models import ExtractionJob


def _get_extraction_pipeline():
    """Lazy import to avoid circular dependency."""
    from api.app_state import extraction_pipeline
    return extraction_pipeline


logger = get_logger(__name__)


async def _process_job(job: ExtractionJob, manager: ExtractionQueueManager):
    """Run the full extraction pipeline for a single job and persist the result.

    Fully isolated: exceptions are caught so a single bad job can never crash the
    worker task or the parent loop. Per-job timeout prevents stuck extraction from
    blocking the queue.
    """
    inv_key = str(job.invoice_id)
    JOB_TIMEOUT = 180  # 3 minutes max per invoice
    try:
        manager.set_status(inv_key, "processing")
        image_bytes = job.tmp_path.read_bytes()
        file_hash = db.calculate_file_hash(image_bytes)

        data = await asyncio.wait_for(
            _get_extraction_pipeline().extract(
                image_bytes, job.file_content_type, company_gstin=job.company_gstin
            ),
            timeout=JOB_TIMEOUT,
        )
        data = clean_extracted_invoice_payload(data)

        usage = data.get("_usage", {})
        if usage:
            metrics.record_ai_usage(data.get("_provider", "unknown"), usage)

        # Log low-confidence extractions for CA review
        ind_conf = data.get("_independent_confidence", 1.0)
        if ind_conf < 0.40:
            logger.warning("LOW CONFIDENCE extraction for invoice %s: %.0f%% — needs manual review",
                          job.invoice_id, ind_conf * 100)
        elif ind_conf < 0.70:
            logger.info("MODERATE CONFIDENCE extraction for invoice %s: %.0f%% — verify fields",
                       job.invoice_id, ind_conf * 100)

        metrics.record_invoice_processed()

        existing_list = []
        if db.invoices is not None:
            try:
                existing_list = await db.list_invoices(
                    user_id=job.user_id, client_id=job.client_id
                )
            except Exception:
                pass

        validation = val.run_full_validation(data, existing_list)
        inv_display_id = await db.next_id("invoice_id")
        storage_key = await storage_store(job.user_id, inv_display_id, image_bytes)
        active_company_id = (
            (job.user_config or {}).get("active_company_id")
            if isinstance(job.user_config, dict)
            else None
        )
        inv_display_id, _ = await db.insert_invoice(
            user_id=job.user_id,
            client_id=job.client_id,
            extracted=data,
            validation=validation,
            file_hash=file_hash,
            storage_key=storage_key,
            display_id=inv_display_id,
            company_id=active_company_id,
        )
        if validation.get("decision") == "high" and db.invoices is not None:
            await db.update_invoice_status(inv_display_id, "validated")

        await db.invoices.update_one(
            {"_id": job.invoice_id},
            {
                "$set": {
                    "status": "draft",
                    "display_id": inv_display_id,
                    "extracted": data,
                    "validation": validation,
                    "storage_key": storage_key,
                    "image_data": None,
                }
            },
        )
        manager.set_status(inv_key, "completed")
        metrics.record_invoice_processed()
        user_id_for_audit = job.user_id or "unknown"
        await audit_logger.log_invoice_action(
            "extract",
            inv_display_id,
            user_id_for_audit,
            f"status={validation.get('decision', 'unknown')}",
        )
    except asyncio.TimeoutError:
        msg = f"Extraction timed out after {JOB_TIMEOUT}s — invoice may be too large or AI provider is slow"
        logger.error("QUEUE WORKER: invoice %s: %s", job.invoice_id, msg)
        manager.set_status(inv_key, f"failed: {msg}")
        if db.invoices is not None:
            await db.invoices.update_one(
                {"_id": job.invoice_id},
                {"$set": {"status": "extraction_failed", "sync_error": msg}},
            )
    except Exception as e:
        logger.error("QUEUE WORKER: invoice %s failed: %s", job.invoice_id, e)
        manager.set_status(inv_key, f"failed: {e}")
        if db.invoices is not None:
            await db.invoices.update_one(
                {"_id": job.invoice_id},
                {"$set": {"status": "extraction_failed", "sync_error": str(e)}},
            )
    finally:
        if job.tmp_path and job.tmp_path.exists():
            try:
                job.tmp_path.unlink()
            except Exception:
                pass
        manager.task_done()


async def run_extraction_worker(manager: ExtractionQueueManager):
    """Background loop: pull jobs from *manager* and dispatch with concurrency throttle.

    Crash-proof: any exception that escapes the loop is caught, logged, and the
    loop restarts after a short backoff so extraction never silently dies.
    """
    while True:
        try:
            metrics.set_worker_heartbeat()
            metrics.set_queue_depth(manager.pending_count())
            job = await manager.get()
            asyncio.create_task(_process_job(job, manager))
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("EXTRACTION WORKER loop error, restarting in 5s: %s", e)
            await asyncio.sleep(5)
