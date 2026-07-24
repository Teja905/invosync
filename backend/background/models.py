"""Typed data models for extraction queue jobs and task status."""

from dataclasses import dataclass
from pathlib import Path

from bson.objectid import ObjectId


@dataclass
class ExtractionJob:
    """A single extraction job submitted by a route handler."""

    invoice_id: ObjectId
    tmp_path: Path
    file_content_type: str
    user_id: str
    client_id: int
    company_gstin: str
    user_config: dict


@dataclass
class TaskStatus:
    """Current processing state and timestamp for a job."""

    state: str
    timestamp: float
