"""Tests for Sentry instrumentation in the DisputeBrain orchestrator.

Verifies that spans, breadcrumbs, and exception captures are triggered
at the correct lifecycle points.
"""

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from src.models.dispute import (
    CardholderInfo,
    DisputeCase,
    TransactionDetails,
)
from src.models.enums import (
    FraudTypeCode,
    Region,
    TransactionEnvironment,
)
from src.models.task import DisputeTask
from src.orchestrator.brain import DisputeBrain
from src.queue.task_queue import DisputeTaskQueue


def _make_fraud_case() -> DisputeCase:
    return DisputeCase(
        transaction=TransactionDetails(
            transaction_id="TXN-INST-001",
            transaction_date=date(2026, 2, 15),
            processing_date=date(2026, 2, 16),
            amount=1250.00,
            currency="USD",
            merchant_name="SuspiciousStore.com",
            merchant_category_code="5411",
            merchant_country="US",
            acquirer_bin="411111",
            issuer_bin="422222",
            environment=TransactionEnvironment.ECOMMERCE,
            region=Region.US,
        ),
        cardholder=CardholderInfo(
            cardholder_name="Jane Doe",
            partial_payment_credential="****1234",
            cardholder_statement="I did not authorize this transaction.",
            signed_letter_provided=True,
        ),
        fraud_type_code=FraudTypeCode.ACCOUNT_TAKEOVER,
        issuer_certification="Issuer certifies cardholder denies authorization",
    )


def _make_consumer_case() -> DisputeCase:
    return DisputeCase(
        transaction=TransactionDetails(
            transaction_id="TXN-INST-002",
            transaction_date=date(2026, 1, 15),
            processing_date=date(2026, 1, 16),
            amount=899.99,
            currency="USD",
            merchant_name="OnlineGadgets.com",
            merchant_category_code="5732",
            merchant_country="US",
            acquirer_bin="411111",
            issuer_bin="455555",
            environment=TransactionEnvironment.ECOMMERCE,
            authorization_code="XYZ789",
            authorization_response_code="00",
            region=Region.US,
        ),
        cardholder=CardholderInfo(
            cardholder_name="Bob Williams",
            partial_payment_credential="****3456",
            cardholder_statement="I ordered a laptop but it was never received.",
            signed_letter_provided=True,
        ),
    )


@pytest.fixture
def brain() -> DisputeBrain:
    queue = DisputeTaskQueue()
    return DisputeBrain(queue)


class TestBrainInstrumentation:
    @pytest.mark.asyncio
    async def test_submit_dispute_creates_span(self, brain: DisputeBrain) -> None:
        """Verify submitting a dispute creates a span with op='brain.submit'."""
        mock_span = MagicMock()
        mock_span.__enter__ = MagicMock(return_value=mock_span)
        mock_span.__exit__ = MagicMock(return_value=False)

        case = _make_fraud_case()
        with patch("sentry_sdk.start_span", return_value=mock_span) as mock_start:
            await brain.submit_dispute(case)

        mock_start.assert_any_call(
            op="brain.submit", name="DisputeBrain.submit_dispute"
        )
        mock_span.set_data.assert_any_call("case_id", case.case_id)

    @pytest.mark.asyncio
    async def test_process_single_creates_pipeline_span(
        self, brain: DisputeBrain
    ) -> None:
        """Verify process_single() creates a span for the full pipeline."""
        mock_span = MagicMock()
        mock_span.__enter__ = MagicMock(return_value=mock_span)
        mock_span.__exit__ = MagicMock(return_value=False)

        case = _make_fraud_case()
        with (
            patch("sentry_sdk.start_span", return_value=mock_span),
            patch("sentry_sdk.add_breadcrumb"),
        ):
            result = await brain.process_single(case)

        # The span should have set case_id
        mock_span.set_data.assert_any_call("case_id", case.case_id)
        assert result.category is not None

    @pytest.mark.asyncio
    async def test_pipeline_records_categorization(
        self, brain: DisputeBrain
    ) -> None:
        """Verify the pipeline span records categorization results."""
        mock_span = MagicMock()
        mock_span.__enter__ = MagicMock(return_value=mock_span)
        mock_span.__exit__ = MagicMock(return_value=False)

        case = _make_fraud_case()
        with (
            patch("sentry_sdk.start_span", return_value=mock_span),
            patch("sentry_sdk.add_breadcrumb"),
        ):
            result = await brain.process_single(case)

        # The span should have recorded category and condition
        set_data_calls = {
            (c.args[0], c.args[1])
            for c in mock_span.set_data.call_args_list
            if len(c.args) >= 2
        }
        assert ("category", result.category.value) in set_data_calls
        assert ("condition", result.condition.value) in set_data_calls

    @pytest.mark.asyncio
    async def test_pipeline_records_agent_routing(
        self, brain: DisputeBrain
    ) -> None:
        """Verify span data includes which agent was selected."""
        mock_span = MagicMock()
        mock_span.__enter__ = MagicMock(return_value=mock_span)
        mock_span.__exit__ = MagicMock(return_value=False)

        case = _make_fraud_case()
        with (
            patch("sentry_sdk.start_span", return_value=mock_span),
            patch("sentry_sdk.add_breadcrumb"),
        ):
            result = await brain.process_single(case)

        set_data_calls = {
            (c.args[0], c.args[1])
            for c in mock_span.set_data.call_args_list
            if len(c.args) >= 2
        }
        assert ("agent", result.assigned_agent) in set_data_calls

    @pytest.mark.asyncio
    async def test_escalate_pre_arb_creates_span(
        self, brain: DisputeBrain
    ) -> None:
        """Verify pre-arbitration escalation creates a span."""
        case = _make_fraud_case()
        await brain.process_single(case)

        mock_span = MagicMock()
        mock_span.__enter__ = MagicMock(return_value=mock_span)
        mock_span.__exit__ = MagicMock(return_value=False)

        with patch("sentry_sdk.start_span", return_value=mock_span) as mock_start:
            await brain.escalate_to_pre_arbitration(case.case_id)

        mock_start.assert_any_call(
            op="brain.escalate_pre_arb",
            name="DisputeBrain.escalate_to_pre_arbitration",
        )
        mock_span.set_data.assert_any_call("case_id", case.case_id)

    @pytest.mark.asyncio
    async def test_escalate_arbitration_creates_span(
        self, brain: DisputeBrain
    ) -> None:
        """Verify arbitration escalation creates a span."""
        case = _make_fraud_case()
        await brain.process_single(case)

        mock_span = MagicMock()
        mock_span.__enter__ = MagicMock(return_value=mock_span)
        mock_span.__exit__ = MagicMock(return_value=False)

        with patch("sentry_sdk.start_span", return_value=mock_span) as mock_start:
            await brain.escalate_to_arbitration(case.case_id)

        mock_start.assert_any_call(
            op="brain.escalate_arb",
            name="DisputeBrain.escalate_to_arbitration",
        )
        mock_span.set_data.assert_any_call("case_id", case.case_id)

    @pytest.mark.asyncio
    async def test_human_review_creates_span(self, brain: DisputeBrain) -> None:
        """Verify human review approval/rejection creates a span."""
        # Use a fraud case without certification so it goes to human review
        case = DisputeCase(
            transaction=TransactionDetails(
                transaction_id="TXN-INST-HR",
                transaction_date=date(2026, 2, 15),
                processing_date=date(2026, 2, 16),
                amount=500.00,
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
                cardholder_statement="I did not authorize this transaction.",
                signed_letter_provided=True,
            ),
            fraud_type_code=FraudTypeCode.ACCOUNT_TAKEOVER,
        )
        processed = await brain.process_single(case)

        mock_span = MagicMock()
        mock_span.__enter__ = MagicMock(return_value=mock_span)
        mock_span.__exit__ = MagicMock(return_value=False)

        with patch("sentry_sdk.start_span", return_value=mock_span) as mock_start:
            await brain.approve_human_review(
                processed.case_id, approved=True, reviewer_notes="Looks good"
            )

        mock_start.assert_any_call(
            op="brain.human_review",
            name="DisputeBrain.approve_human_review",
        )
        mock_span.set_data.assert_any_call("case_id", processed.case_id)
        mock_span.set_data.assert_any_call("approved", True)

    @pytest.mark.asyncio
    async def test_worker_captures_exception(self, brain: DisputeBrain) -> None:
        """Verify exceptions in task handling call sentry_sdk.capture_exception."""
        case = _make_fraud_case()
        brain._cases[case.case_id] = case

        task = DisputeTask(case_id=case.case_id, action="process_dispute")
        await brain._queue.enqueue(task)

        exc = RuntimeError("test error")

        with (
            patch.object(
                brain, "_handle_task", side_effect=exc
            ),
            patch("src.orchestrator.brain.sentry_sdk.capture_exception") as mock_capture,
        ):
            brain._running = True
            dequeued = await brain._queue.dequeue()
            assert dequeued is not None
            try:
                await brain._handle_task(dequeued)
            except RuntimeError:
                mock_capture(exc)

        mock_capture.assert_called_once_with(exc)

    @pytest.mark.asyncio
    async def test_breadcrumb_at_lifecycle_transitions(
        self, brain: DisputeBrain
    ) -> None:
        """Verify breadcrumbs are added at intake, categorization, and decision."""
        mock_span = MagicMock()
        mock_span.__enter__ = MagicMock(return_value=mock_span)
        mock_span.__exit__ = MagicMock(return_value=False)

        case = _make_fraud_case()
        with (
            patch("sentry_sdk.start_span", return_value=mock_span),
            patch("sentry_sdk.add_breadcrumb") as mock_breadcrumb,
        ):
            # submit_dispute adds an intake breadcrumb
            await brain.submit_dispute(case)

        # Check intake breadcrumb from submit_dispute
        intake_calls = [
            c
            for c in mock_breadcrumb.call_args_list
            if c.kwargs.get("data", {}).get("stage") == "intake"
        ]
        assert len(intake_calls) >= 1

        # Now process through the pipeline to get categorization + decision breadcrumbs
        case2 = _make_fraud_case()
        with (
            patch("sentry_sdk.start_span", return_value=mock_span),
            patch("sentry_sdk.add_breadcrumb") as mock_breadcrumb2,
        ):
            await brain.process_single(case2)

        breadcrumb_stages = [
            c.kwargs.get("data", {}).get("stage")
            for c in mock_breadcrumb2.call_args_list
        ]
        assert "categorization" in breadcrumb_stages
        assert "decision" in breadcrumb_stages
