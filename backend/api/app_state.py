"""Shared application state — global instances used across routers."""

from slowapi import Limiter
from slowapi.util import get_remote_address
from extractors import ExtractionPipeline
from company_config import CompanyConfig
from xml_generator import TallyXmlGenerator
from ledger_mapping import LedgerMappingEngine
from rules_engine import RulesEngine
from context_classifier import ContextClassifier
from ledger_learner import LedgerLearner
from validators.pipeline import ValidationPipeline
from background import ExtractionQueueManager, TallySyncManager
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

# Extraction queue manager — routers submit jobs here
queue_manager = ExtractionQueueManager()
MAX_CONCURRENT_EXTRACTIONS = queue_manager.max_concurrent
TASK_TTL_SECONDS = queue_manager.task_ttl

# Tally sync manager — tracks sync jobs handed off to the C# connector
tally_sync_manager = TallySyncManager()

# Global default: 120 req/min per IP. Individual routes may tighten this
# (e.g. extraction is 15/min). Protects the service from a single client
# overwhelming it at 1000+ users.
limiter = Limiter(key_func=get_remote_address, default_limits=["120/minute"])
