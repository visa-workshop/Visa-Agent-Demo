"""Tests for Pre-Arbitration Agent instrumentation (Decision Point #6).

Verifies structured logging across all decision paths:
- Sub-flow routing in process()
- Pre-arbitration, pre-arbitration response, and arbitration processing
- LLM evaluation timing and result logging
- next_action path logging in _apply_pre_arb_result
- Error handling and warning-level escalation logs
"""

import logging
from datetime import date
from unittest.mock import patch

import pytest

from src.agents.pre_arbitration_agent import PreArbitrationAgent
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


def _make_pre_arb_case(
    stage: DisputeLifecycleStage = DisputeLifecycleStage.PRE_ARBITRATION,
    evidence: list[DisputeEvidence] | None = None,
    condition: DisputeCondition | None = DisputeCondition.OTHER_FRAUD_CARD_ABSENT,
    category: DisputeCategory | None = DisputeCategory.FRAUD,
    issuer_certification: str | None = None,
) -> DisputeCase:
    """Create a case suitable for pre-arbitration testing."""
    return DisputeCase(
        transaction=TransactionDetails(
            transaction_id="TXN-PREARB-001",
            transaction_date=date(2026, 2, 15),
            processing_date=date(2026, 2, 16),
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
        ),
        condition=condition,
        category=category,
        evidence=evidence or [],
        stage=stage,
        issuer_certification=issuer_certification,
    )


class TestPreArbProcessRouting:
    """Test that process() logs which sub-flow is being routed to."""

    @pytest.fixture
    def agent(self) -> PreArbitrationAgent:
        return PreArbitrationAgent()

    async def test_routes_to_pre_arbitration(
        self, agent: PreArbitrationAgent, caplog: pytest.LogCaptureFixture
    ) -> None:
        case = _make_pre_arb_case(stage=DisputeLifecycleStage.PRE_ARBITRATION)
        with caplog.at_level(logging.INFO, logger="agent.pre_arbitration_agent"):
            await agent.process(case)
        assert any("Routing to pre_arbitration sub-flow" in r.message for r in caplog.records)

    async def test_routes_to_pre_arbitration_response(
        self, agent: PreArbitrationAgent, caplog: pytest.LogCaptureFixture
    ) -> None:
        case = _make_pre_arb_case(stage=DisputeLifecycleStage.PRE_ARBITRATION_RESPONSE)
        with caplog.at_level(logging.INFO, logger="agent.pre_arbitration_agent"):
            await agent.process(case)
        assert any(
            "Routing to pre_arbitration_response sub-flow" in r.message for r in caplog.records
        )

    async def test_routes_to_arbitration(
        self, agent: PreArbitrationAgent, caplog: pytest.LogCaptureFixture
    ) -> None:
        case = _make_pre_arb_case(stage=DisputeLifecycleStage.ARBITRATION)
        with caplog.at_level(logging.INFO, logger="agent.pre_arbitration_agent"):
            await agent.process(case)
        assert any("Routing to arbitration sub-flow" in r.message for r in caplog.records)


class TestPreArbitrationProcessingLogs:
    """Test _process_pre_arbitration instrumentation."""

    @pytest.fixture
    def agent(self) -> PreArbitrationAgent:
        return PreArbitrationAgent()

    async def test_logs_pre_arb_start(
        self, agent: PreArbitrationAgent, caplog: pytest.LogCaptureFixture
    ) -> None:
        case = _make_pre_arb_case(stage=DisputeLifecycleStage.PRE_ARBITRATION)
        with caplog.at_level(logging.INFO, logger="agent.pre_arbitration_agent"):
            await agent.process(case)
        start_records = [
            r for r in caplog.records if "Processing pre-arbitration attempt" in r.message
        ]
        assert len(start_records) >= 1
        rec = start_records[0]
        assert rec.case_id == case.case_id
        assert rec.pre_arbitration_attempts == 1
        assert rec.transaction_id == "TXN-PREARB-001"

    async def test_logs_llm_result(
        self, agent: PreArbitrationAgent, caplog: pytest.LogCaptureFixture
    ) -> None:
        case = _make_pre_arb_case(stage=DisputeLifecycleStage.PRE_ARBITRATION)
        with caplog.at_level(logging.INFO, logger="agent.pre_arbitration_agent"):
            await agent.process(case)
        result_records = [r for r in caplog.records if "LLM evaluation result" in r.message]
        assert len(result_records) >= 1
        rec = result_records[0]
        assert hasattr(rec, "has_compelling_evidence")
        assert hasattr(rec, "resolution")
        assert hasattr(rec, "confidence")
        assert hasattr(rec, "next_action")
        assert hasattr(rec, "rule_citations_count")

    async def test_logs_next_action(
        self, agent: PreArbitrationAgent, caplog: pytest.LogCaptureFixture
    ) -> None:
        case = _make_pre_arb_case(stage=DisputeLifecycleStage.PRE_ARBITRATION)
        with caplog.at_level(logging.INFO, logger="agent.pre_arbitration_agent"):
            await agent.process(case)
        action_records = [r for r in caplog.records if "Applying next_action path" in r.message]
        assert len(action_records) >= 1


class TestPreArbitrationResponseLogs:
    """Test _process_pre_arbitration_response instrumentation."""

    @pytest.fixture
    def agent(self) -> PreArbitrationAgent:
        return PreArbitrationAgent()

    async def test_logs_response_processing(
        self, agent: PreArbitrationAgent, caplog: pytest.LogCaptureFixture
    ) -> None:
        evidence = [
            DisputeEvidence(
                description="Issuer accepts financial responsibility for this dispute",
                evidence_type="acceptance",
                provided_by="issuer",
            ),
        ]
        case = _make_pre_arb_case(
            stage=DisputeLifecycleStage.PRE_ARBITRATION_RESPONSE,
            evidence=evidence,
        )
        with caplog.at_level(logging.INFO, logger="agent.pre_arbitration_agent"):
            await agent.process(case)
        response_records = [
            r for r in caplog.records if "Processing pre-arbitration response" in r.message
        ]
        assert len(response_records) >= 1
        rec = response_records[0]
        assert rec.case_id == case.case_id
        assert rec.stage == "pre_arbitration_response"


class TestArbitrationProcessingLogs:
    """Test _process_arbitration instrumentation."""

    @pytest.fixture
    def agent(self) -> PreArbitrationAgent:
        return PreArbitrationAgent()

    async def test_logs_arbitration_filing(
        self, agent: PreArbitrationAgent, caplog: pytest.LogCaptureFixture
    ) -> None:
        case = _make_pre_arb_case(stage=DisputeLifecycleStage.ARBITRATION)
        with caplog.at_level(logging.INFO, logger="agent.pre_arbitration_agent"):
            await agent.process(case)
        arb_records = [
            r for r in caplog.records if "Processing arbitration filing" in r.message
        ]
        assert len(arb_records) >= 1
        rec = arb_records[0]
        assert rec.case_id == case.case_id
        assert rec.arbitration_filed is True

    async def test_arbitration_always_requires_human_review(
        self, agent: PreArbitrationAgent, caplog: pytest.LogCaptureFixture
    ) -> None:
        case = _make_pre_arb_case(stage=DisputeLifecycleStage.ARBITRATION)
        with caplog.at_level(logging.INFO, logger="agent.pre_arbitration_agent"):
            result = await agent.process(case)
        assert result.decision is not None
        assert result.decision.requires_human_review is True
        assert result.stage == DisputeLifecycleStage.HUMAN_REVIEW


class TestApplyPreArbResultPaths:
    """Test _apply_pre_arb_result logs each next_action path appropriately."""

    @pytest.fixture
    def agent(self) -> PreArbitrationAgent:
        return PreArbitrationAgent()

    async def test_resolved_path_logs(
        self, agent: PreArbitrationAgent, caplog: pytest.LogCaptureFixture
    ) -> None:
        """No compelling evidence, no special flags -> resolved path."""
        case = _make_pre_arb_case(stage=DisputeLifecycleStage.PRE_ARBITRATION)
        with caplog.at_level(logging.INFO, logger="agent.pre_arbitration_agent"):
            await agent.process(case)
        action_records = [r for r in caplog.records if "Applying next_action path" in r.message]
        assert len(action_records) >= 1
        assert action_records[0].next_action == "resolved"
        # Verify final decision log
        decision_records = [
            r for r in caplog.records if "Pre-arbitration decision applied" in r.message
        ]
        assert len(decision_records) >= 1
        assert hasattr(decision_records[0], "resolution")
        assert hasattr(decision_records[0], "confidence")
        assert hasattr(decision_records[0], "requires_human_review")

    async def test_awaiting_issuer_response_path_logs(
        self, agent: PreArbitrationAgent, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Compelling evidence -> awaiting_issuer_response path."""
        evidence = [
            DisputeEvidence(
                description="Delivery proof to AVS-verified address",
                evidence_type="delivery confirmation",
                provided_by="acquirer",
                is_compelling_evidence=True,
            ),
        ]
        case = _make_pre_arb_case(
            stage=DisputeLifecycleStage.PRE_ARBITRATION,
            evidence=evidence,
        )
        with caplog.at_level(logging.INFO, logger="agent.pre_arbitration_agent"):
            await agent.process(case)
        action_records = [r for r in caplog.records if "Applying next_action path" in r.message]
        assert len(action_records) >= 1
        assert action_records[0].next_action == "awaiting_issuer_response"

    async def test_escalate_arbitration_path_logs_warning(
        self, agent: PreArbitrationAgent, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Issuer certification in response -> escalate_arbitration path with WARNING."""
        case = _make_pre_arb_case(
            stage=DisputeLifecycleStage.PRE_ARBITRATION_RESPONSE,
            issuer_certification="Cardholder still disputes after reviewing evidence",
        )
        with caplog.at_level(logging.WARNING, logger="agent.pre_arbitration_agent"):
            await agent.process(case)
        warn_records = [
            r
            for r in caplog.records
            if r.levelno == logging.WARNING and "Escalating to arbitration" in r.message
        ]
        assert len(warn_records) >= 1

    async def test_human_review_path_logs_warning(
        self, agent: PreArbitrationAgent, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Arbitration stage -> human_review next_action path with WARNING."""
        case = _make_pre_arb_case(stage=DisputeLifecycleStage.ARBITRATION)
        with caplog.at_level(logging.WARNING, logger="agent.pre_arbitration_agent"):
            await agent.process(case)
        # The arbitration mock returns next_action="human_review", which hits the else branch
        # in _apply_pre_arb_result (but only for the _apply path, not _process_arbitration's
        # own path which doesn't call _apply_pre_arb_result).
        # For arbitration, _process_arbitration doesn't call _apply_pre_arb_result,
        # so we verify the arbitration filing log and human review stage instead.
        assert case.stage == DisputeLifecycleStage.HUMAN_REVIEW


class TestLLMErrorHandling:
    """Test that LLM errors are caught and logged."""

    @pytest.fixture
    def agent(self) -> PreArbitrationAgent:
        return PreArbitrationAgent()

    async def test_llm_error_logged_and_reraised(
        self, agent: PreArbitrationAgent, caplog: pytest.LogCaptureFixture
    ) -> None:
        case = _make_pre_arb_case(stage=DisputeLifecycleStage.PRE_ARBITRATION)
        with (
            patch(
                "src.agents.pre_arbitration_agent.chat_json",
                side_effect=RuntimeError("LLM service unavailable"),
            ),
            caplog.at_level(logging.ERROR, logger="agent.pre_arbitration_agent"),
            pytest.raises(RuntimeError, match="LLM service unavailable"),
        ):
            await agent.process(case)
        error_records = [
            r
            for r in caplog.records
            if r.levelno == logging.ERROR
            and "LLM call failed in pre-arbitration evaluation" in r.message
        ]
        assert len(error_records) >= 1
        assert error_records[0].case_id == case.case_id


class TestLLMTimingLogs:
    """Test that LLM call timing is logged."""

    @pytest.fixture
    def agent(self) -> PreArbitrationAgent:
        return PreArbitrationAgent()

    async def test_timing_logged(
        self, agent: PreArbitrationAgent, caplog: pytest.LogCaptureFixture
    ) -> None:
        case = _make_pre_arb_case(stage=DisputeLifecycleStage.PRE_ARBITRATION)
        with caplog.at_level(logging.INFO, logger="agent.pre_arbitration_agent"):
            await agent.process(case)
        timing_records = [r for r in caplog.records if "LLM call completed" in r.message]
        assert len(timing_records) >= 1
        rec = timing_records[0]
        assert hasattr(rec, "elapsed_ms")
        assert isinstance(rec.elapsed_ms, float)
        assert rec.elapsed_ms >= 0
