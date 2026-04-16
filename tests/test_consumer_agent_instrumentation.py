"""Tests for Consumer Disputes Agent instrumentation (AI Decision Point #5).

Verifies structured logging and observability added to the
ConsumerDisputesAgent.process() method.
"""

import logging
from datetime import date, datetime, timedelta
from unittest.mock import patch

import pytest

from src.agents.consumer_disputes_agent import ConsumerDisputesAgent
from src.models.dispute import (
    CardholderInfo,
    DisputeCase,
    DisputeEvidence,
    TransactionDetails,
)
from src.models.enums import (
    DisputeCondition,
    DisputeLifecycleStage,
    DisputeResolution,
    Region,
    TransactionEnvironment,
)


def _make_case(
    condition: DisputeCondition | None = None,
    statement: str | None = None,
    evidence: list[DisputeEvidence] | None = None,
    stage: DisputeLifecycleStage = DisputeLifecycleStage.PROCESSING,
    dispute_filed_date: datetime | None = None,
    dispute_amount: float | None = None,
    **txn_overrides: object,
) -> DisputeCase:
    txn_defaults = {
        "transaction_id": "TXN-CONSUMER-001",
        "transaction_date": date(2026, 2, 15),
        "processing_date": date(2026, 2, 16),
        "amount": 250.0,
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
        evidence=evidence or [],
        stage=stage,
        dispute_filed_date=dispute_filed_date,
        dispute_amount=dispute_amount,
    )


class TestConsumerAgentInstrumentationValidDispute:
    """Test that a valid consumer dispute logs start, LLM result, and final decision."""

    @pytest.fixture
    def agent(self) -> ConsumerDisputesAgent:
        return ConsumerDisputesAgent()

    async def test_logs_processing_start(
        self, agent: ConsumerDisputesAgent, caplog: pytest.LogCaptureFixture
    ) -> None:
        case = _make_case(
            condition=DisputeCondition.MERCHANDISE_NOT_RECEIVED,
            statement="I never received my order",
            dispute_filed_date=datetime(2026, 2, 17),
        )
        with caplog.at_level(logging.INFO, logger="agent.consumer_disputes_agent"):
            await agent.process(case)

        start_msgs = [r for r in caplog.records if "Processing consumer dispute" in r.message]
        assert len(start_msgs) >= 1
        msg = start_msgs[0].message
        assert case.case_id in msg
        assert "13.1" in msg
        assert "TXN-CONSUMER-001" in msg
        assert "250.0" in msg
        assert "TestMerchant" in msg

    async def test_logs_llm_result(
        self, agent: ConsumerDisputesAgent, caplog: pytest.LogCaptureFixture
    ) -> None:
        case = _make_case(
            condition=DisputeCondition.MERCHANDISE_NOT_RECEIVED,
            statement="I never received my order",
            dispute_filed_date=datetime(2026, 2, 17),
        )
        with caplog.at_level(logging.INFO, logger="agent.consumer_disputes_agent"):
            await agent.process(case)

        llm_msgs = [r for r in caplog.records if "LLM result" in r.message]
        assert len(llm_msgs) >= 1
        msg = llm_msgs[0].message
        assert "is_valid=" in msg
        assert "resolution=" in msg
        assert "confidence=" in msg
        assert "rule_citations=" in msg

    async def test_logs_final_decision(
        self, agent: ConsumerDisputesAgent, caplog: pytest.LogCaptureFixture
    ) -> None:
        case = _make_case(
            condition=DisputeCondition.MERCHANDISE_NOT_RECEIVED,
            statement="I never received my order",
            dispute_filed_date=datetime(2026, 2, 17),
        )
        with caplog.at_level(logging.INFO, logger="agent.consumer_disputes_agent"):
            await agent.process(case)

        decision_msgs = [r for r in caplog.records if "Final decision" in r.message]
        assert len(decision_msgs) >= 1
        msg = decision_msgs[0].message
        assert "resolution=" in msg
        assert "confidence=" in msg
        assert "requires_human_review=" in msg
        assert "decided_by=" in msg


class TestConsumerAgentInstrumentationInvalidDispute:
    """Test that an invalid dispute logs a WARNING."""

    @pytest.fixture
    def agent(self) -> ConsumerDisputesAgent:
        return ConsumerDisputesAgent()

    async def test_invalid_dispute_logs_warning(
        self, agent: ConsumerDisputesAgent, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Filing outside time limit triggers invalid dispute WARNING."""
        case = _make_case(
            condition=DisputeCondition.MERCHANDISE_NOT_RECEIVED,
            statement="I never received my order",
            dispute_filed_date=datetime(2026, 2, 16) + timedelta(days=200),
        )
        with caplog.at_level(logging.WARNING, logger="agent.consumer_disputes_agent"):
            result = await agent.process(case)

        assert result.decision is not None
        assert result.decision.resolution == DisputeResolution.INVALID_DISPUTE

        warning_msgs = [
            r
            for r in caplog.records
            if r.levelno == logging.WARNING and "Dispute flagged as invalid" in r.message
        ]
        assert len(warning_msgs) >= 1
        assert case.case_id in warning_msgs[0].message


class TestConsumerAgentInstrumentationHumanEscalation:
    """Test that human escalation logs a WARNING."""

    @pytest.fixture
    def agent(self) -> ConsumerDisputesAgent:
        return ConsumerDisputesAgent()

    async def test_human_escalation_logs_warning(
        self, agent: ConsumerDisputesAgent, caplog: pytest.LogCaptureFixture
    ) -> None:
        """High-value dispute (>$25k) triggers human escalation WARNING."""
        case = _make_case(
            condition=DisputeCondition.MERCHANDISE_NOT_RECEIVED,
            statement="I never received my order",
            dispute_filed_date=datetime(2026, 2, 17),
            dispute_amount=30000.0,
        )
        with caplog.at_level(logging.WARNING, logger="agent.consumer_disputes_agent"):
            result = await agent.process(case)

        assert result.decision is not None
        assert result.decision.requires_human_review is True

        warning_msgs = [
            r
            for r in caplog.records
            if r.levelno == logging.WARNING and "Human escalation triggered" in r.message
        ]
        assert len(warning_msgs) >= 1
        assert case.case_id in warning_msgs[0].message


class TestConsumerAgentInstrumentationLLMError:
    """Test that LLM errors are caught and logged at ERROR level."""

    @pytest.fixture
    def agent(self) -> ConsumerDisputesAgent:
        return ConsumerDisputesAgent()

    async def test_llm_error_logged_and_reraised(
        self, agent: ConsumerDisputesAgent, caplog: pytest.LogCaptureFixture
    ) -> None:
        case = _make_case(
            condition=DisputeCondition.MERCHANDISE_NOT_RECEIVED,
            statement="I never received my order",
            dispute_filed_date=datetime(2026, 2, 17),
        )
        with (
            patch.object(
                agent,
                "_evaluate_dispute_with_llm",
                side_effect=RuntimeError("OpenAI API timeout"),
            ),
            caplog.at_level(logging.ERROR, logger="agent.consumer_disputes_agent"),
            pytest.raises(RuntimeError, match="OpenAI API timeout"),
        ):
            await agent.process(case)

        error_msgs = [
            r
            for r in caplog.records
            if r.levelno == logging.ERROR and "LLM evaluation failed" in r.message
        ]
        assert len(error_msgs) >= 1
        assert case.case_id in error_msgs[0].message


class TestConsumerAgentInstrumentationTiming:
    """Test that LLM call timing is logged."""

    @pytest.fixture
    def agent(self) -> ConsumerDisputesAgent:
        return ConsumerDisputesAgent()

    async def test_timing_logged(
        self, agent: ConsumerDisputesAgent, caplog: pytest.LogCaptureFixture
    ) -> None:
        case = _make_case(
            condition=DisputeCondition.MERCHANDISE_NOT_RECEIVED,
            statement="I never received my order",
            dispute_filed_date=datetime(2026, 2, 17),
        )
        with caplog.at_level(logging.INFO, logger="agent.consumer_disputes_agent"):
            await agent.process(case)

        timing_msgs = [r for r in caplog.records if "LLM call completed in" in r.message]
        assert len(timing_msgs) >= 1
        assert "ms" in timing_msgs[0].message
        assert case.case_id in timing_msgs[0].message
