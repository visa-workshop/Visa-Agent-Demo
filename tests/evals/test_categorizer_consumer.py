"""Eval tests for categorize_dispute() — Category 13 (Consumer Disputes)."""

from datetime import date

from src.models.dispute import CardholderInfo, DisputeCase, TransactionDetails
from src.models.enums import (
    DisputeCategory,
    DisputeCondition,
    Region,
    TransactionEnvironment,
)
from src.rules.categorizer import categorize_dispute


def _base_transaction(**overrides):
    defaults = {
        "transaction_id": "TXN-CONSUMER-001",
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


def _make_case(statement=None, **txn_overrides):
    return DisputeCase(
        transaction=_base_transaction(**txn_overrides),
        cardholder=CardholderInfo(
            cardholder_name="Test User",
            partial_payment_credential="****1234",
            cardholder_statement=statement,
        ),
    )


# ── 13.1 Merchandise / Services Not Received ────────────────────────


def test_merchandise_not_received():
    case = _make_case(
        statement="Items not received after 30 days",
        authorization_code="ABC",
        authorization_response_code="00",
    )
    result = categorize_dispute(case)
    assert result.category == DisputeCategory.CONSUMER_DISPUTES
    assert result.condition == DisputeCondition.MERCHANDISE_NOT_RECEIVED


def test_never_received():
    case = _make_case(
        statement="I never received my order",
        authorization_code="ABC",
        authorization_response_code="00",
    )
    result = categorize_dispute(case)
    assert result.category == DisputeCategory.CONSUMER_DISPUTES
    assert result.condition == DisputeCondition.MERCHANDISE_NOT_RECEIVED


# ── 13.2 Cancelled Recurring ────────────────────────────────────────


def test_cancelled_recurring():
    case = _make_case(
        statement="I asked to cancel my subscription",
        is_recurring=True,
        authorization_code="ABC",
        authorization_response_code="00",
    )
    result = categorize_dispute(case)
    assert result.category == DisputeCategory.CONSUMER_DISPUTES
    assert result.condition == DisputeCondition.CANCELLED_RECURRING


# ── 13.3 Not as Described / Defective ───────────────────────────────


def test_not_as_described():
    case = _make_case(
        statement="Product was not as described",
        authorization_code="ABC",
        authorization_response_code="00",
    )
    result = categorize_dispute(case)
    assert result.category == DisputeCategory.CONSUMER_DISPUTES
    assert result.condition == DisputeCondition.NOT_AS_DESCRIBED


def test_defective_merchandise():
    case = _make_case(
        statement="The item is defective and does not work",
        authorization_code="ABC",
        authorization_response_code="00",
    )
    result = categorize_dispute(case)
    assert result.category == DisputeCategory.CONSUMER_DISPUTES
    assert result.condition == DisputeCondition.NOT_AS_DESCRIBED


# ── 13.4 Counterfeit Merchandise ────────────────────────────────────


def test_counterfeit_merchandise():
    case = _make_case(
        statement="The goods are counterfeit knockoffs",
        authorization_code="ABC",
        authorization_response_code="00",
    )
    result = categorize_dispute(case)
    assert result.category == DisputeCategory.CONSUMER_DISPUTES
    assert result.condition == DisputeCondition.COUNTERFEIT_MERCHANDISE


# ── 13.5 Misrepresentation ──────────────────────────────────────────


def test_misrepresentation():
    case = _make_case(
        statement="The seller did misrepresent the product features",
        authorization_code="ABC",
        authorization_response_code="00",
    )
    result = categorize_dispute(case)
    assert result.category == DisputeCategory.CONSUMER_DISPUTES
    assert result.condition == DisputeCondition.MISREPRESENTATION


# ── 13.6 Credit Not Processed ───────────────────────────────────────


def test_credit_not_processed():
    case = _make_case(
        statement="Merchant promised a credit not yet applied",
        authorization_code="ABC",
        authorization_response_code="00",
    )
    result = categorize_dispute(case)
    assert result.category == DisputeCategory.CONSUMER_DISPUTES
    assert result.condition == DisputeCondition.CREDIT_NOT_PROCESSED


# ── 13.7 Cancelled Merchandise / Services ───────────────────────────


def test_cancelled_merchandise():
    case = _make_case(
        statement="I want to cancel my order",
        authorization_code="ABC",
        authorization_response_code="00",
    )
    result = categorize_dispute(case)
    assert result.category == DisputeCategory.CONSUMER_DISPUTES
    assert result.condition == DisputeCondition.CANCELLED_MERCHANDISE


# ── 13.8 Original Credit Transaction Not Accepted ───────────────────


def test_oct_not_accepted():
    case = _make_case(
        statement="The original credit was rejected",
        authorization_code="ABC",
        authorization_response_code="00",
    )
    result = categorize_dispute(case)
    assert result.category == DisputeCategory.CONSUMER_DISPUTES
    assert result.condition == DisputeCondition.OCT_NOT_ACCEPTED


# ── 13.9 Non-Receipt of Cash from ATM ───────────────────────────────


def test_non_receipt_cash_atm():
    case = _make_case(
        statement="ATM did not dispense cash",
        environment=TransactionEnvironment.ATM,
        authorization_code="ABC",
        authorization_response_code="00",
    )
    result = categorize_dispute(case)
    assert result.category == DisputeCategory.CONSUMER_DISPUTES
    assert result.condition == DisputeCondition.NON_RECEIPT_CASH_ATM
