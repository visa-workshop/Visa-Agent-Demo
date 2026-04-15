"""Eval tests for Category 11 (Authorization) dispute categorization."""

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
        "transaction_id": "TXN-AUTH-001",
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


def test_card_recovery_bulletin():
    case = _make_case(statement="card recovery bulletin")
    result = categorize_dispute(case)
    assert result.category == DisputeCategory.AUTHORIZATION
    assert result.condition == DisputeCondition.CARD_RECOVERY_BULLETIN


def test_declined_authorization_response_code():
    case = _make_case(authorization_response_code="51")
    result = categorize_dispute(case)
    assert result.category == DisputeCategory.AUTHORIZATION
    assert result.condition == DisputeCondition.DECLINED_AUTHORIZATION


def test_declined_authorization_from_statement():
    case = _make_case(statement="declined", authorization_response_code="51")
    result = categorize_dispute(case)
    assert result.category == DisputeCategory.AUTHORIZATION
    assert result.condition == DisputeCondition.DECLINED_AUTHORIZATION


def test_no_authorization_no_auth_code():
    case = _make_case(statement="no authorization")
    result = categorize_dispute(case)
    assert result.category == DisputeCategory.AUTHORIZATION
    assert result.condition == DisputeCondition.NO_AUTHORIZATION


def test_no_authorization_missing_code_non_recurring():
    case = _make_case(statement="generic issue with charge")
    result = categorize_dispute(case)
    assert result.category == DisputeCategory.AUTHORIZATION
    assert result.condition == DisputeCondition.NO_AUTHORIZATION


def test_expired_card_declined():
    case = _make_case(statement="expired card")
    result = categorize_dispute(case)
    assert result.category == DisputeCategory.AUTHORIZATION
    assert result.condition == DisputeCondition.NO_AUTHORIZATION
