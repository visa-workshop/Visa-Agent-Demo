"""Tests for authorization agent instrumentation (structured logging & observability).

Verifies that the AuthorizationDisputeAgent.process() method emits the
expected log messages at the correct levels for various scenarios.
"""

import logging
from datetime import date, datetime
from unittest.mock import patch

import pytest

from src.agents.authorization_agent import AuthorizationDisputeAgent
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


def _make_auth_case(
    condition: DisputeCondition = DisputeCondition.DECLINED_AUTHORIZATION,
    authorization_code: str | None = None,
    authorization_response_code: str | None = "14",
    evidence: list[DisputeEvidence] | None = None,
    dispute_filed_date: datetime | None = None,
    dispute_amount: float | None = None,
    **txn_overrides: object,
) -> DisputeCase:
    """Create a DisputeCase configured for authorization agent tests."""
    txn_defaults = {
        "transaction_id": "TXN-AUTH-INST-001",
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
        "authorization_code": authorization_code,
        "authorization_response_code": authorization_response_code,
    }
    txn_defaults.update(txn_overrides)

    return DisputeCase(
        transaction=TransactionDetails(**txn_defaults),
        cardholder=CardholderInfo(
            cardholder_name="Test User",
            partial_payment_credential="****1234",
            cardholder_statement="Authorization was declined",
        ),
        condition=condition,
        evidence=evidence or [],
        stage=DisputeLifecycleStage.PROCESSING,
        dispute_filed_date=dispute_filed_date or datetime(2026, 2, 17),
        dispute_amount=dispute_amount,
    )


class TestAuthAgentInstrumentationValidCase:
    """Test that processing a valid authorization case logs start, LLM result, and final decision."""

    @pytest.fixture
    def agent(self) -> AuthorizationDisputeAgent:
        return AuthorizationDisputeAgent()

    async def test_logs_processing_start(
        self, agent: AuthorizationDisputeAgent, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Processing start is logged at INFO with case details."""
        case = _make_auth_case(
            condition=DisputeCondition.DECLINED_AUTHORIZATION,
            authorization_response_code="14",
        )
        with caplog.at_level(logging.INFO, logger="agent.authorization_agent"):
            await agent.process(case)

        start_messages = [
            r for r in caplog.records
            if "Processing authorization dispute" in r.message
        ]
        assert len(start_messages) == 1
        record = start_messages[0]
        assert record.levelno == logging.INFO
        assert case.case_id in record.message
        assert "TXN-AUTH-INST-001" in record.message
        assert "500.0" in record.message

    async def test_logs_llm_result(
        self, agent: AuthorizationDisputeAgent, caplog: pytest.LogCaptureFixture
    ) -> None:
        """LLM evaluation result is logged at INFO with key fields."""
        case = _make_auth_case(
            condition=DisputeCondition.DECLINED_AUTHORIZATION,
            authorization_response_code="14",
        )
        with caplog.at_level(logging.INFO, logger="agent.authorization_agent"):
            await agent.process(case)

        llm_result_messages = [
            r for r in caplog.records if "LLM result" in r.message
        ]
        assert len(llm_result_messages) == 1
        record = llm_result_messages[0]
        assert record.levelno == logging.INFO
        assert "is_valid=" in record.message
        assert "resolution=" in record.message
        assert "confidence=" in record.message
        assert "rule_citations=" in record.message

    async def test_logs_final_decision(
        self, agent: AuthorizationDisputeAgent, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Final decision is logged at INFO with resolution, confidence, human review, decided_by."""
        case = _make_auth_case(
            condition=DisputeCondition.DECLINED_AUTHORIZATION,
            authorization_response_code="14",
        )
        with caplog.at_level(logging.INFO, logger="agent.authorization_agent"):
            await agent.process(case)

        final_messages = [
            r for r in caplog.records if "Final decision" in r.message
        ]
        assert len(final_messages) == 1
        record = final_messages[0]
        assert record.levelno == logging.INFO
        assert "resolution=" in record.message
        assert "confidence=" in record.message
        assert "requires_human_review=" in record.message
        assert "decided_by=" in record.message


class TestAuthAgentInstrumentationInvalidDispute:
    """Test that an invalid dispute logs a WARNING."""

    @pytest.fixture
    def agent(self) -> AuthorizationDisputeAgent:
        return AuthorizationDisputeAgent()

    async def test_invalid_dispute_logs_warning(
        self, agent: AuthorizationDisputeAgent, caplog: pytest.LogCaptureFixture
    ) -> None:
        """When LLM flags dispute as invalid, a WARNING is logged."""
        # 11.2 with approved response code (starts with '0') -> invalid
        case = _make_auth_case(
            condition=DisputeCondition.DECLINED_AUTHORIZATION,
            authorization_response_code="00",
        )
        with caplog.at_level(logging.WARNING, logger="agent.authorization_agent"):
            result = await agent.process(case)

        assert result.decision is not None
        assert result.decision.resolution == DisputeResolution.INVALID_DISPUTE

        invalid_warnings = [
            r for r in caplog.records
            if "Dispute flagged as invalid" in r.message
        ]
        assert len(invalid_warnings) == 1
        record = invalid_warnings[0]
        assert record.levelno == logging.WARNING
        assert case.case_id in record.message


class TestAuthAgentInstrumentationHumanEscalation:
    """Test that human escalation logs a WARNING."""

    @pytest.fixture
    def agent(self) -> AuthorizationDisputeAgent:
        return AuthorizationDisputeAgent()

    async def test_human_escalation_logs_warning(
        self, agent: AuthorizationDisputeAgent, caplog: pytest.LogCaptureFixture
    ) -> None:
        """When dispute is escalated to human review, a WARNING is logged."""
        # High-value dispute (>$25k) triggers escalation
        case = _make_auth_case(
            condition=DisputeCondition.DECLINED_AUTHORIZATION,
            authorization_response_code="14",
            dispute_amount=30000.0,
        )
        with caplog.at_level(logging.WARNING, logger="agent.authorization_agent"):
            result = await agent.process(case)

        assert result.decision is not None
        assert result.decision.requires_human_review is True

        escalation_warnings = [
            r for r in caplog.records
            if "Human escalation triggered" in r.message
        ]
        assert len(escalation_warnings) == 1
        record = escalation_warnings[0]
        assert record.levelno == logging.WARNING
        assert case.case_id in record.message


class TestAuthAgentInstrumentationLLMError:
    """Test that LLM errors are caught and logged at ERROR level."""

    @pytest.fixture
    def agent(self) -> AuthorizationDisputeAgent:
        return AuthorizationDisputeAgent()

    async def test_llm_error_logged_and_reraised(
        self, agent: AuthorizationDisputeAgent, caplog: pytest.LogCaptureFixture
    ) -> None:
        """When the LLM call raises, the error is logged at ERROR and re-raised."""
        case = _make_auth_case(
            condition=DisputeCondition.DECLINED_AUTHORIZATION,
            authorization_response_code="14",
        )

        with (
            patch.object(
                agent, "_evaluate_dispute_with_llm", side_effect=RuntimeError("LLM service unavailable"),
            ),
            caplog.at_level(logging.ERROR, logger="agent.authorization_agent"),
            pytest.raises(RuntimeError, match="LLM service unavailable"),
        ):
            await agent.process(case)

        error_messages = [
            r for r in caplog.records
            if "LLM evaluation failed" in r.message
        ]
        assert len(error_messages) == 1
        record = error_messages[0]
        assert record.levelno == logging.ERROR
        assert case.case_id in record.message


class TestAuthAgentInstrumentationTiming:
    """Test that LLM call timing is logged."""

    @pytest.fixture
    def agent(self) -> AuthorizationDisputeAgent:
        return AuthorizationDisputeAgent()

    async def test_timing_logged(
        self, agent: AuthorizationDisputeAgent, caplog: pytest.LogCaptureFixture
    ) -> None:
        """LLM evaluation timing is logged at INFO in milliseconds."""
        case = _make_auth_case(
            condition=DisputeCondition.DECLINED_AUTHORIZATION,
            authorization_response_code="14",
        )
        with caplog.at_level(logging.INFO, logger="agent.authorization_agent"):
            await agent.process(case)

        timing_messages = [
            r for r in caplog.records
            if "LLM evaluation completed in" in r.message and "ms" in r.message
        ]
        assert len(timing_messages) == 1
        record = timing_messages[0]
        assert record.levelno == logging.INFO
        assert case.case_id in record.message
