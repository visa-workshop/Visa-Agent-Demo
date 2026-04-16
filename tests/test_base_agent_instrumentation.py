"""Tests for instrumentation logging in BaseDisputeAgent.

Verifies that _should_escalate_to_human, create_decision, and
_evaluate_dispute_with_llm produce the expected log messages at the
correct levels (INFO, WARNING, ERROR).
"""

import logging
from datetime import date, datetime
from unittest.mock import patch

import pytest

from src.agents.base_agent import BaseDisputeAgent
from src.models.dispute import (
    CardholderInfo,
    DisputeCase,
    DisputeDecision,
    RuleEvaluationResult,
    TransactionDetails,
)
from src.models.enums import (
    AgentType,
    DisputeCategory,
    DisputeCondition,
    DisputeResolution,
    TransactionEnvironment,
)

# ---------------------------------------------------------------------------
# Concrete subclass so we can instantiate the abstract BaseDisputeAgent
# ---------------------------------------------------------------------------


class _ConcreteAgent(BaseDisputeAgent):
    """Minimal concrete implementation used only in tests."""

    def __init__(self) -> None:
        super().__init__(AgentType.FRAUD)

    async def process(self, case: DisputeCase) -> DisputeCase:
        return case

    async def validate(self, case: DisputeCase) -> bool:
        return True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_case(
    dispute_amount: float | None = 1000.0,
    category: DisputeCategory | None = DisputeCategory.FRAUD,
    condition: DisputeCondition | None = DisputeCondition.OTHER_FRAUD_CARD_ABSENT,
) -> DisputeCase:
    """Build a minimal DisputeCase for testing."""
    return DisputeCase(
        case_id="TEST-001",
        transaction=TransactionDetails(
            transaction_id="TXN-001",
            transaction_date=date(2025, 1, 15),
            processing_date=date(2025, 1, 16),
            amount=500.0,
            currency="USD",
            merchant_name="Test Merchant",
            merchant_category_code="5411",
            merchant_country="US",
            acquirer_bin="123456",
            issuer_bin="654321",
            environment=TransactionEnvironment.ECOMMERCE,
        ),
        cardholder=CardholderInfo(
            cardholder_name="Jane Doe",
            partial_payment_credential="*1234",
            cardholder_statement="I did not authorize this transaction",
        ),
        dispute_amount=dispute_amount,
        category=category,
        condition=condition,
        dispute_filed_date=datetime(2025, 2, 1),
    )


def _make_rule_eval() -> RuleEvaluationResult:
    return RuleEvaluationResult(
        rule_id="time_limit_check",
        rule_section="11.7",
        rule_description="Time limit check",
        is_satisfied=True,
        details="Within time limit",
    )


# ---------------------------------------------------------------------------
# Tests: _should_escalate_to_human
# ---------------------------------------------------------------------------


class TestShouldEscalateToHuman:
    """Verify logging produced by _should_escalate_to_human."""

    def test_low_confidence_logs_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        agent = _ConcreteAgent()
        case = _make_case(dispute_amount=1000.0)

        with caplog.at_level(logging.DEBUG):
            result = agent._should_escalate_to_human(0.50, case)

        assert result is True
        # Should log WARNING about low confidence
        warning_msgs = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert any("low confidence" in m.message.lower() for m in warning_msgs)
        assert any("0.50" in m.message for m in warning_msgs)

    def test_high_amount_logs_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        agent = _ConcreteAgent()
        case = _make_case(dispute_amount=30000.0)

        with caplog.at_level(logging.DEBUG):
            result = agent._should_escalate_to_human(0.90, case)

        assert result is True
        warning_msgs = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert any("high dispute amount" in m.message.lower() for m in warning_msgs)
        assert any("30000" in m.message for m in warning_msgs)

    def test_no_escalation_logs_info(self, caplog: pytest.LogCaptureFixture) -> None:
        agent = _ConcreteAgent()
        case = _make_case(dispute_amount=1000.0)

        with caplog.at_level(logging.DEBUG):
            result = agent._should_escalate_to_human(0.90, case)

        assert result is False
        info_msgs = [r for r in caplog.records if r.levelno == logging.INFO]
        assert any("no escalation" in m.message.lower() for m in info_msgs)


# ---------------------------------------------------------------------------
# Tests: create_decision
# ---------------------------------------------------------------------------


class TestCreateDecision:
    """Verify logging produced by create_decision."""

    def test_logs_decision_details(self, caplog: pytest.LogCaptureFixture) -> None:
        agent = _ConcreteAgent()

        with caplog.at_level(logging.DEBUG):
            decision = agent.create_decision(
                resolution=DisputeResolution.ISSUER_WIN,
                rationale="Fraud confirmed",
                rule_evaluations=[_make_rule_eval()],
                confidence=0.92,
                requires_human_review=False,
            )

        assert isinstance(decision, DisputeDecision)
        info_msgs = [r for r in caplog.records if r.levelno == logging.INFO]
        assert any("issuer_win" in m.message for m in info_msgs)
        assert any("0.92" in m.message for m in info_msgs)
        assert any("fraud_agent" in m.message for m in info_msgs)

    def test_human_review_logs_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        agent = _ConcreteAgent()

        with caplog.at_level(logging.DEBUG):
            decision = agent.create_decision(
                resolution=DisputeResolution.ISSUER_WIN,
                rationale="Needs review",
                rule_evaluations=[_make_rule_eval()],
                confidence=0.60,
                requires_human_review=True,
                human_review_reason="Low confidence score",
            )

        assert decision.requires_human_review is True
        warning_msgs = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert any("human review" in m.message.lower() for m in warning_msgs)
        assert any("Low confidence score" in m.message for m in warning_msgs)


# ---------------------------------------------------------------------------
# Tests: _evaluate_dispute_with_llm
# ---------------------------------------------------------------------------


class TestEvaluateDisputeWithLLM:
    """Verify logging produced by _evaluate_dispute_with_llm."""

    def test_logs_timing_and_results(self, caplog: pytest.LogCaptureFixture) -> None:
        agent = _ConcreteAgent()
        case = _make_case()

        with caplog.at_level(logging.DEBUG):
            result = agent._evaluate_dispute_with_llm(
                case, "mock rules context", "You are a fraud agent"
            )

        assert isinstance(result, dict)
        info_msgs = [r for r in caplog.records if r.levelno == logging.INFO]
        # Should log the pre-call info with case_id, category, condition
        assert any("TEST-001" in m.message for m in info_msgs)
        assert any("category" in m.message.lower() for m in info_msgs)
        # Should log the post-call info with timing and result keys
        assert any("completed" in m.message.lower() for m in info_msgs)
        assert any("resolution" in m.message.lower() for m in info_msgs)

    def test_logs_error_on_llm_failure(self, caplog: pytest.LogCaptureFixture) -> None:
        agent = _ConcreteAgent()
        case = _make_case()

        with (
            patch(
                "src.agents.base_agent.chat_json",
                side_effect=RuntimeError("API timeout"),
            ),
            caplog.at_level(logging.DEBUG),
            pytest.raises(RuntimeError, match="API timeout"),
        ):
            agent._evaluate_dispute_with_llm(
                case, "mock rules context", "You are a fraud agent"
            )

        error_msgs = [r for r in caplog.records if r.levelno == logging.ERROR]
        assert len(error_msgs) >= 1
        assert any("failed" in m.message.lower() for m in error_msgs)
        assert any("TEST-001" in m.message for m in error_msgs)
