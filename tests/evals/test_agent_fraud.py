"""Eval tests for FraudDisputeAgent.process().

Validates decisions, rule citations, escalation behaviour, and lifecycle
stage transitions produced by the fraud agent under various input scenarios.
"""

from datetime import date, datetime

from src.agents.fraud_agent import FraudDisputeAgent
from src.models.dispute import CardholderInfo, DisputeCase, TransactionDetails
from src.models.enums import (
    DisputeCategory,
    DisputeCondition,
    DisputeLifecycleStage,
    DisputeResolution,
    FraudTypeCode,
    Region,
    TransactionEnvironment,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _base_transaction(**overrides):
    defaults = {
        "transaction_id": "TXN-FRAUD-AGENT-001",
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


def _make_fraud_case(
    condition=DisputeCondition.OTHER_FRAUD_CARD_ABSENT,
    statement=None,
    fraud_type_code=None,
    issuer_certification=None,
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
        fraud_type_code=fraud_type_code,
        issuer_certification=issuer_certification,
    )
    case.category = DisputeCategory.FRAUD
    case.condition = condition
    case.dispute_amount = dispute_amount if dispute_amount is not None else 500.00
    case.dispute_currency = "USD"
    case.dispute_filed_date = dispute_filed_date or datetime.utcnow()
    return case


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

agent = FraudDisputeAgent()


async def test_valid_fraud_dispute_issuer_win():
    """Condition 10.4, fraud type + certification, amount < $25k -> issuer_win."""
    case = _make_fraud_case(
        condition=DisputeCondition.OTHER_FRAUD_CARD_ABSENT,
        fraud_type_code=FraudTypeCode.ACCOUNT_TAKEOVER,
        issuer_certification="Issuer certifies fraud",
        dispute_amount=5000.00,
    )

    result = await agent.process(case)

    assert result.decision is not None
    assert result.decision.resolution == DisputeResolution.ISSUER_WIN
    assert result.decision.confidence_score >= 0.85
    assert result.decision.requires_human_review is False
    assert result.stage == DisputeLifecycleStage.RESOLVED


async def test_fraud_invalid_chip_initiated_10_1():
    """Condition 10.1, chip-initiated = True -> invalid_dispute."""
    case = _make_fraud_case(
        condition=DisputeCondition.EMV_COUNTERFEIT_FRAUD,
        fraud_type_code=FraudTypeCode.COUNTERFEIT,
        issuer_certification="Issuer certifies fraud",
        is_chip_initiated=True,
        is_chip_card=True,
        environment=TransactionEnvironment.CARD_PRESENT,
    )

    result = await agent.process(case)

    assert result.decision is not None
    assert result.decision.resolution == DisputeResolution.INVALID_DISPUTE
    assert result.decision.is_valid is False if hasattr(result.decision, "is_valid") else True
    # The key assertion: resolution must be INVALID_DISPUTE
    assert case.decision.resolution == DisputeResolution.INVALID_DISPUTE


async def test_fraud_time_expired():
    """Dispute filed > 120 days after processing date -> invalid_dispute."""
    processing = date(2025, 6, 1)
    filed = datetime(2025, 11, 15)  # 167 days later

    case = _make_fraud_case(
        fraud_type_code=FraudTypeCode.ACCOUNT_TAKEOVER,
        issuer_certification="Issuer certifies fraud",
        processing_date=processing,
        transaction_date=date(2025, 5, 30),
        dispute_filed_date=filed,
    )

    result = await agent.process(case)

    assert result.decision is not None
    assert result.decision.resolution == DisputeResolution.INVALID_DISPUTE
    assert "time" in result.decision.rationale.lower() or "limit" in result.decision.rationale.lower()


async def test_fraud_missing_documentation_human_review():
    """No fraud type code, no certification -> human review, low confidence."""
    case = _make_fraud_case(
        fraud_type_code=None,
        issuer_certification=None,
    )

    result = await agent.process(case)

    assert result.decision is not None
    assert result.decision.requires_human_review is True
    assert result.decision.confidence_score < 0.70


async def test_fraud_high_value_human_review():
    """Amount > $25k, all docs present -> human review, reason mentions threshold."""
    case = _make_fraud_case(
        fraud_type_code=FraudTypeCode.ACCOUNT_TAKEOVER,
        issuer_certification="Issuer certifies fraud",
        dispute_amount=50000.0,
    )

    result = await agent.process(case)

    assert result.decision is not None
    assert result.decision.requires_human_review is True
    assert result.decision.human_review_reason is not None
    reason_lower = result.decision.human_review_reason.lower()
    assert "threshold" in reason_lower or "25,000" in reason_lower or "25000" in reason_lower or "high" in reason_lower


async def test_fraud_rule_citations_present():
    """Valid fraud case -> rule_evaluations is non-empty with rule_section."""
    case = _make_fraud_case(
        fraud_type_code=FraudTypeCode.ACCOUNT_TAKEOVER,
        issuer_certification="Issuer certifies fraud",
        dispute_amount=5000.00,
    )

    result = await agent.process(case)

    assert len(result.rule_evaluations) > 0
    for evaluation in result.rule_evaluations:
        assert evaluation.rule_section is not None
        assert len(evaluation.rule_section) > 0


async def test_fraud_stage_transitions():
    """Valid fraud case -> stage history contains RULE_EVALUATION -> DECISION -> RESOLVED."""
    case = _make_fraud_case(
        fraud_type_code=FraudTypeCode.ACCOUNT_TAKEOVER,
        issuer_certification="Issuer certifies fraud",
        dispute_amount=5000.00,
    )

    result = await agent.process(case)

    to_stages = [entry["to_stage"] for entry in result.stage_history]
    assert DisputeLifecycleStage.RULE_EVALUATION.value in to_stages
    assert DisputeLifecycleStage.DECISION.value in to_stages
    assert DisputeLifecycleStage.RESOLVED.value in to_stages

    # Verify ordering: RULE_EVALUATION before DECISION before RESOLVED
    idx_rule = to_stages.index(DisputeLifecycleStage.RULE_EVALUATION.value)
    idx_decision = to_stages.index(DisputeLifecycleStage.DECISION.value)
    idx_resolved = to_stages.index(DisputeLifecycleStage.RESOLVED.value)
    assert idx_rule < idx_decision < idx_resolved


async def test_fraud_assigned_agent_set():
    """Any fraud case -> assigned_agent == 'fraud_agent'."""
    case = _make_fraud_case()

    result = await agent.process(case)

    assert result.assigned_agent == "fraud_agent"
