"""Tests for Processing Errors Agent (Category 12) instrumentation.

Verifies that structured logging and observability are correctly added
to the ProcessingErrorsAgent.process() method.
"""

import logging
from datetime import date, datetime
from unittest.mock import patch

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
    DisputeResolution,
    Region,
    TransactionEnvironment,
)


def _make_case(
    condition: DisputeCondition | None = None,
    dispute_filed_date: datetime | None = None,
    dispute_amount: float | None = None,
    dispute_currency: str | None = None,
    statement: str | None = None,
    evidence: list[DisputeEvidence] | None = None,
    **txn_overrides: object,
) -> DisputeCase:
    """Create a DisputeCase for testing."""
    txn_defaults = {
        "transaction_id": "TXN-PROC-001",
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
        evidence=evidence or [],
        stage=DisputeLifecycleStage.PROCESSING,
        dispute_filed_date=dispute_filed_date,
        dispute_amount=dispute_amount,
        dispute_currency=dispute_currency,
    )


@pytest.fixture
def agent() -> ProcessingErrorsAgent:
    return ProcessingErrorsAgent()


class TestProcessingStartLog:
    """Test that processing a valid case logs start, LLM result, and final decision."""

    async def test_logs_start_llm_result_and_decision(
        self, agent: ProcessingErrorsAgent, caplog: pytest.LogCaptureFixture
    ) -> None:
        case = _make_case(
            condition=DisputeCondition.DUPLICATE_PROCESSING,
            dispute_filed_date=datetime(2026, 2, 17),
        )
        with caplog.at_level(logging.INFO, logger="agent.processing_errors_agent"):
            result = await agent.process(case)

        messages = [r.message for r in caplog.records]

        # Start log
        start_msgs = [m for m in messages if "Processing errors evaluation started" in m]
        assert len(start_msgs) == 1
        assert "case_id=" in start_msgs[0]
        assert "condition=12.6" in start_msgs[0]
        assert "transaction_id=TXN-PROC-001" in start_msgs[0]
        assert "amount=500.0" in start_msgs[0]
        assert "currency=USD" in start_msgs[0]

        # LLM result log
        llm_msgs = [m for m in messages if "LLM evaluation result" in m]
        assert len(llm_msgs) == 1
        assert "is_valid=" in llm_msgs[0]
        assert "resolution=" in llm_msgs[0]
        assert "confidence=" in llm_msgs[0]
        assert "rule_citations_count=" in llm_msgs[0]

        # Final decision log
        decision_msgs = [m for m in messages if "Final decision" in m]
        assert len(decision_msgs) == 1
        assert "resolution=" in decision_msgs[0]
        assert "confidence=" in decision_msgs[0]
        assert "requires_human_review=" in decision_msgs[0]
        assert "decided_by=" in decision_msgs[0]

        assert result.decision is not None
        assert result.decision.resolution == DisputeResolution.ISSUER_WIN


class TestInvalidDisputeWarning:
    """Test that an invalid dispute logs a WARNING."""

    async def test_invalid_dispute_logs_warning(
        self, agent: ProcessingErrorsAgent, caplog: pytest.LogCaptureFixture
    ) -> None:
        # 12.5 with no dispute_amount triggers invalid in the mock
        case = _make_case(
            condition=DisputeCondition.INCORRECT_AMOUNT,
            dispute_filed_date=datetime(2026, 2, 17),
            dispute_amount=None,
        )
        with caplog.at_level(logging.DEBUG, logger="agent.processing_errors_agent"):
            result = await agent.process(case)

        warning_records = [
            r for r in caplog.records
            if r.levelno == logging.WARNING and "Dispute flagged as invalid" in r.message
        ]
        assert len(warning_records) == 1
        assert "case_id=" in warning_records[0].message
        assert "reason=" in warning_records[0].message

        assert result.decision is not None
        assert result.decision.resolution == DisputeResolution.INVALID_DISPUTE


class TestHumanEscalationWarning:
    """Test that human escalation logs a WARNING."""

    async def test_human_escalation_logs_warning(
        self, agent: ProcessingErrorsAgent, caplog: pytest.LogCaptureFixture
    ) -> None:
        # High-value dispute triggers _should_escalate_to_human
        case = _make_case(
            condition=DisputeCondition.DUPLICATE_PROCESSING,
            dispute_filed_date=datetime(2026, 2, 17),
            dispute_amount=30000.0,
        )
        with caplog.at_level(logging.DEBUG, logger="agent.processing_errors_agent"):
            result = await agent.process(case)

        warning_records = [
            r for r in caplog.records
            if r.levelno == logging.WARNING and "Human escalation triggered" in r.message
        ]
        assert len(warning_records) == 1
        assert "case_id=" in warning_records[0].message
        assert "reason=" in warning_records[0].message

        assert result.decision is not None
        assert result.decision.requires_human_review is True
        assert result.stage == DisputeLifecycleStage.HUMAN_REVIEW


class TestLLMErrorLogging:
    """Test that LLM errors are caught and logged at ERROR level."""

    async def test_llm_error_logged_and_reraised(
        self, agent: ProcessingErrorsAgent, caplog: pytest.LogCaptureFixture
    ) -> None:
        case = _make_case(
            condition=DisputeCondition.DUPLICATE_PROCESSING,
            dispute_filed_date=datetime(2026, 2, 17),
        )
        with (
            patch.object(
                agent, "_evaluate_dispute_with_llm", side_effect=RuntimeError("LLM service unavailable")
            ),
            caplog.at_level(logging.DEBUG, logger="agent.processing_errors_agent"),
            pytest.raises(RuntimeError, match="LLM service unavailable"),
        ):
            await agent.process(case)

        error_records = [
            r for r in caplog.records
            if r.levelno == logging.ERROR and "LLM evaluation failed" in r.message
        ]
        assert len(error_records) == 1
        assert "case_id=" in error_records[0].message
        assert "condition=" in error_records[0].message


class TestTimingLogged:
    """Test that timing of the LLM call is logged."""

    async def test_timing_logged(
        self, agent: ProcessingErrorsAgent, caplog: pytest.LogCaptureFixture
    ) -> None:
        case = _make_case(
            condition=DisputeCondition.DUPLICATE_PROCESSING,
            dispute_filed_date=datetime(2026, 2, 17),
        )
        with caplog.at_level(logging.INFO, logger="agent.processing_errors_agent"):
            await agent.process(case)

        timing_records = [
            r for r in caplog.records if "elapsed_ms=" in r.message
        ]
        assert len(timing_records) == 1
        assert "LLM call completed" in timing_records[0].message
