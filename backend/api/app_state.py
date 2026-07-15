"""Shared application state — global instances used across routers."""

import asyncio

from extractors import ExtractionPipeline
from company_config import CompanyConfig
from xml_generator import TallyXmlGenerator
from ledger_mapping import LedgerMappingEngine
from rules_engine import RulesEngine
from context_classifier import ContextClassifier
from ledger_learner import LedgerLearner
from validators.pipeline import ValidationPipeline
from core.logging import get_logger

import database as db

logger = get_logger(__name__)

# Core engine instances
extraction_pipeline = ExtractionPipeline()
company_config = CompanyConfig()
xml_generator = TallyXmlGenerator(company_config)
ledger_engine = LedgerMappingEngine(company_config)

# Ledger learner — self-improving, user-scoped correction engine
learner = LedgerLearner(db=db)

# Validation pipeline — runs all validators on every generation
validation_pipeline = ValidationPipeline()

# Rules engine + context classifier
_api_rules_engine = RulesEngine()
api_rules_engine = _api_rules_engine
api_context_classifier = ContextClassifier(rules_engine=_api_rules_engine)

# Async extraction queue
MAX_CONCURRENT_EXTRACTIONS = 3
extraction_queue = asyncio.Queue()
processing_tasks: dict[str, tuple[str, float]] = {}
TASK_TTL_SECONDS = 3600
