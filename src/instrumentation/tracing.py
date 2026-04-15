"""Sentry-based tracing and instrumentation for dispute processing agents.

Provides decorators and utilities for:
- Initializing Sentry with FastAPI integration
- Tracing agent process() and validate() calls as Sentry spans
- Recording LLM call metrics (token usage, latency)
- Capturing agent decisions with structured context
"""

import functools
import logging
import os
import time
from collections.abc import Callable
from typing import Any, ParamSpec, TypeVar

import sentry_sdk
from sentry_sdk import set_context, set_tag

logger = logging.getLogger(__name__)

P = ParamSpec("P")
T = TypeVar("T")

# ---------------------------------------------------------------------------
# Sentry initialization
# ---------------------------------------------------------------------------

def init_sentry(
    dsn: str | None = None,
    environment: str = "development",
    traces_sample_rate: float = 1.0,
    profiles_sample_rate: float = 0.1,
) -> None:
    """Initialize Sentry SDK with FastAPI and logging integrations.

    Args:
        dsn: Sentry DSN. Falls back to SENTRY_DSN env var.
        environment: Deployment environment name.
        traces_sample_rate: Fraction of transactions to trace (0.0-1.0).
        profiles_sample_rate: Fraction of traced transactions to profile.
    """
    resolved_dsn = dsn or os.environ.get("SENTRY_DSN")
    if not resolved_dsn:
        logger.info("SENTRY_DSN not configured — instrumentation disabled")
        return

    sentry_sdk.init(
        dsn=resolved_dsn,
        environment=environment,
        traces_sample_rate=traces_sample_rate,
        profiles_sample_rate=profiles_sample_rate,
        send_default_pii=False,
        enable_tracing=True,
    )
    logger.info("Sentry initialized (env=%s, traces=%.0f%%)", environment, traces_sample_rate * 100)


# ---------------------------------------------------------------------------
# Span helpers
# ---------------------------------------------------------------------------

def trace_agent_process(agent_name: str) -> Callable[..., Any]:
    """Decorator that wraps an agent's ``process()`` in a Sentry span.

    Records:
    - agent.name, case_id, category, condition as span tags
    - Elapsed wall-clock time
    - Decision resolution and confidence on completion
    """

    def decorator(fn: Callable[P, T]) -> Callable[P, T]:
        @functools.wraps(fn)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            # args[0] is self, args[1] is case
            case = args[1] if len(args) > 1 else kwargs.get("case")
            case_id = getattr(case, "case_id", "unknown") if case else "unknown"

            with sentry_sdk.start_span(
                op="agent.process",
                name=f"{agent_name}.process",
            ) as span:
                span.set_data("agent.name", agent_name)
                span.set_data("case.id", case_id)
                if case:
                    _set_case_span_data(span, case)

                start = time.monotonic()
                try:
                    result = await fn(*args, **kwargs)
                except Exception as exc:
                    span.set_status("internal_error")
                    span.set_data("error", str(exc))
                    sentry_sdk.capture_exception(exc)
                    raise
                else:
                    elapsed = time.monotonic() - start
                    span.set_data("duration_ms", round(elapsed * 1000, 2))
                    span.set_status("ok")
                    if hasattr(result, "decision") and result.decision:
                        span.set_data("decision.resolution", result.decision.resolution.value)
                        span.set_data("decision.confidence", result.decision.confidence_score)
                        span.set_data("decision.requires_human_review", result.decision.requires_human_review)
                    if hasattr(result, "stage"):
                        span.set_data("case.final_stage", result.stage.value)
                    return result

        return wrapper  # type: ignore[return-value]

    return decorator


def record_agent_validation(agent_name: str) -> Callable[..., Any]:
    """Decorator that wraps an agent's ``validate()`` in a Sentry span."""

    def decorator(fn: Callable[P, T]) -> Callable[P, T]:
        @functools.wraps(fn)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            case = args[1] if len(args) > 1 else kwargs.get("case")
            case_id = getattr(case, "case_id", "unknown") if case else "unknown"

            with sentry_sdk.start_span(
                op="agent.validate",
                name=f"{agent_name}.validate",
            ) as span:
                span.set_data("agent.name", agent_name)
                span.set_data("case.id", case_id)
                result = await fn(*args, **kwargs)
                span.set_data("validation.result", result)
                return result

        return wrapper  # type: ignore[return-value]

    return decorator


def trace_llm_call(agent_name: str) -> Callable[..., Any]:
    """Decorator that wraps an LLM evaluation call in a Sentry span.

    Records prompt lengths, response time, and model metadata.
    """

    def decorator(fn: Callable[P, T]) -> Callable[P, T]:
        @functools.wraps(fn)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            with sentry_sdk.start_span(
                op="ai.chat_completion",
                name=f"{agent_name}.llm_call",
            ) as span:
                span.set_data("agent.name", agent_name)
                # Try to capture prompt lengths from positional args
                # base_agent._evaluate_dispute_with_llm(self, case, rules_context, system_prompt)
                if len(args) >= 4:
                    span.set_data("prompt.rules_context_len", len(str(args[2])))
                    span.set_data("prompt.system_prompt_len", len(str(args[3])))

                start = time.monotonic()
                try:
                    result = fn(*args, **kwargs)
                except Exception as exc:
                    span.set_status("internal_error")
                    span.set_data("error", str(exc))
                    sentry_sdk.capture_exception(exc)
                    raise
                else:
                    elapsed = time.monotonic() - start
                    span.set_data("duration_ms", round(elapsed * 1000, 2))
                    span.set_status("ok")
                    if isinstance(result, dict):
                        span.set_data("response.confidence", result.get("confidence"))
                        span.set_data("response.is_valid", result.get("is_valid"))
                        span.set_data("response.resolution", result.get("resolution"))
                    return result

        return wrapper  # type: ignore[return-value]

    return decorator


# ---------------------------------------------------------------------------
# Context helpers
# ---------------------------------------------------------------------------

def record_agent_decision(
    agent_name: str,
    case_id: str,
    resolution: str,
    confidence: float,
    requires_human_review: bool,
    rule_count: int,
) -> None:
    """Record a structured agent decision as Sentry breadcrumb + context."""
    set_tag("agent.name", agent_name)
    set_tag("case.resolution", resolution)

    sentry_sdk.add_breadcrumb(
        category="agent.decision",
        message=f"{agent_name} decided {resolution} (confidence={confidence:.2f})",
        level="info",
        data={
            "case_id": case_id,
            "resolution": resolution,
            "confidence": confidence,
            "requires_human_review": requires_human_review,
            "rule_evaluations_count": rule_count,
        },
    )

    set_context("agent_decision", {
        "agent_name": agent_name,
        "case_id": case_id,
        "resolution": resolution,
        "confidence": confidence,
        "requires_human_review": requires_human_review,
        "rule_evaluations_count": rule_count,
    })


def instrument_agent(agent_name: str) -> dict[str, Callable[..., Any]]:
    """Return a dict of decorators pre-configured for a specific agent.

    Usage::

        _inst = instrument_agent("fraud_agent")
        # then apply _inst["process"], _inst["validate"], _inst["llm_call"]
    """
    return {
        "process": trace_agent_process(agent_name),
        "validate": record_agent_validation(agent_name),
        "llm_call": trace_llm_call(agent_name),
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _set_case_span_data(span: Any, case: Any) -> None:
    """Attach dispute case metadata to a Sentry span."""
    if hasattr(case, "category") and case.category:
        span.set_data("case.category", case.category.value)
    if hasattr(case, "condition") and case.condition:
        span.set_data("case.condition", case.condition.value)
    if hasattr(case, "dispute_amount") and case.dispute_amount is not None:
        span.set_data("case.dispute_amount", case.dispute_amount)
    if hasattr(case, "stage"):
        span.set_data("case.stage", case.stage.value)
