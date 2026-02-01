"""Keywords AI tracing setup for the shopping agent.

This module initializes the KeywordsAITelemetry instance and provides
the @workflow and @task decorators for instrumentation.
"""

from __future__ import annotations

import os
import logging
from pathlib import Path

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Load .env early so tracing can read API key.
env_path = Path(__file__).parent.parent / ".env"
if env_path.exists():
    load_dotenv(env_path)

# Initialize Keywords AI Telemetry
# The SDK reads KEYWORDSAI_API_KEY from environment automatically.
# If the app uses KEYWORDS_API_KEY, map it for tracing.
if not os.getenv("KEYWORDSAI_API_KEY"):
    api_key = os.getenv("KEYWORDS_API_KEY")
    if api_key:
        os.environ["KEYWORDSAI_API_KEY"] = api_key
try:
    from keywordsai_tracing.decorators import workflow, task
    from keywordsai_tracing.main import KeywordsAITelemetry

    # Initialize telemetry - reads KEYWORDSAI_API_KEY from env
    telemetry = KeywordsAITelemetry()
    TRACING_ENABLED = True
    logger.info("Keywords AI tracing enabled")

except ImportError:
    # Fallback if keywordsai-tracing is not installed
    logger.warning("keywordsai-tracing not installed, tracing disabled")
    TRACING_ENABLED = False
    telemetry = None

    # Create no-op decorators
    def workflow(name: str = "", **kwargs):
        """No-op workflow decorator when tracing is disabled."""
        def decorator(func):
            return func
        return decorator

    def task(name: str = "", **kwargs):
        """No-op task decorator when tracing is disabled."""
        def decorator(func):
            return func
        return decorator


__all__ = ["workflow", "task", "telemetry", "TRACING_ENABLED"]
