"""Eval tests for AuthorizationDisputeAgent.process() decisions."""

from datetime import date, datetime

from src.agents.authorization_agent import AuthorizationDisputeAgent
from src.models.dispute import CardholderInfo, DisputeCase, DisputeEvidence, TransactionDetails
from src.models.enums import (
    DisputeCategory,
    DisputeCondition,
    DisputeLifecycleStage,
    DisputeResolution,
    Region,
    TransactionEnvironment,
)


def _base_transaction(**overrides):
    defaults = {
        "transaction_id": "TXN-AUTH-AGENT-001",
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


def _make_auth_case(
    condition=DisputeCondition.DECLINED_AUTHORIZATION,
    statement=None,
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
    case.category = DisputeCategory.AUTHORIZATION
    case.condition = condition
    case.dispute_amount = 500.00
    case.dispute_currency = "USD"
    case.dispute_filed_date = dispute_filed_date or datetime.utcnow()
    return case


# ---------------------------------------------------------------------------
# 1. CRB with evidence -> issuer_win
# ---------------------------------------------------------------------------
async def test_crb_with_evidence_issuer_win():
    case = _make_auth_case(condition=DisputeCondition.CARD_RECOVERY_BULLETIN)
    case.evidence.append(
        DisputeEvidence(
            description="CRB listing confirmation",
            evidence_type="document",
            provided_by="issuer",
        )
    )
    agent = AuthorizationDisputeAgent()
    result = await agent.process(case)
    assert result.decision.resolution == DisputeResolution.ISSUER_WIN


# ---------------------------------------------------------------------------
# 2. CRB without evidence -> acquirer_win
# ---------------------------------------------------------------------------
async def test_crb_no_evidence_acquirer_win():
    case = _make_auth_case(condition=DisputeCondition.CARD_RECOVERY_BULLETIN)
    agent = AuthorizationDisputeAgent()
    result = await agent.process(case)
    assert result.decision.resolution == DisputeResolution.ACQUIRER_WIN


# ---------------------------------------------------------------------------
# 3. Declined auth valid (non-zero response) -> issuer_win
# ---------------------------------------------------------------------------
async def test_declined_auth_valid():
    case = _make_auth_case(
        condition=DisputeCondition.DECLINED_AUTHORIZATION,
        authorization_response_code="14",
    )
    agent = AuthorizationDisputeAgent()
    result = await agent.process(case)
    assert result.decision.resolution == DisputeResolution.ISSUER_WIN


# ---------------------------------------------------------------------------
# 4. Declined auth actually approved (response starts with 0) -> invalid_dispute
# ---------------------------------------------------------------------------
async def test_declined_auth_actually_approved():
    case = _make_auth_case(
        condition=DisputeCondition.DECLINED_AUTHORIZATION,
        authorization_response_code="00",
    )
    agent = AuthorizationDisputeAgent()
    result = await agent.process(case)
    assert result.decision.resolution == DisputeResolution.INVALID_DISPUTE


# ---------------------------------------------------------------------------
# 5. No auth code (None) -> issuer_win
# ---------------------------------------------------------------------------
async def test_no_auth_code_valid():
    case = _make_auth_case(
        condition=DisputeCondition.NO_AUTHORIZATION,
        authorization_code=None,
    )
    agent = AuthorizationDisputeAgent()
    result = await agent.process(case)
    assert result.decision.resolution == DisputeResolution.ISSUER_WIN


# ---------------------------------------------------------------------------
# 6. No auth but code exists -> invalid_dispute
# ---------------------------------------------------------------------------
async def test_no_auth_but_code_exists():
    case = _make_auth_case(
        condition=DisputeCondition.NO_AUTHORIZATION,
        authorization_code="AUTH123",
    )
    agent = AuthorizationDisputeAgent()
    result = await agent.process(case)
    assert result.decision.resolution == DisputeResolution.INVALID_DISPUTE


# ---------------------------------------------------------------------------
# 7. Time expired (>120 days) -> invalid_dispute
# ---------------------------------------------------------------------------
async def test_auth_time_expired():
    case = _make_auth_case(
        condition=DisputeCondition.DECLINED_AUTHORIZATION,
        dispute_filed_date=datetime(2025, 11, 15),
        processing_date=date(2025, 6, 1),
    )
    agent = AuthorizationDisputeAgent()
    result = await agent.process(case)
    assert result.decision.resolution == DisputeResolution.INVALID_DISPUTE


# ---------------------------------------------------------------------------
# 8. Stage transitions: RULE_EVALUATION -> DECISION -> RESOLVED
# ---------------------------------------------------------------------------
async def test_auth_stage_transitions():
    case = _make_auth_case(
        condition=DisputeCondition.DECLINED_AUTHORIZATION,
        authorization_response_code="14",
    )
    agent = AuthorizationDisputeAgent()
    result = await agent.process(case)

    stages = [entry["to_stage"] for entry in result.stage_history]
    assert "rule_evaluation" in stages
    assert "decision" in stages
    assert "resolved" in stages
    assert result.stage == DisputeLifecycleStage.RESOLVED
