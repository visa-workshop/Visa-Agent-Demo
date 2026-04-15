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
        "transaction_id": "TXN-PROC-001",
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


def test_duplicate_processing():
    case = _make_case(
        statement="duplicate",
        authorization_code="ABC",
        authorization_response_code="00",
    )
    result = categorize_dispute(case)
    assert result.category == DisputeCategory.PROCESSING_ERRORS
    assert result.condition == DisputeCondition.DUPLICATE_PROCESSING


def test_charged_twice():
    case = _make_case(
        statement="charged twice",
        authorization_code="ABC",
        authorization_response_code="00",
    )
    result = categorize_dispute(case)
    assert result.category == DisputeCategory.PROCESSING_ERRORS
    assert result.condition == DisputeCondition.DUPLICATE_PROCESSING


def test_paid_by_other_means():
    case = _make_case(
        statement="paid by other means",
        authorization_code="ABC",
        authorization_response_code="00",
    )
    result = categorize_dispute(case)
    assert result.category == DisputeCategory.PROCESSING_ERRORS
    assert result.condition == DisputeCondition.DUPLICATE_PROCESSING


def test_incorrect_amount():
    case = _make_case(
        statement="incorrect amount",
        authorization_code="ABC",
        authorization_response_code="00",
    )
    result = categorize_dispute(case)
    assert result.category == DisputeCategory.PROCESSING_ERRORS
    assert result.condition == DisputeCondition.INCORRECT_AMOUNT


def test_wrong_amount():
    case = _make_case(
        statement="wrong amount",
        authorization_code="ABC",
        authorization_response_code="00",
    )
    result = categorize_dispute(case)
    assert result.category == DisputeCategory.PROCESSING_ERRORS
    assert result.condition == DisputeCondition.INCORRECT_AMOUNT


def test_incorrect_currency():
    case = _make_case(
        statement="incorrect currency",
        authorization_code="ABC",
        authorization_response_code="00",
    )
    result = categorize_dispute(case)
    assert result.category == DisputeCategory.PROCESSING_ERRORS
    assert result.condition == DisputeCondition.INCORRECT_CURRENCY


def test_wrong_account_number():
    case = _make_case(
        statement="wrong account",
        authorization_code="ABC",
        authorization_response_code="00",
    )
    result = categorize_dispute(case)
    assert result.category == DisputeCategory.PROCESSING_ERRORS
    assert result.condition == DisputeCondition.INCORRECT_ACCOUNT_NUMBER


def test_incorrect_transaction_code():
    case = _make_case(
        statement="incorrect code",
        authorization_code="ABC",
        authorization_response_code="00",
    )
    result = categorize_dispute(case)
    assert result.category == DisputeCategory.PROCESSING_ERRORS
    assert result.condition == DisputeCondition.INCORRECT_TRANSACTION_CODE


def test_invalid_data():
    case = _make_case(
        statement="invalid data",
        authorization_code="ABC",
        authorization_response_code="00",
    )
    result = categorize_dispute(case)
    assert result.category == DisputeCategory.PROCESSING_ERRORS
    assert result.condition == DisputeCondition.INVALID_DATA
