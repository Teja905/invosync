"""XML preflight validation endpoint."""

from fastapi import APIRouter, HTTPException, Depends

from api.deps import get_authenticated_user
from xml_preflight import validate_xml_preflight

router = APIRouter()


@router.post("/api/v3/xml/preflight")
async def preflight_xml(body: dict, current_user: dict = Depends(get_authenticated_user)):
    """Validate generated XML for common Tally import issues before export."""
    xml = body.get("xml", "")
    if not xml:
        raise HTTPException(status_code=422, detail="xml field is required")
    report = validate_xml_preflight(xml)
    return report
