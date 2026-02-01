"""Keywords AI tracing setup for the shopping agent.

This module initializes the KeywordsAITelemetry instance and provides
the @workflow and @task decorators for instrumentation.
"""

from __future__ import annotations

import os
import logging

logger = logging.getLogger(__name__)

# Initialize Keywords AI Telemetry
# The SDK reads KEYWORDSAI_API_KEY from environment automatically
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
