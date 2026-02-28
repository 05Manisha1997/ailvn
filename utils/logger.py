"""
utils/logger.py
Structured logging with call_id context binding.
"""
import structlog
import logging
import sys
from config.settings import get_settings

settings = get_settings()


def configure_logging():
    log_level = getattr(logging, settings.log_level.upper(), logging.INFO)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer() if settings.app_env == "production"
            else structlog.dev.ConsoleRenderer(colors=True),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(sys.stdout),
    )


configure_logging()

logger = structlog.get_logger()


def get_call_logger(call_id: str, **extra):
    """Returns a logger pre-bound with call_id for scoped logging."""
    return logger.bind(call_id=call_id, **extra)
