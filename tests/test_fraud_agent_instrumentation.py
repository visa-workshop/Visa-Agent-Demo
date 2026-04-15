"""Tests verifying Sentry instrumentation on FraudDisputeAgent.

Each test mocks sentry_sdk functions and asserts that the instrumentation
decorators produce the expected spans, breadcrumbs, and metadata.
"""

from datetime import date, datetime
from unittest.mock import MagicMock, patch

import pytest

from src.agents.fraud_agent import FraudDisputeAgent
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
    FraudTypeCode,
    Region,
    TransactionEnvironment,
)


def _make_case(
    condition: DisputeCondition | None = None,
    category: DisputeCategory | None = None,
    fraud_type_code: FraudTypeCode | None = None,
    statement: str | None = None,
    issuer_certification: str | None = None,
    evidence: list[DisputeEvidence] | None = None,
    stage: DisputeLifecycleStage = DisputeLifecycleStage.PROCESSING,
    dispute_filed_date: datetime | None = None,
    dispute_amount: float | None = None,
    **txn_overrides: object,
) -> DisputeCase:
    txn_defaults: dict = {
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
        fraud_type_code=fraud_type_code,
        issuer_certification=issuer_certification,
        evidence=evidence or [],
        stage=stage,
        dispute_filed_date=dispute_filed_date,
        dispute_amount=dispute_amount,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _valid_fraud_case() -> DisputeCase:
    """Return a standard valid fraud case that will resolve successfully."""
    return _make_case(
        condition=DisputeCondition.OTHER_FRAUD_CARD_ABSENT,
        fraud_type_code=FraudTypeCode.ACCOUNT_TAKEOVER,
        issuer_certification="Cardholder denies authorization",
        dispute_filed_date=datetime(2026, 2, 17),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestFraudAgentInstrumentation:
    """Verify Sentry spans, breadcrumbs, and metadata from instrumentation."""

    @pytest.fixture()
    def agent(self) -> FraudDisputeAgent:
        return FraudDisputeAgent()

    # 1. process() creates a span with op="agent.process"
    @patch("src.instrumentation.tracing.sentry_sdk")
    async def test_process_creates_sentry_span(
        self, mock_sentry: MagicMock, agent: FraudDisputeAgent
    ) -> None:
        mock_span = MagicMock()
        mock_sentry.start_span.return_value.__enter__ = MagicMock(return_value=mock_span)
        mock_sentry.start_span.return_value.__exit__ = MagicMock(return_value=False)

        case = _valid_fraud_case()
        await agent.process(case)

        mock_sentry.start_span.assert_any_call(
            op="agent.process",
            name="fraud_agent.process",
        )

    # 2. validate() creates a span with op="agent.validate"
    @patch("src.instrumentation.tracing.sentry_sdk")
    async def test_validate_creates_sentry_span(
        self, mock_sentry: MagicMock, agent: FraudDisputeAgent
    ) -> None:
        mock_span = MagicMock()
        mock_sentry.start_span.return_value.__enter__ = MagicMock(return_value=mock_span)
        mock_sentry.start_span.return_value.__exit__ = MagicMock(return_value=False)

        case = _make_case(condition=DisputeCondition.OTHER_FRAUD_CARD_ABSENT)
        await agent.validate(case)

        mock_sentry.start_span.assert_any_call(
            op="agent.validate",
            name="fraud_agent.validate",
        )

    # 3. LLM evaluation creates a span with op="ai.chat_completion"
    @patch("src.instrumentation.tracing.sentry_sdk")
    async def test_llm_call_creates_sentry_span(
        self, mock_sentry: MagicMock, agent: FraudDisputeAgent
    ) -> None:
        mock_span = MagicMock()
        mock_sentry.start_span.return_value.__enter__ = MagicMock(return_value=mock_span)
        mock_sentry.start_span.return_value.__exit__ = MagicMock(return_value=False)

        case = _valid_fraud_case()
        await agent.process(case)

        # The LLM call span should be created during process()
        calls = mock_sentry.start_span.call_args_list
        llm_calls = [
            c for c in calls
            if c.kwargs.get("op") == "ai.chat_completion"
            or (c.args and len(c.args) > 0 and c.args[0] == "ai.chat_completion")
        ]
        assert len(llm_calls) >= 1, (
            f"Expected at least one ai.chat_completion span, got {calls}"
        )
        assert llm_calls[0].kwargs["name"] == "fraud_agent.llm_call"

    # 4. Decision recorded as breadcrumb with category="agent.decision"
    @patch("src.instrumentation.tracing.sentry_sdk")
    async def test_decision_recorded_as_breadcrumb(
        self, mock_sentry: MagicMock, agent: FraudDisputeAgent
    ) -> None:
        mock_span = MagicMock()
        mock_sentry.start_span.return_value.__enter__ = MagicMock(return_value=mock_span)
        mock_sentry.start_span.return_value.__exit__ = MagicMock(return_value=False)

        case = _valid_fraud_case()
        await agent.process(case)

        mock_sentry.add_breadcrumb.assert_called()
        breadcrumb_call = mock_sentry.add_breadcrumb.call_args
        assert breadcrumb_call.kwargs["category"] == "agent.decision"

    # 5. Exception during processing triggers capture_exception
    @patch("src.instrumentation.tracing.sentry_sdk")
    async def test_process_captures_exception_on_error(
        self, mock_sentry: MagicMock, agent: FraudDisputeAgent
    ) -> None:
        mock_span = MagicMock()
        mock_sentry.start_span.return_value.__enter__ = MagicMock(return_value=mock_span)
        mock_sentry.start_span.return_value.__exit__ = MagicMock(return_value=False)

        case = _valid_fraud_case()

        with (
            patch.object(
                agent, "_evaluate_dispute_with_llm", side_effect=RuntimeError("LLM failure")
            ),
            pytest.raises(RuntimeError, match="LLM failure"),
        ):
            await agent.process(case)

        mock_sentry.capture_exception.assert_called()

    # 6. Span data includes case metadata (case_id, category, condition, dispute_amount)
    @patch("src.instrumentation.tracing.sentry_sdk")
    async def test_span_records_case_metadata(
        self, mock_sentry: MagicMock, agent: FraudDisputeAgent
    ) -> None:
        mock_span = MagicMock()
        mock_sentry.start_span.return_value.__enter__ = MagicMock(return_value=mock_span)
        mock_sentry.start_span.return_value.__exit__ = MagicMock(return_value=False)

        case = _make_case(
            condition=DisputeCondition.OTHER_FRAUD_CARD_ABSENT,
            category=DisputeCategory.FRAUD,
            fraud_type_code=FraudTypeCode.ACCOUNT_TAKEOVER,
            issuer_certification="Denial",
            dispute_filed_date=datetime(2026, 2, 17),
            dispute_amount=1200.0,
        )
        await agent.process(case)

        set_data_calls = {
            call.args[0]: call.args[1]
            for call in mock_span.set_data.call_args_list
        }
        assert set_data_calls.get("case.id") == case.case_id
        assert set_data_calls.get("case.category") == "10"
        assert set_data_calls.get("case.condition") == "10.4"
        assert set_data_calls.get("case.dispute_amount") == 1200.0

    # 7. Span data includes decision outcome after successful processing
    @patch("src.instrumentation.tracing.sentry_sdk")
    async def test_span_records_decision_outcome(
        self, mock_sentry: MagicMock, agent: FraudDisputeAgent
    ) -> None:
        mock_span = MagicMock()
        mock_sentry.start_span.return_value.__enter__ = MagicMock(return_value=mock_span)
        mock_sentry.start_span.return_value.__exit__ = MagicMock(return_value=False)

        case = _valid_fraud_case()
        result = await agent.process(case)

        set_data_calls = {
            call.args[0]: call.args[1]
            for call in mock_span.set_data.call_args_list
        }
        assert "decision.resolution" in set_data_calls
        assert set_data_calls["decision.resolution"] == result.decision.resolution.value
        assert "decision.confidence" in set_data_calls
        assert set_data_calls["decision.confidence"] == result.decision.confidence_score
        assert "decision.requires_human_review" in set_data_calls
        assert (
            set_data_calls["decision.requires_human_review"]
            == result.decision.requires_human_review
        )
