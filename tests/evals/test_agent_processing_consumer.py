"""Eval tests for ProcessingErrorsAgent and ConsumerDisputesAgent.

Validates that both agents produce correct decisions for various dispute
scenarios using the mock LLM framework from conftest.py.
"""

from datetime import date, datetime

from src.agents.consumer_disputes_agent import ConsumerDisputesAgent
from src.agents.processing_errors_agent import ProcessingErrorsAgent
from src.models.dispute import (
    CardholderInfo,
    DisputeCase,
    DisputeEvidence,
    TransactionDetails,
)
from src.models.enums import (
    DisputeCategory,
    DisputeCondition,
    DisputeResolution,
    Region,
    TransactionEnvironment,
)


def _base_transaction(**overrides):
    defaults = {
        "transaction_id": "TXN-AGENT-001",
        "transaction_date": date(2026, 2, 15),
        "processing_date": date(2026, 2, 16),
        "amount": 500.00,
        "currency": "USD",
        "merchant_name": "TestMerchant",
        "merchant_category_code": "5411",
        "merchant_country": "US",
        "acquirer_bin": "411111",
        "issuer_bin": "422222",
        "environment": TransactionEnvironment.ECOMMERCE,
        "region": Region.US,
    }
    defaults.update(overrides)
    return TransactionDetails(**defaults)


def _make_processing_case(
    condition=DisputeCondition.DUPLICATE_PROCESSING,
    statement=None,
    dispute_amount=None,
    dispute_filed_date=None,
    **txn_overrides,
):
    case = DisputeCase(
        transaction=_base_transaction(**txn_overrides),
        cardholder=CardholderInfo(
            cardholder_name="Test User",
            partial_payment_credential="****1234",
            cardholder_statement=statement,
        ),
    )
    case.category = DisputeCategory.PROCESSING_ERRORS
    case.condition = condition
    case.dispute_amount = dispute_amount if dispute_amount is not None else 500.00
    case.dispute_currency = "USD"
    case.dispute_filed_date = dispute_filed_date or datetime.utcnow()
    return case


def _make_consumer_case(
    condition=DisputeCondition.MERCHANDISE_NOT_RECEIVED,
    statement=None,
    dispute_amount=None,
    dispute_filed_date=None,
    **txn_overrides,
):
    case = DisputeCase(
        transaction=_base_transaction(**txn_overrides),
        cardholder=CardholderInfo(
            cardholder_name="Test User",
            partial_payment_credential="****1234",
            cardholder_statement=statement,
        ),
    )
    case.category = DisputeCategory.CONSUMER_DISPUTES
    case.condition = condition
    case.dispute_amount = dispute_amount if dispute_amount is not None else 500.00
    case.dispute_currency = "USD"
    case.dispute_filed_date = dispute_filed_date or datetime.utcnow()
    return case


# ── Processing Errors Agent Tests ──────────────────────────────────────


async def test_processing_error_valid():
    """Condition 12.6 (duplicate), valid case -> issuer_win, confidence >= 0.85."""
    case = _make_processing_case(condition=DisputeCondition.DUPLICATE_PROCESSING)
    agent = ProcessingErrorsAgent()
    result = await agent.process(case)
    assert result.decision.resolution == DisputeResolution.ISSUER_WIN
    assert result.decision.confidence_score >= 0.85


async def test_processing_error_12_5_no_amount():
    """Condition 12.5, dispute_amount=None -> invalid_dispute."""
    case = _make_processing_case(condition=DisputeCondition.INCORRECT_AMOUNT)
    case.dispute_amount = None
    agent = ProcessingErrorsAgent()
    result = await agent.process(case)
    assert result.decision.resolution == DisputeResolution.INVALID_DISPUTE


async def test_processing_error_time_expired():
    """Dispute filed outside time limit (> 120 days) -> invalid_dispute."""
    case = _make_processing_case(
        processing_date=date(2025, 6, 1),
        dispute_filed_date=datetime(2025, 11, 15),
    )
    agent = ProcessingErrorsAgent()
    result = await agent.process(case)
    assert result.decision.resolution == DisputeResolution.INVALID_DISPUTE


# ── Consumer Disputes Agent Tests ──────────────────────────────────────


async def test_consumer_valid_merchandise_not_received():
    """Condition 13.1, valid case -> issuer_win."""
    case = _make_consumer_case(condition=DisputeCondition.MERCHANDISE_NOT_RECEIVED)
    agent = ConsumerDisputesAgent()
    result = await agent.process(case)
    assert result.decision.resolution == DisputeResolution.ISSUER_WIN


async def test_consumer_cancelled_recurring_valid():
    """Condition 13.2, recurring cancelled -> issuer_win."""
    case = _make_consumer_case(
        condition=DisputeCondition.CANCELLED_RECURRING,
        is_recurring=True,
    )
    agent = ConsumerDisputesAgent()
    result = await agent.process(case)
    assert result.decision.resolution == DisputeResolution.ISSUER_WIN


async def test_consumer_not_as_described_with_evidence():
    """Condition 13.3, compelling evidence added -> issuer_win."""
    case = _make_consumer_case(condition=DisputeCondition.NOT_AS_DESCRIBED)
    case.evidence.append(
        DisputeEvidence(
            description="Product photos showing defects",
            evidence_type="photo",
            provided_by="issuer",
            is_compelling_evidence=True,
        )
    )
    agent = ConsumerDisputesAgent()
    result = await agent.process(case)
    assert result.decision.resolution == DisputeResolution.ISSUER_WIN


async def test_consumer_time_expired():
    """Consumer dispute filed outside time limit -> invalid_dispute."""
    case = _make_consumer_case(
        processing_date=date(2025, 6, 1),
        dispute_filed_date=datetime(2025, 11, 15),
    )
    agent = ConsumerDisputesAgent()
    result = await agent.process(case)
    assert result.decision.resolution == DisputeResolution.INVALID_DISPUTE


async def test_consumer_high_value_human_review():
    """Amount > $25,000 -> requires_human_review=True."""
    case = _make_consumer_case(dispute_amount=30000.0)
    agent = ConsumerDisputesAgent()
    result = await agent.process(case)
    assert result.decision.requires_human_review is True
