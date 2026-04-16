"""Tests for dispute categorization instrumentation.

Verifies structured logging, timing, low-confidence warnings,
error handling, and invalid category/condition handling added
to categorize_dispute().
"""

import logging
from datetime import date
from unittest.mock import patch

import pytest

from src.models.dispute import (
    CardholderInfo,
    DisputeCase,
    TransactionDetails,
)
from src.models.enums import (
    DisputeCondition,
    FraudTypeCode,
    Region,
    TransactionEnvironment,
)
from src.rules.categorizer import categorize_dispute

LOGGER_NAME = "src.rules.categorizer"


def _base_transaction(**overrides: object) -> TransactionDetails:
    defaults = {
        "transaction_id": "TXN-INST-001",
        "transaction_date": date(2026, 2, 15),
        "processing_date": date(2026, 2, 16),
        "amount": 250.00,
        "currency": "USD",
        "merchant_name": "InstrumentMerchant",
        "merchant_category_code": "5411",
        "merchant_country": "US",
        "acquirer_bin": "411111",
        "issuer_bin": "422222",
        "environment": TransactionEnvironment.ECOMMERCE,
        "region": Region.US,
    }
    defaults.update(overrides)
    return TransactionDetails(**defaults)


def _make_case(
    statement: str | None = None,
    fraud_type_code: FraudTypeCode | None = None,
    **txn_overrides: object,
) -> DisputeCase:
    return DisputeCase(
        transaction=_base_transaction(**txn_overrides),
        cardholder=CardholderInfo(
            cardholder_name="Test User",
            partial_payment_credential="****1234",
            cardholder_statement=statement,
        ),
        fraud_type_code=fraud_type_code,
    )


class TestSuccessfulCategorizationLogging:
    """Verify INFO logs for input details and output results."""

    def test_logs_input_details(self, caplog: pytest.LogCaptureFixture) -> None:
        case = _make_case(
            statement="I received counterfeit goods",
            authorization_code="ABC",
            authorization_response_code="00",
        )
        with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
            categorize_dispute(case)

        input_logs = [r for r in caplog.records if "categorize_dispute called" in r.message]
        assert len(input_logs) >= 1
        msg = input_logs[0].message
        assert "transaction_id=TXN-INST-001" in msg
        assert "merchant=InstrumentMerchant" in msg
        assert "amount=250.0" in msg
        assert "environment=ecommerce" in msg

    def test_logs_output_result(self, caplog: pytest.LogCaptureFixture) -> None:
        case = _make_case(
            statement="I received counterfeit goods",
            authorization_code="ABC",
            authorization_response_code="00",
        )
        with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
            categorize_dispute(case)

        result_logs = [r for r in caplog.records if "categorization result" in r.message]
        assert len(result_logs) >= 1
        msg = result_logs[0].message
        assert "category=13" in msg
        assert "condition=13.4" in msg
        assert "confidence=" in msg
        assert "rationale=" in msg


class TestTimingLogging:
    """Verify that LLM call duration is logged."""

    def test_timing_logged_on_success(self, caplog: pytest.LogCaptureFixture) -> None:
        case = _make_case(
            statement="I received counterfeit goods",
            authorization_code="ABC",
            authorization_response_code="00",
        )
        with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
            categorize_dispute(case)

        timing_logs = [r for r in caplog.records if "elapsed_seconds=" in r.message and "chat_json completed" in r.message]
        assert len(timing_logs) >= 1

    def test_timing_logged_on_error(self, caplog: pytest.LogCaptureFixture) -> None:
        case = _make_case(statement="test error timing")
        with (
            patch("src.rules.categorizer.chat_json", side_effect=RuntimeError("API failure")),
            caplog.at_level(logging.ERROR, logger=LOGGER_NAME),
            pytest.raises(RuntimeError, match="API failure"),
        ):
            categorize_dispute(case)

        error_logs = [r for r in caplog.records if "chat_json failed" in r.message]
        assert len(error_logs) >= 1
        assert "elapsed_seconds=" in error_logs[0].message


class TestLowConfidenceWarning:
    """Verify WARNING log when confidence < 0.70."""

    def test_low_confidence_produces_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        """Default fallback case produces confidence=0.50 which is < 0.70."""
        case = _make_case(
            statement="I have a problem with this transaction",
            authorization_code="ABC",
            authorization_response_code="00",
        )
        with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
            result = categorize_dispute(case)

        assert result.confidence < 0.70
        warning_logs = [r for r in caplog.records if r.levelno == logging.WARNING and "low confidence" in r.message]
        assert len(warning_logs) >= 1
        assert "transaction_id=TXN-INST-001" in warning_logs[0].message

    def test_high_confidence_no_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        """A high-confidence result should NOT produce a low-confidence warning."""
        case = _make_case(
            statement="Cash was not dispensed at the ATM",
            authorization_code="ABC",
            authorization_response_code="00",
            environment=TransactionEnvironment.ATM,
        )
        with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
            result = categorize_dispute(case)

        assert result.confidence >= 0.70
        warning_logs = [r for r in caplog.records if r.levelno == logging.WARNING and "low confidence" in r.message]
        assert len(warning_logs) == 0


class TestLLMErrorHandling:
    """Verify that OpenAI/chat_json errors are caught, logged, and re-raised."""

    def test_runtime_error_logged_and_reraised(self, caplog: pytest.LogCaptureFixture) -> None:
        case = _make_case(statement="test")
        with (
            patch("src.rules.categorizer.chat_json", side_effect=RuntimeError("OpenAI API error")),
            caplog.at_level(logging.ERROR, logger=LOGGER_NAME),
            pytest.raises(RuntimeError, match="OpenAI API error"),
        ):
            categorize_dispute(case)

        error_logs = [r for r in caplog.records if r.levelno == logging.ERROR and "chat_json failed" in r.message]
        assert len(error_logs) >= 1
        assert "transaction_id=TXN-INST-001" in error_logs[0].message

    def test_generic_exception_logged_and_reraised(self, caplog: pytest.LogCaptureFixture) -> None:
        case = _make_case(statement="test")
        with (
            patch("src.rules.categorizer.chat_json", side_effect=ConnectionError("Network down")),
            caplog.at_level(logging.ERROR, logger=LOGGER_NAME),
            pytest.raises(ConnectionError, match="Network down"),
        ):
            categorize_dispute(case)

        error_logs = [r for r in caplog.records if r.levelno == logging.ERROR]
        assert len(error_logs) >= 1


class TestInvalidLLMResponse:
    """Verify that invalid category/condition values are logged at ERROR level."""

    def test_invalid_category_logged(self, caplog: pytest.LogCaptureFixture) -> None:
        bad_response = {
            "category": "99",
            "condition": "13.1",
            "confidence": 0.80,
            "rationale": "test",
            "alternative_conditions": [],
        }
        case = _make_case(statement="test")
        with (
            patch("src.rules.categorizer.chat_json", return_value=bad_response),
            caplog.at_level(logging.ERROR, logger=LOGGER_NAME),
            pytest.raises(ValueError),
        ):
            categorize_dispute(case)

        error_logs = [r for r in caplog.records if r.levelno == logging.ERROR and "invalid category" in r.message]
        assert len(error_logs) >= 1
        assert "category=99" in error_logs[0].message

    def test_invalid_condition_logged(self, caplog: pytest.LogCaptureFixture) -> None:
        bad_response = {
            "category": "13",
            "condition": "13.99",
            "confidence": 0.80,
            "rationale": "test",
            "alternative_conditions": [],
        }
        case = _make_case(statement="test")
        with (
            patch("src.rules.categorizer.chat_json", return_value=bad_response),
            caplog.at_level(logging.ERROR, logger=LOGGER_NAME),
            pytest.raises(ValueError),
        ):
            categorize_dispute(case)

        error_logs = [r for r in caplog.records if r.levelno == logging.ERROR and "invalid condition" in r.message]
        assert len(error_logs) >= 1
        assert "condition=13.99" in error_logs[0].message

    def test_invalid_alternative_condition_warns(self, caplog: pytest.LogCaptureFixture) -> None:
        """Invalid alternative conditions are skipped with a WARNING, not a crash."""
        bad_response = {
            "category": "13",
            "condition": "13.1",
            "confidence": 0.90,
            "rationale": "test",
            "alternative_conditions": ["13.2", "INVALID"],
        }
        case = _make_case(statement="test")
        with (
            patch("src.rules.categorizer.chat_json", return_value=bad_response),
            caplog.at_level(logging.WARNING, logger=LOGGER_NAME),
        ):
            result = categorize_dispute(case)

        assert len(result.alternative_conditions) == 1
        assert result.alternative_conditions[0] == DisputeCondition.CANCELLED_RECURRING
        warning_logs = [r for r in caplog.records if r.levelno == logging.WARNING and "skipping invalid alternative" in r.message]
        assert len(warning_logs) >= 1
