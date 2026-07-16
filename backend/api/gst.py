"""GST-related endpoints: state codes, GSTIN validation."""

from fastapi import APIRouter

from gst_engine import validate_gstin
from schemas import GST_STATE_CODES

router = APIRouter()


@router.get("/api/v3/gst/state-codes")
async def get_state_codes():
    """Return the mapping of GST state codes to state names."""
    return GST_STATE_CODES


@router.post("/api/v3/gst/validate")
async def gst_validate(gstin: str):
    """Validate a GSTIN number and return its checksum and state details."""
    return validate_gstin(gstin)
