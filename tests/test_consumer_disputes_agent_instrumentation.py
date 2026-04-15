"""Tests for Sentry instrumentation on ConsumerDisputesAgent.

Verifies that the agent's process(), validate(), and LLM evaluation methods
create appropriate Sentry spans, breadcrumbs, and exception captures.
"""

from datetime import date, datetime
from unittest.mock import MagicMock, call, patch

import pytest

from src.agents.consumer_disputes_agent import ConsumerDisputesAgent
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
    stage: DisputeLifecycleStage = DisputeLifecycleStage.PROCESSING,
    dispute_filed_date: datetime | None = None,
    dispute_amount: float | None = None,
    **txn_overrides: object,
) -> DisputeCase:
    txn_defaults = {
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
        stage=stage,
        dispute_filed_date=dispute_filed_date,
        dispute_amount=dispute_amount,
    )


class TestConsumerDisputesAgentInstrumentation:
    """Verify Sentry instrumentation on ConsumerDisputesAgent."""

    @pytest.fixture
    def agent(self) -> ConsumerDisputesAgent:
        return ConsumerDisputesAgent()

    # 1. test_process_creates_sentry_span
    async def test_process_creates_sentry_span(self, agent: ConsumerDisputesAgent) -> None:
        """Verify that processing a case calls sentry_sdk.start_span with
        op='agent.process' and name='consumer_disputes_agent.process'."""
        case = _make_case(
            condition=DisputeCondition.MERCHANDISE_NOT_RECEIVED,
            statement="I never received my order",
            dispute_filed_date=datetime(2026, 2, 17),
        )

        mock_span = MagicMock()
        mock_span.__enter__ = MagicMock(return_value=mock_span)
        mock_span.__exit__ = MagicMock(return_value=False)

        with patch("sentry_sdk.start_span", return_value=mock_span) as mock_start_span:
            await agent.process(case)

            # The process decorator should create a span with op="agent.process"
            mock_start_span.assert_any_call(
                op="agent.process",
                name="consumer_disputes_agent.process",
            )

    # 2. test_validate_creates_sentry_span
    async def test_validate_creates_sentry_span(self, agent: ConsumerDisputesAgent) -> None:
        """Verify validation creates a span with op='agent.validate'."""
        case = _make_case(condition=DisputeCondition.MERCHANDISE_NOT_RECEIVED)

        mock_span = MagicMock()
        mock_span.__enter__ = MagicMock(return_value=mock_span)
        mock_span.__exit__ = MagicMock(return_value=False)

        with patch("sentry_sdk.start_span", return_value=mock_span) as mock_start_span:
            await agent.validate(case)

            mock_start_span.assert_called_once_with(
                op="agent.validate",
                name="consumer_disputes_agent.validate",
            )

    # 3. test_llm_call_creates_sentry_span
    async def test_llm_call_creates_sentry_span(self, agent: ConsumerDisputesAgent) -> None:
        """Verify LLM evaluation creates a span with op='ai.chat_completion'."""
        case = _make_case(
            condition=DisputeCondition.CANCELLED_RECURRING,
            statement="I cancelled my subscription but was still charged",
            dispute_filed_date=datetime(2026, 2, 17),
        )

        mock_span = MagicMock()
        mock_span.__enter__ = MagicMock(return_value=mock_span)
        mock_span.__exit__ = MagicMock(return_value=False)

        with patch("sentry_sdk.start_span", return_value=mock_span) as mock_start_span:
            await agent.process(case)

            # Check that one of the start_span calls was for ai.chat_completion
            llm_calls = [
                c for c in mock_start_span.call_args_list
                if c == call(op="ai.chat_completion", name="consumer_disputes_agent.llm_call")
            ]
            assert len(llm_calls) >= 1, (
                f"Expected a start_span call with op='ai.chat_completion', "
                f"got calls: {mock_start_span.call_args_list}"
            )

    # 4. test_decision_recorded_as_breadcrumb
    async def test_decision_recorded_as_breadcrumb(self, agent: ConsumerDisputesAgent) -> None:
        """Verify sentry_sdk.add_breadcrumb is called after a decision
        with category='agent.decision'."""
        case = _make_case(
            condition=DisputeCondition.MERCHANDISE_NOT_RECEIVED,
            statement="I never received my order",
            dispute_filed_date=datetime(2026, 2, 17),
        )

        mock_span = MagicMock()
        mock_span.__enter__ = MagicMock(return_value=mock_span)
        mock_span.__exit__ = MagicMock(return_value=False)

        with (
            patch("sentry_sdk.start_span", return_value=mock_span),
            patch("sentry_sdk.add_breadcrumb") as mock_breadcrumb,
        ):
            await agent.process(case)

            mock_breadcrumb.assert_called_once()
            breadcrumb_kwargs = mock_breadcrumb.call_args
            assert breadcrumb_kwargs[1]["category"] == "agent.decision" or \
                breadcrumb_kwargs.kwargs.get("category") == "agent.decision"

    # 5. test_process_captures_exception_on_error
    async def test_process_captures_exception_on_error(self, agent: ConsumerDisputesAgent) -> None:
        """Mock an exception during processing and verify
        sentry_sdk.capture_exception is called."""
        case = _make_case(
            condition=DisputeCondition.MERCHANDISE_NOT_RECEIVED,
            statement="I never received my order",
            dispute_filed_date=datetime(2026, 2, 17),
        )

        mock_span = MagicMock()
        mock_span.__enter__ = MagicMock(return_value=mock_span)
        mock_span.__exit__ = MagicMock(return_value=False)

        with (
            patch("sentry_sdk.start_span", return_value=mock_span),
            patch("sentry_sdk.capture_exception") as mock_capture,
            patch.object(
                agent, "_evaluate_dispute_with_llm", side_effect=RuntimeError("LLM failure")
            ),
        ):
            with pytest.raises(RuntimeError, match="LLM failure"):
                await agent.process(case)

            mock_capture.assert_called_once()
            exc_arg = mock_capture.call_args[0][0]
            assert isinstance(exc_arg, RuntimeError)

    # 6. test_span_records_case_metadata
    async def test_span_records_case_metadata(self, agent: ConsumerDisputesAgent) -> None:
        """Verify span data includes case_id, category, condition."""
        case = _make_case(
            condition=DisputeCondition.CANCELLED_RECURRING,
            statement="I cancelled my subscription but was still charged",
            dispute_filed_date=datetime(2026, 2, 17),
        )

        mock_span = MagicMock()
        mock_span.__enter__ = MagicMock(return_value=mock_span)
        mock_span.__exit__ = MagicMock(return_value=False)

        with patch("sentry_sdk.start_span", return_value=mock_span):
            await agent.process(case)

            # Collect all set_data calls into a dict
            set_data_calls = {
                c[0][0]: c[0][1] for c in mock_span.set_data.call_args_list
            }

            assert "case.id" in set_data_calls
            assert set_data_calls["case.id"] == case.case_id
            assert "case.condition" in set_data_calls
            assert set_data_calls["case.condition"] == "13.2"

    # 7. test_span_records_decision_outcome
    async def test_span_records_decision_outcome(self, agent: ConsumerDisputesAgent) -> None:
        """Verify span data includes resolution and confidence after
        successful processing."""
        case = _make_case(
            condition=DisputeCondition.MERCHANDISE_NOT_RECEIVED,
            statement="I never received my order",
            dispute_filed_date=datetime(2026, 2, 17),
        )

        mock_span = MagicMock()
        mock_span.__enter__ = MagicMock(return_value=mock_span)
        mock_span.__exit__ = MagicMock(return_value=False)

        with patch("sentry_sdk.start_span", return_value=mock_span):
            result = await agent.process(case)

            set_data_calls = {
                c[0][0]: c[0][1] for c in mock_span.set_data.call_args_list
            }

            assert "decision.resolution" in set_data_calls
            assert set_data_calls["decision.resolution"] == result.decision.resolution.value
            assert "decision.confidence" in set_data_calls
            assert isinstance(set_data_calls["decision.confidence"], float)
