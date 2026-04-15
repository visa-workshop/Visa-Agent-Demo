"""Tests for Sentry instrumentation on the AuthorizationDisputeAgent.

Verifies that processing, validation, and LLM calls create proper Sentry
spans/breadcrumbs, and that exceptions are captured correctly.
"""

from datetime import date, datetime
from unittest.mock import MagicMock, patch

import pytest

from src.agents.authorization_agent import AuthorizationDisputeAgent
from src.models.dispute import (
    CardholderInfo,
    DisputeCase,
    DisputeEvidence,
    TransactionDetails,
)
from src.models.enums import (
    DisputeCategory,
    DisputeCondition,
    DisputeLifecycleStage,
    Region,
    TransactionEnvironment,
)


def _make_case(
    condition: DisputeCondition | None = None,
    category: DisputeCategory | None = None,
    statement: str | None = None,
    evidence: list[DisputeEvidence] | None = None,
    dispute_filed_date: datetime | None = None,
    dispute_amount: float | None = None,
    **txn_overrides: object,
) -> DisputeCase:
    """Create a test DisputeCase with sensible defaults."""
    txn_defaults: dict[str, object] = {
        "transaction_id": "TXN-INST-001",
        "transaction_date": date(2026, 2, 15),
        "processing_date": date(2026, 2, 16),
        "amount": 500.0,
        "currency": "USD",
        "merchant_name": "TestMerchant",
        "merchant_category_code": "5411",
        "merchant_country": "US",
        "acquirer_bin": "411111",
        "issuer_bin": "422222",
        "environment": TransactionEnvironment.ECOMMERCE,
        "region": Region.US,
    }
    txn_defaults.update(txn_overrides)

    return DisputeCase(
        transaction=TransactionDetails(**txn_defaults),
        cardholder=CardholderInfo(
            cardholder_name="Test User",
            partial_payment_credential="****1234",
            cardholder_statement=statement,
        ),
        condition=condition,
        category=category,
        evidence=evidence or [],
        stage=DisputeLifecycleStage.PROCESSING,
        dispute_filed_date=dispute_filed_date,
        dispute_amount=dispute_amount,
    )


@pytest.fixture
def agent() -> AuthorizationDisputeAgent:
    return AuthorizationDisputeAgent()


class TestProcessSpan:
    """Verify that process() creates a Sentry span."""

    async def test_process_creates_sentry_span(
        self, agent: AuthorizationDisputeAgent
    ) -> None:
        case = _make_case(
            condition=DisputeCondition.DECLINED_AUTHORIZATION,
            dispute_filed_date=datetime(2026, 2, 17),
            authorization_response_code="14",
        )
        with patch("sentry_sdk.start_span") as mock_start_span:
            mock_span = MagicMock()
            mock_start_span.return_value.__enter__ = MagicMock(return_value=mock_span)
            mock_start_span.return_value.__exit__ = MagicMock(return_value=False)

            await agent.process(case)

            # The process decorator should call start_span with agent.process op
            calls = mock_start_span.call_args_list
            process_calls = [
                c
                for c in calls
                if c.kwargs.get("op") == "agent.process"
                and c.kwargs.get("name") == "authorization_agent.process"
            ]
            assert len(process_calls) >= 1, (
                f"Expected start_span with op='agent.process', got: {calls}"
            )


class TestValidateSpan:
    """Verify that validate() creates a Sentry span."""

    async def test_validate_creates_sentry_span(
        self, agent: AuthorizationDisputeAgent
    ) -> None:
        case = _make_case(condition=DisputeCondition.DECLINED_AUTHORIZATION)
        with patch("sentry_sdk.start_span") as mock_start_span:
            mock_span = MagicMock()
            mock_start_span.return_value.__enter__ = MagicMock(return_value=mock_span)
            mock_start_span.return_value.__exit__ = MagicMock(return_value=False)

            await agent.validate(case)

            calls = mock_start_span.call_args_list
            validate_calls = [
                c
                for c in calls
                if c.kwargs.get("op") == "agent.validate"
            ]
            assert len(validate_calls) >= 1, (
                f"Expected start_span with op='agent.validate', got: {calls}"
            )


class TestLLMCallSpan:
    """Verify that LLM evaluation creates a Sentry span."""

    async def test_llm_call_creates_sentry_span(
        self, agent: AuthorizationDisputeAgent
    ) -> None:
        case = _make_case(
            condition=DisputeCondition.DECLINED_AUTHORIZATION,
            dispute_filed_date=datetime(2026, 2, 17),
            authorization_response_code="14",
        )
        with patch("sentry_sdk.start_span") as mock_start_span:
            mock_span = MagicMock()
            mock_start_span.return_value.__enter__ = MagicMock(return_value=mock_span)
            mock_start_span.return_value.__exit__ = MagicMock(return_value=False)

            await agent.process(case)

            calls = mock_start_span.call_args_list
            llm_calls = [
                c
                for c in calls
                if c.kwargs.get("op") == "ai.chat_completion"
            ]
            assert len(llm_calls) >= 1, (
                f"Expected start_span with op='ai.chat_completion', got: {calls}"
            )


class TestDecisionBreadcrumb:
    """Verify that a decision is recorded as a Sentry breadcrumb."""

    async def test_decision_recorded_as_breadcrumb(
        self, agent: AuthorizationDisputeAgent
    ) -> None:
        case = _make_case(
            condition=DisputeCondition.DECLINED_AUTHORIZATION,
            dispute_filed_date=datetime(2026, 2, 17),
            authorization_response_code="14",
        )
        with patch("sentry_sdk.add_breadcrumb") as mock_breadcrumb, \
             patch("sentry_sdk.start_span") as mock_start_span:
            mock_span = MagicMock()
            mock_start_span.return_value.__enter__ = MagicMock(return_value=mock_span)
            mock_start_span.return_value.__exit__ = MagicMock(return_value=False)

            await agent.process(case)

            assert mock_breadcrumb.called, "Expected add_breadcrumb to be called"
            breadcrumb_call = mock_breadcrumb.call_args
            assert breadcrumb_call.kwargs.get("category") == "agent.decision", (
                f"Expected category='agent.decision', got: {breadcrumb_call}"
            )


class TestExceptionCapture:
    """Verify that exceptions during processing are captured by Sentry."""

    async def test_process_captures_exception_on_error(
        self, agent: AuthorizationDisputeAgent
    ) -> None:
        case = _make_case(
            condition=DisputeCondition.DECLINED_AUTHORIZATION,
            dispute_filed_date=datetime(2026, 2, 17),
            authorization_response_code="14",
        )
        with patch("sentry_sdk.capture_exception") as mock_capture, \
             patch("sentry_sdk.start_span") as mock_start_span, \
             patch.object(
                 agent, "_evaluate_dispute_with_llm", side_effect=RuntimeError("LLM failure")
             ):
            mock_span = MagicMock()
            mock_start_span.return_value.__enter__ = MagicMock(return_value=mock_span)
            mock_start_span.return_value.__exit__ = MagicMock(return_value=False)

            with pytest.raises(RuntimeError, match="LLM failure"):
                await agent.process(case)

            assert mock_capture.called, "Expected capture_exception to be called"
            captured_exc = mock_capture.call_args[0][0]
            assert isinstance(captured_exc, RuntimeError)


class TestSpanMetadata:
    """Verify that span data includes case metadata and decision outcome."""

    async def test_span_records_case_metadata(
        self, agent: AuthorizationDisputeAgent
    ) -> None:
        case = _make_case(
            condition=DisputeCondition.NO_AUTHORIZATION,
            category=DisputeCategory.AUTHORIZATION,
            dispute_filed_date=datetime(2026, 2, 17),
            authorization_code=None,
        )
        with patch("sentry_sdk.start_span") as mock_start_span:
            mock_span = MagicMock()
            mock_start_span.return_value.__enter__ = MagicMock(return_value=mock_span)
            mock_start_span.return_value.__exit__ = MagicMock(return_value=False)

            await agent.process(case)

            # Collect all set_data calls across all spans
            set_data_calls = {
                c[0][0]: c[0][1] for c in mock_span.set_data.call_args_list
            }
            assert "case.id" in set_data_calls, (
                f"Expected 'case.id' in span data, got keys: {list(set_data_calls.keys())}"
            )
            assert "case.category" in set_data_calls, (
                f"Expected 'case.category' in span data, got keys: {list(set_data_calls.keys())}"
            )
            assert "case.condition" in set_data_calls, (
                f"Expected 'case.condition' in span data, got keys: {list(set_data_calls.keys())}"
            )
            assert set_data_calls["case.condition"] == "11.3"

    async def test_span_records_decision_outcome(
        self, agent: AuthorizationDisputeAgent
    ) -> None:
        case = _make_case(
            condition=DisputeCondition.DECLINED_AUTHORIZATION,
            dispute_filed_date=datetime(2026, 2, 17),
            authorization_response_code="14",
        )
        with patch("sentry_sdk.start_span") as mock_start_span:
            mock_span = MagicMock()
            mock_start_span.return_value.__enter__ = MagicMock(return_value=mock_span)
            mock_start_span.return_value.__exit__ = MagicMock(return_value=False)

            result = await agent.process(case)

            set_data_calls = {
                c[0][0]: c[0][1] for c in mock_span.set_data.call_args_list
            }
            assert "decision.resolution" in set_data_calls, (
                f"Expected 'decision.resolution' in span data, got keys: {list(set_data_calls.keys())}"
            )
            assert "decision.confidence" in set_data_calls, (
                f"Expected 'decision.confidence' in span data, got keys: {list(set_data_calls.keys())}"
            )
            # Verify the values match the actual decision
            assert set_data_calls["decision.resolution"] == result.decision.resolution.value
            assert set_data_calls["decision.confidence"] == result.decision.confidence_score
