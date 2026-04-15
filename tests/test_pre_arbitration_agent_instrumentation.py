"""Tests for Sentry instrumentation on the PreArbitrationAgent.

Verifies that spans, breadcrumbs, and exception capturing are wired
correctly via the shared decorators in src.instrumentation.tracing.
"""

import asyncio
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from src.agents.pre_arbitration_agent import PreArbitrationAgent
from src.models.dispute import (
    CardholderInfo,
    DisputeCase,
    TransactionDetails,
)
from src.models.enums import (
    DisputeCategory,
    DisputeCondition,
    DisputeLifecycleStage,
    TransactionEnvironment,
)


def _make_case(stage: DisputeLifecycleStage) -> DisputeCase:
    """Build a minimal DisputeCase at the given lifecycle stage."""
    case = DisputeCase(
        transaction=TransactionDetails(
            transaction_id="TXN-INST-001",
            transaction_date=date(2025, 1, 15),
            processing_date=date(2025, 1, 16),
            amount=500.00,
            currency="USD",
            merchant_name="Test Merchant",
            merchant_category_code="5411",
            merchant_country="US",
            acquirer_bin="400000",
            issuer_bin="400001",
            environment=TransactionEnvironment.ECOMMERCE,
        ),
        cardholder=CardholderInfo(
            cardholder_name="Test User",
            partial_payment_credential="4111XXXX1111",
            cardholder_statement="Dispute for testing",
        ),
        stage=stage,
        category=DisputeCategory.FRAUD,
        condition=DisputeCondition.OTHER_FRAUD_CARD_ABSENT,
    )
    return case


# ------------------------------------------------------------------
# 1. test_process_creates_sentry_span
# ------------------------------------------------------------------


@patch("sentry_sdk.start_span")
def test_process_creates_sentry_span(mock_start_span: MagicMock) -> None:
    """Processing a pre-arb case should open an agent.process span."""
    span_ctx = MagicMock()
    mock_start_span.return_value.__enter__ = MagicMock(return_value=span_ctx)
    mock_start_span.return_value.__exit__ = MagicMock(return_value=False)

    agent = PreArbitrationAgent()
    case = _make_case(DisputeLifecycleStage.PRE_ARBITRATION)
    asyncio.get_event_loop().run_until_complete(agent.process(case))

    mock_start_span.assert_any_call(
        op="agent.process",
        name="pre_arbitration_agent.process",
    )


# ------------------------------------------------------------------
# 2. test_validate_creates_sentry_span
# ------------------------------------------------------------------


@patch("sentry_sdk.start_span")
def test_validate_creates_sentry_span(mock_start_span: MagicMock) -> None:
    """Validation should open an agent.validate span."""
    span_ctx = MagicMock()
    mock_start_span.return_value.__enter__ = MagicMock(return_value=span_ctx)
    mock_start_span.return_value.__exit__ = MagicMock(return_value=False)

    agent = PreArbitrationAgent()
    case = _make_case(DisputeLifecycleStage.PRE_ARBITRATION)
    result = asyncio.get_event_loop().run_until_complete(agent.validate(case))

    assert result is True
    mock_start_span.assert_any_call(
        op="agent.validate",
        name="pre_arbitration_agent.validate",
    )


# ------------------------------------------------------------------
# 3. test_llm_call_creates_sentry_span
# ------------------------------------------------------------------


@patch("sentry_sdk.start_span")
def test_llm_call_creates_sentry_span(mock_start_span: MagicMock) -> None:
    """LLM evaluation should open an ai.chat_completion span."""
    span_ctx = MagicMock()
    mock_start_span.return_value.__enter__ = MagicMock(return_value=span_ctx)
    mock_start_span.return_value.__exit__ = MagicMock(return_value=False)

    agent = PreArbitrationAgent()
    case = _make_case(DisputeLifecycleStage.PRE_ARBITRATION)
    # process() internally calls _evaluate_pre_arb_with_llm
    asyncio.get_event_loop().run_until_complete(agent.process(case))

    mock_start_span.assert_any_call(
        op="ai.chat_completion",
        name="pre_arbitration_agent.llm_call",
    )


# ------------------------------------------------------------------
# 4. test_decision_recorded_as_breadcrumb
# ------------------------------------------------------------------


@patch("sentry_sdk.add_breadcrumb")
@patch("sentry_sdk.start_span")
def test_decision_recorded_as_breadcrumb(
    mock_start_span: MagicMock,
    mock_add_breadcrumb: MagicMock,
) -> None:
    """After a decision, sentry_sdk.add_breadcrumb should be called with category='agent.decision'."""
    span_ctx = MagicMock()
    mock_start_span.return_value.__enter__ = MagicMock(return_value=span_ctx)
    mock_start_span.return_value.__exit__ = MagicMock(return_value=False)

    agent = PreArbitrationAgent()
    case = _make_case(DisputeLifecycleStage.PRE_ARBITRATION)
    asyncio.get_event_loop().run_until_complete(agent.process(case))

    # record_agent_decision calls sentry_sdk.add_breadcrumb
    mock_add_breadcrumb.assert_called()
    breadcrumb_call = mock_add_breadcrumb.call_args
    assert breadcrumb_call.kwargs.get("category") == "agent.decision" or (
        breadcrumb_call.args and breadcrumb_call.kwargs.get("category") == "agent.decision"
    )


# ------------------------------------------------------------------
# 5. test_process_captures_exception_on_error
# ------------------------------------------------------------------


@patch("sentry_sdk.capture_exception")
@patch("sentry_sdk.start_span")
def test_process_captures_exception_on_error(
    mock_start_span: MagicMock,
    mock_capture_exception: MagicMock,
) -> None:
    """When process() raises, sentry_sdk.capture_exception should be called."""
    span_ctx = MagicMock()
    mock_start_span.return_value.__enter__ = MagicMock(return_value=span_ctx)
    mock_start_span.return_value.__exit__ = MagicMock(return_value=False)

    agent = PreArbitrationAgent()
    case = _make_case(DisputeLifecycleStage.PRE_ARBITRATION)

    with (
        patch.object(agent, "_process_pre_arbitration", side_effect=RuntimeError("boom")),
        pytest.raises(RuntimeError, match="boom"),
    ):
        asyncio.get_event_loop().run_until_complete(agent.process(case))

    mock_capture_exception.assert_called_once()
    exc_arg = mock_capture_exception.call_args[0][0]
    assert isinstance(exc_arg, RuntimeError)


# ------------------------------------------------------------------
# 6. test_arbitration_creates_span
# ------------------------------------------------------------------


@patch("sentry_sdk.add_breadcrumb")
@patch("sentry_sdk.start_span")
def test_arbitration_creates_span(
    mock_start_span: MagicMock,
    mock_add_breadcrumb: MagicMock,
) -> None:
    """Arbitration processing should create agent.process and ai.chat_completion spans."""
    span_ctx = MagicMock()
    mock_start_span.return_value.__enter__ = MagicMock(return_value=span_ctx)
    mock_start_span.return_value.__exit__ = MagicMock(return_value=False)

    agent = PreArbitrationAgent()
    case = _make_case(DisputeLifecycleStage.ARBITRATION)
    result = asyncio.get_event_loop().run_until_complete(agent.process(case))

    assert result.arbitration_filed is True

    # Should have both process and LLM spans
    span_calls = [call.kwargs for call in mock_start_span.call_args_list]
    ops = [c.get("op") for c in span_calls]
    assert "agent.process" in ops
    assert "ai.chat_completion" in ops

    # Decision breadcrumb should be recorded
    mock_add_breadcrumb.assert_called()


# ------------------------------------------------------------------
# 7. test_pre_arb_response_creates_span
# ------------------------------------------------------------------


@patch("sentry_sdk.add_breadcrumb")
@patch("sentry_sdk.start_span")
def test_pre_arb_response_creates_span(
    mock_start_span: MagicMock,
    mock_add_breadcrumb: MagicMock,
) -> None:
    """Pre-arb response processing should create the correct spans."""
    span_ctx = MagicMock()
    mock_start_span.return_value.__enter__ = MagicMock(return_value=span_ctx)
    mock_start_span.return_value.__exit__ = MagicMock(return_value=False)

    agent = PreArbitrationAgent()
    case = _make_case(DisputeLifecycleStage.PRE_ARBITRATION_RESPONSE)
    asyncio.get_event_loop().run_until_complete(agent.process(case))

    span_calls = [call.kwargs for call in mock_start_span.call_args_list]
    ops = [c.get("op") for c in span_calls]
    assert "agent.process" in ops
    assert "ai.chat_completion" in ops

    # Decision breadcrumb should be recorded
    mock_add_breadcrumb.assert_called()
