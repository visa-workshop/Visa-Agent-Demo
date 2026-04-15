"""Tests for Sentry instrumentation on ProcessingErrorsAgent.

Verifies that the agent correctly creates Sentry spans, breadcrumbs,
and captures exceptions during dispute processing.
"""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from src.agents.processing_errors_agent import ProcessingErrorsAgent
from src.models.dispute import (
    CardholderInfo,
    DisputeCase,
    DisputeEvidence,
    TransactionDetails,
)
from src.models.enums import (
    DisputeCondition,
    DisputeLifecycleStage,
    Region,
    TransactionEnvironment,
)


def _make_case(
    condition: DisputeCondition | None = None,
    dispute_amount: float | None = None,
    dispute_filed_date: datetime | None = None,
    evidence: list[DisputeEvidence] | None = None,
    statement: str | None = None,
) -> DisputeCase:
    """Create a test DisputeCase for processing errors."""
    return DisputeCase(
        transaction=TransactionDetails(
            transaction_id="TXN-INST-001",
            transaction_date=datetime(2026, 2, 15).date(),
            processing_date=datetime(2026, 2, 16).date(),
            amount=500.0,
            currency="USD",
            merchant_name="TestMerchant",
            merchant_category_code="5411",
            merchant_country="US",
            acquirer_bin="411111",
            issuer_bin="422222",
            environment=TransactionEnvironment.ECOMMERCE,
            region=Region.US,
        ),
        cardholder=CardholderInfo(
            cardholder_name="Test User",
            partial_payment_credential="****1234",
            cardholder_statement=statement,
        ),
        condition=condition,
        evidence=evidence or [],
        stage=DisputeLifecycleStage.PROCESSING,
        dispute_filed_date=dispute_filed_date,
        dispute_amount=dispute_amount,
    )


@pytest.fixture
def agent() -> ProcessingErrorsAgent:
    return ProcessingErrorsAgent()


class TestProcessCreatesSentrySpan:
    """test_process_creates_sentry_span"""

    async def test_process_creates_sentry_span(self, agent: ProcessingErrorsAgent) -> None:
        """Verify that processing a case calls sentry_sdk.start_span with
        op='agent.process' and name='processing_errors_agent.process'."""
        case = _make_case(
            condition=DisputeCondition.DUPLICATE_PROCESSING,
            dispute_filed_date=datetime(2026, 2, 17),
        )
        mock_span = MagicMock()
        mock_span.__enter__ = MagicMock(return_value=mock_span)
        mock_span.__exit__ = MagicMock(return_value=False)

        with patch("src.instrumentation.tracing.sentry_sdk.start_span", return_value=mock_span) as mock_start:
            await agent.process(case)
            # Find the call with op="agent.process"
            found = False
            for call in mock_start.call_args_list:
                kwargs = call.kwargs if call.kwargs else {}
                if kwargs.get("op") == "agent.process" and kwargs.get("name") == "processing_errors_agent.process":
                    found = True
                    break
            assert found, (
                f"Expected sentry_sdk.start_span called with op='agent.process' "
                f"and name='processing_errors_agent.process', got calls: {mock_start.call_args_list}"
            )


class TestValidateCreatesSentrySpan:
    """test_validate_creates_sentry_span"""

    async def test_validate_creates_sentry_span(self, agent: ProcessingErrorsAgent) -> None:
        """Verify validation creates a span with op='agent.validate'."""
        case = _make_case(condition=DisputeCondition.INCORRECT_AMOUNT)
        mock_span = MagicMock()
        mock_span.__enter__ = MagicMock(return_value=mock_span)
        mock_span.__exit__ = MagicMock(return_value=False)

        with patch("src.instrumentation.tracing.sentry_sdk.start_span", return_value=mock_span) as mock_start:
            result = await agent.validate(case)
            assert result is True
            found = False
            for call in mock_start.call_args_list:
                kwargs = call.kwargs if call.kwargs else {}
                if kwargs.get("op") == "agent.validate":
                    found = True
                    break
            assert found, (
                f"Expected sentry_sdk.start_span called with op='agent.validate', "
                f"got calls: {mock_start.call_args_list}"
            )


class TestLlmCallCreatesSentrySpan:
    """test_llm_call_creates_sentry_span"""

    async def test_llm_call_creates_sentry_span(self, agent: ProcessingErrorsAgent) -> None:
        """Verify LLM evaluation creates a span with op='ai.chat_completion'."""
        case = _make_case(
            condition=DisputeCondition.DUPLICATE_PROCESSING,
            dispute_filed_date=datetime(2026, 2, 17),
        )
        mock_span = MagicMock()
        mock_span.__enter__ = MagicMock(return_value=mock_span)
        mock_span.__exit__ = MagicMock(return_value=False)

        with patch("src.instrumentation.tracing.sentry_sdk.start_span", return_value=mock_span) as mock_start:
            await agent.process(case)
            found = False
            for call in mock_start.call_args_list:
                kwargs = call.kwargs if call.kwargs else {}
                if kwargs.get("op") == "ai.chat_completion":
                    found = True
                    break
            assert found, (
                f"Expected sentry_sdk.start_span called with op='ai.chat_completion', "
                f"got calls: {mock_start.call_args_list}"
            )


class TestDecisionRecordedAsBreadcrumb:
    """test_decision_recorded_as_breadcrumb"""

    async def test_decision_recorded_as_breadcrumb(self, agent: ProcessingErrorsAgent) -> None:
        """Verify sentry_sdk.add_breadcrumb is called after a decision
        with category='agent.decision'."""
        case = _make_case(
            condition=DisputeCondition.DUPLICATE_PROCESSING,
            dispute_filed_date=datetime(2026, 2, 17),
        )

        with patch("src.instrumentation.tracing.sentry_sdk.add_breadcrumb") as mock_breadcrumb:
            await agent.process(case)
            mock_breadcrumb.assert_called_once()
            call_kwargs = mock_breadcrumb.call_args.kwargs if mock_breadcrumb.call_args.kwargs else mock_breadcrumb.call_args[1]
            assert call_kwargs.get("category") == "agent.decision"


class TestProcessCapturesExceptionOnError:
    """test_process_captures_exception_on_error"""

    async def test_process_captures_exception_on_error(self, agent: ProcessingErrorsAgent) -> None:
        """Mock an exception during processing and verify
        sentry_sdk.capture_exception is called."""
        case = _make_case(
            condition=DisputeCondition.DUPLICATE_PROCESSING,
            dispute_filed_date=datetime(2026, 2, 17),
        )

        with (
            patch.object(
                agent,
                "_evaluate_dispute_with_llm",
                side_effect=RuntimeError("LLM service unavailable"),
            ),
            patch("src.instrumentation.tracing.sentry_sdk.capture_exception") as mock_capture,
            patch("src.instrumentation.tracing.sentry_sdk.start_span") as mock_start,
        ):
            mock_span = MagicMock()
            mock_span.__enter__ = MagicMock(return_value=mock_span)
            mock_span.__exit__ = MagicMock(return_value=False)
            mock_start.return_value = mock_span

            with pytest.raises(RuntimeError, match="LLM service unavailable"):
                await agent.process(case)

            mock_capture.assert_called_once()
            exc_arg = mock_capture.call_args[0][0]
            assert isinstance(exc_arg, RuntimeError)


class TestSpanRecordsCaseMetadata:
    """test_span_records_case_metadata"""

    async def test_span_records_case_metadata(self, agent: ProcessingErrorsAgent) -> None:
        """Verify span data includes case_id, category, condition."""
        case = _make_case(
            condition=DisputeCondition.INCORRECT_AMOUNT,
            dispute_filed_date=datetime(2026, 2, 17),
            dispute_amount=100.0,
        )
        mock_span = MagicMock()
        mock_span.__enter__ = MagicMock(return_value=mock_span)
        mock_span.__exit__ = MagicMock(return_value=False)

        with patch("src.instrumentation.tracing.sentry_sdk.start_span", return_value=mock_span):
            await agent.process(case)

        # Collect all set_data calls
        set_data_calls = {call[0][0]: call[0][1] for call in mock_span.set_data.call_args_list}
        assert "case.id" in set_data_calls
        assert set_data_calls["case.id"] == case.case_id
        assert "case.condition" in set_data_calls
        assert set_data_calls["case.condition"] == DisputeCondition.INCORRECT_AMOUNT.value


class TestSpanRecordsDecisionOutcome:
    """test_span_records_decision_outcome"""

    async def test_span_records_decision_outcome(self, agent: ProcessingErrorsAgent) -> None:
        """Verify span data includes resolution, confidence after successful processing."""
        case = _make_case(
            condition=DisputeCondition.DUPLICATE_PROCESSING,
            dispute_filed_date=datetime(2026, 2, 17),
        )
        mock_span = MagicMock()
        mock_span.__enter__ = MagicMock(return_value=mock_span)
        mock_span.__exit__ = MagicMock(return_value=False)

        with patch("src.instrumentation.tracing.sentry_sdk.start_span", return_value=mock_span):
            result = await agent.process(case)

        set_data_calls = {call[0][0]: call[0][1] for call in mock_span.set_data.call_args_list}
        assert "decision.resolution" in set_data_calls
        assert set_data_calls["decision.resolution"] == result.decision.resolution.value
        assert "decision.confidence" in set_data_calls
        assert set_data_calls["decision.confidence"] == result.decision.confidence_score
