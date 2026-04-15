"""Eval tests for categorize_dispute() — Category 10 (Fraud) disputes.

Validates that the categorizer correctly identifies fraud disputes and
assigns the appropriate condition codes (10.1–10.4) based on transaction
environment, chip card presence, and fraud type indicators.
"""

from datetime import date

from src.models.dispute import CardholderInfo, DisputeCase, TransactionDetails
from src.models.enums import (
    DisputeCategory,
    DisputeCondition,
    FraudTypeCode,
    Region,
    TransactionEnvironment,
)
from src.rules.categorizer import categorize_dispute


def _base_transaction(**overrides):
    defaults = {
        "transaction_id": "TXN-FRAUD-001",
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


def _make_case(statement=None, fraud_type_code=None, **txn_overrides):
    return DisputeCase(
        transaction=_base_transaction(**txn_overrides),
        cardholder=CardholderInfo(
            cardholder_name="Test User",
            partial_payment_credential="****1234",
            cardholder_statement=statement,
        ),
        fraud_type_code=fraud_type_code,
    )


# ── 10.1  EMV Counterfeit Fraud ──────────────────────────────────────────


def test_emv_counterfeit_fraud_chip_card():
    """Card-present, chip card, non-chip-initiated, fraud type 4 -> 10.1."""
    case = _make_case(
        fraud_type_code=FraudTypeCode.COUNTERFEIT,
        environment=TransactionEnvironment.CARD_PRESENT,
        is_chip_card=True,
        is_chip_initiated=False,
    )
    result = categorize_dispute(case)

    assert result.category == DisputeCategory.FRAUD
    assert result.condition == DisputeCondition.EMV_COUNTERFEIT_FRAUD
    assert result.confidence >= 0.85


def test_emv_counterfeit_fraud_chip_initiated_still_categorized():
    """Card-present, chip card, chip-initiated, fraud type 4 -> still 10.1."""
    case = _make_case(
        fraud_type_code=FraudTypeCode.COUNTERFEIT,
        environment=TransactionEnvironment.CARD_PRESENT,
        is_chip_card=True,
        is_chip_initiated=True,
    )
    result = categorize_dispute(case)

    assert result.category == DisputeCategory.FRAUD
    assert result.condition == DisputeCondition.EMV_COUNTERFEIT_FRAUD


# ── 10.2  EMV Non-Counterfeit Fraud ──────────────────────────────────────


def test_emv_non_counterfeit_lost_card():
    """Chip card, fraud type 0 (lost) -> 10.2."""
    case = _make_case(
        fraud_type_code=FraudTypeCode.LOST,
        environment=TransactionEnvironment.CARD_PRESENT,
        is_chip_card=True,
    )
    result = categorize_dispute(case)

    assert result.category == DisputeCategory.FRAUD
    assert result.condition == DisputeCondition.EMV_NON_COUNTERFEIT_FRAUD


def test_emv_non_counterfeit_stolen_card():
    """Chip card, fraud type 1 (stolen) -> 10.2."""
    case = _make_case(
        fraud_type_code=FraudTypeCode.STOLEN,
        environment=TransactionEnvironment.CARD_PRESENT,
        is_chip_card=True,
    )
    result = categorize_dispute(case)

    assert result.category == DisputeCategory.FRAUD
    assert result.condition == DisputeCondition.EMV_NON_COUNTERFEIT_FRAUD


# ── 10.3  Other Fraud — Card Present ────────────────────────────────────


def test_other_fraud_card_present():
    """Card-present, fraud type present, no chip -> 10.3."""
    case = _make_case(
        fraud_type_code=FraudTypeCode.LOST,
        environment=TransactionEnvironment.CARD_PRESENT,
        is_chip_card=False,
    )
    result = categorize_dispute(case)

    assert result.category == DisputeCategory.FRAUD
    assert result.condition == DisputeCondition.OTHER_FRAUD_CARD_PRESENT


# ── 10.4  Other Fraud — Card Absent ─────────────────────────────────────


def test_other_fraud_card_absent_ecommerce():
    """E-commerce, fraud type present -> 10.4."""
    case = _make_case(
        fraud_type_code=FraudTypeCode.LOST,
        environment=TransactionEnvironment.ECOMMERCE,
    )
    result = categorize_dispute(case)

    assert result.category == DisputeCategory.FRAUD
    assert result.condition == DisputeCondition.OTHER_FRAUD_CARD_ABSENT


def test_other_fraud_card_absent_moto():
    """MOTO environment, fraud type present -> 10.4."""
    case = _make_case(
        fraud_type_code=FraudTypeCode.LOST,
        environment=TransactionEnvironment.MOTO,
    )
    result = categorize_dispute(case)

    assert result.category == DisputeCategory.FRAUD
    assert result.condition == DisputeCondition.OTHER_FRAUD_CARD_ABSENT


# ── Statement-based fraud detection ─────────────────────────────────────


def test_fraud_from_statement_unauthorized_card_present():
    """Statement 'unauthorized', card-present, no fraud type -> 10.3."""
    case = _make_case(
        statement="This transaction was unauthorized",
        environment=TransactionEnvironment.CARD_PRESENT,
    )
    result = categorize_dispute(case)

    assert result.category == DisputeCategory.FRAUD
    assert result.condition == DisputeCondition.OTHER_FRAUD_CARD_PRESENT


def test_fraud_from_statement_unauthorized_card_absent():
    """Statement 'unauthorized', e-commerce, no fraud type -> 10.4."""
    case = _make_case(
        statement="This transaction was unauthorized",
        environment=TransactionEnvironment.ECOMMERCE,
    )
    result = categorize_dispute(case)

    assert result.category == DisputeCategory.FRAUD
    assert result.condition == DisputeCondition.OTHER_FRAUD_CARD_ABSENT


def test_fraud_from_statement_identity_theft():
    """Statement 'identity theft', e-commerce -> 10.4."""
    case = _make_case(
        statement="This is identity theft",
        environment=TransactionEnvironment.ECOMMERCE,
    )
    result = categorize_dispute(case)

    assert result.category == DisputeCategory.FRAUD
    assert result.condition == DisputeCondition.OTHER_FRAUD_CARD_ABSENT
