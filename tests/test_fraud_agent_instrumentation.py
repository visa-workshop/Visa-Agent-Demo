"""Tests for fraud agent instrumentation (structured logging and observability).

Verifies that the FraudDisputeAgent.process() method emits the correct
log messages at the appropriate levels for various scenarios.
"""

import logging
from datetime import date, datetime, timedelta
from unittest.mock import patch

import pytest

from src.agents.fraud_agent import FraudDisputeAgent
from src.models.dispute import (
    CardholderInfo,
    DisputeCase,
    DisputeEvidence,
    TransactionDetails,
)
from src.models.enums import (
    DisputeCondition,
    DisputeLifecycleStage,
    FraudTypeCode,
    Region,
    TransactionEnvironment,
)


def _make_fraud_case(
    condition: DisputeCondition = DisputeCondition.OTHER_FRAUD_CARD_ABSENT,
    fraud_type_code: FraudTypeCode | None = FraudTypeCode.ACCOUNT_TAKEOVER,
    issuer_certification: str | None = "Cardholder denies authorization",
    dispute_filed_date: datetime | None = None,
    dispute_amount: float | None = None,
    statement: str | None = None,
    evidence: list[DisputeEvidence] | None = None,
    **txn_overrides: object,
) -> DisputeCase:
    """Create a fraud dispute case for testing."""
    if dispute_filed_date is None:
        dispute_filed_date = datetime(2026, 2, 17)

    txn_defaults = {
        "transaction_id": "TXN-FRAUD-INST-001",
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
        fraud_type_code=fraud_type_code,
        issuer_certification=issuer_certification,
        evidence=evidence or [],
        stage=DisputeLifecycleStage.PROCESSING,
        dispute_filed_date=dispute_filed_date,
        dispute_amount=dispute_amount,
    )


class TestFraudAgentInstrumentationValidCase:
    """Test that processing a valid fraud case logs start, LLM result, and final decision."""

    @pytest.fixture
    def agent(self) -> FraudDisputeAgent:
        return FraudDisputeAgent()

    async def test_logs_processing_start(
        self, agent: FraudDisputeAgent, caplog: pytest.LogCaptureFixture
    ) -> None:
        case = _make_fraud_case()
        with caplog.at_level(logging.INFO, logger="agent.fraud_agent"):
            await agent.process(case)

        start_msgs = [r for r in caplog.records if "Processing fraud dispute" in r.message]
        assert len(start_msgs) == 1
        msg = start_msgs[0].message
        assert case.case_id in msg
        assert "10.4" in msg
        assert "TXN-FRAUD-INST-001" in msg
        assert "500.0" in msg

    async def test_logs_llm_result(
        self, agent: FraudDisputeAgent, caplog: pytest.LogCaptureFixture
    ) -> None:
        case = _make_fraud_case()
        with caplog.at_level(logging.INFO, logger="agent.fraud_agent"):
            await agent.process(case)

        result_msgs = [r for r in caplog.records if "LLM evaluation result" in r.message]
        assert len(result_msgs) == 1
        msg = result_msgs[0].message
        assert "is_valid=" in msg
        assert "resolution=" in msg
        assert "confidence=" in msg
        assert "rule_citations=" in msg

    async def test_logs_final_decision(
        self, agent: FraudDisputeAgent, caplog: pytest.LogCaptureFixture
    ) -> None:
        case = _make_fraud_case()
        with caplog.at_level(logging.INFO, logger="agent.fraud_agent"):
            await agent.process(case)

        decision_msgs = [r for r in caplog.records if "Final decision" in r.message]
        assert len(decision_msgs) == 1
        msg = decision_msgs[0].message
        assert "resolution=" in msg
        assert "confidence=" in msg
        assert "requires_human_review=" in msg
        assert "decided_by=" in msg


class TestFraudAgentInstrumentationInvalidDispute:
    """Test that an invalid dispute logs a WARNING."""

    @pytest.fixture
    def agent(self) -> FraudDisputeAgent:
        return FraudDisputeAgent()

    async def test_invalid_dispute_logs_warning(
        self, agent: FraudDisputeAgent, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Chip-initiated 10.1 is invalid — should log a WARNING."""
        case = _make_fraud_case(
            condition=DisputeCondition.EMV_COUNTERFEIT_FRAUD,
            fraud_type_code=FraudTypeCode.COUNTERFEIT,
            issuer_certification="Denial",
            environment=TransactionEnvironment.CARD_PRESENT,
            is_chip_initiated=True,
        )
        with caplog.at_level(logging.WARNING, logger="agent.fraud_agent"):
            await agent.process(case)

        warning_msgs = [
            r for r in caplog.records
            if r.levelno == logging.WARNING and "Dispute flagged as invalid" in r.message
        ]
        assert len(warning_msgs) == 1
        assert case.case_id in warning_msgs[0].message

    async def test_time_expired_logs_warning(
        self, agent: FraudDisputeAgent, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Filing after time limit → invalid → should log WARNING."""
        case = _make_fraud_case(
            dispute_filed_date=datetime(2026, 2, 16) + timedelta(days=200),
        )
        with caplog.at_level(logging.WARNING, logger="agent.fraud_agent"):
            await agent.process(case)

        warning_msgs = [
            r for r in caplog.records
            if r.levelno == logging.WARNING and "Dispute flagged as invalid" in r.message
        ]
        assert len(warning_msgs) == 1


class TestFraudAgentInstrumentationHumanEscalation:
    """Test that human escalation logs a WARNING."""

    @pytest.fixture
    def agent(self) -> FraudDisputeAgent:
        return FraudDisputeAgent()

    async def test_high_amount_escalation_logs_warning(
        self, agent: FraudDisputeAgent, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Dispute amount >$25k triggers threshold-based escalation WARNING."""
        case = _make_fraud_case(dispute_amount=30000.0)
        with caplog.at_level(logging.WARNING, logger="agent.fraud_agent"):
            await agent.process(case)

        escalation_msgs = [
            r for r in caplog.records
            if r.levelno == logging.WARNING and "Human escalation triggered" in r.message
        ]
        assert len(escalation_msgs) >= 1

    async def test_low_confidence_escalation_logs_warning(
        self, agent: FraudDisputeAgent, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Missing docs → low confidence (0.60) → threshold-based escalation WARNING."""
        case = _make_fraud_case(
            fraud_type_code=None,
            issuer_certification=None,
        )
        with caplog.at_level(logging.WARNING, logger="agent.fraud_agent"):
            await agent.process(case)

        escalation_msgs = [
            r for r in caplog.records
            if r.levelno == logging.WARNING and "Human escalation triggered" in r.message
        ]
        assert len(escalation_msgs) >= 1

    async def test_llm_triggered_escalation_logs_warning(
        self, agent: FraudDisputeAgent, caplog: pytest.LogCaptureFixture
    ) -> None:
        """When the LLM itself flags requires_human_review, log a WARNING."""
        case = _make_fraud_case(
            fraud_type_code=None,
            issuer_certification=None,
        )
        with caplog.at_level(logging.WARNING, logger="agent.fraud_agent"):
            result = await agent.process(case)

        assert result.decision is not None
        assert result.decision.requires_human_review is True
        escalation_msgs = [
            r for r in caplog.records
            if r.levelno == logging.WARNING and "Human escalation triggered by LLM" in r.message
        ]
        assert len(escalation_msgs) >= 1


class TestFraudAgentInstrumentationLLMError:
    """Test that LLM errors are caught and logged at ERROR level."""

    @pytest.fixture
    def agent(self) -> FraudDisputeAgent:
        return FraudDisputeAgent()

    async def test_llm_error_logged_and_reraised(
        self, agent: FraudDisputeAgent, caplog: pytest.LogCaptureFixture
    ) -> None:
        case = _make_fraud_case()
        with (
            patch.object(
                agent, "_evaluate_dispute_with_llm", side_effect=RuntimeError("LLM timeout")
            ),
            caplog.at_level(logging.ERROR, logger="agent.fraud_agent"),
            pytest.raises(RuntimeError, match="LLM timeout"),
        ):
            await agent.process(case)

        error_msgs = [
            r for r in caplog.records
            if r.levelno == logging.ERROR and "LLM evaluation failed" in r.message
        ]
        assert len(error_msgs) == 1
        assert case.case_id in error_msgs[0].message


class TestFraudAgentInstrumentationTiming:
    """Test that LLM call timing is logged."""

    @pytest.fixture
    def agent(self) -> FraudDisputeAgent:
        return FraudDisputeAgent()

    async def test_timing_logged(
        self, agent: FraudDisputeAgent, caplog: pytest.LogCaptureFixture
    ) -> None:
        case = _make_fraud_case()
        with caplog.at_level(logging.INFO, logger="agent.fraud_agent"):
            await agent.process(case)

        timing_msgs = [r for r in caplog.records if "LLM call completed in" in r.message]
        assert len(timing_msgs) == 1
        assert "ms" in timing_msgs[0].message
