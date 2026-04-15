"""Eval tests for DisputeBrain orchestrator lifecycle processing."""

from datetime import date

from src.models.dispute import CardholderInfo, DisputeCase, TransactionDetails
from src.models.enums import (
    DisputeCategory,
    DisputeLifecycleStage,
    FraudTypeCode,
    Region,
    TransactionEnvironment,
)
from src.orchestrator.brain import DisputeBrain
from src.queue.task_queue import DisputeTaskQueue

# ---------------------------------------------------------------------------
# Case builder helpers
# ---------------------------------------------------------------------------

def _base_transaction(**overrides):
    defaults = {
        "transaction_id": "TXN-BRAIN-001",
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


def _make_case(
    statement=None,
    fraud_type_code=None,
    issuer_certification=None,
    **txn_overrides,
):
    return DisputeCase(
        transaction=_base_transaction(**txn_overrides),
        cardholder=CardholderInfo(
            cardholder_name="Test User",
            partial_payment_credential="****1234",
            cardholder_statement=statement,
        ),
        fraud_type_code=fraud_type_code,
        issuer_certification=issuer_certification,
    )


async def _make_brain():
    queue = DisputeTaskQueue()
    return DisputeBrain(queue)


# ---------------------------------------------------------------------------
# 1. Submit and process fraud case
# ---------------------------------------------------------------------------

async def test_brain_submit_and_process_fraud():
    brain = await _make_brain()
    case = _make_case(
        fraud_type_code=FraudTypeCode.ACCOUNT_TAKEOVER,
        statement="unauthorized transaction",
    )
    result = await brain.process_single(case)

    assert result.stage == DisputeLifecycleStage.RESOLVED
    assert result.category is not None
    assert result.condition is not None
    assert result.decision is not None


# ---------------------------------------------------------------------------
# 2. Submit and process consumer case
# ---------------------------------------------------------------------------

async def test_brain_submit_and_process_consumer():
    brain = await _make_brain()
    case = _make_case(
        statement="merchandise not received",
        authorization_code="ABC",
        authorization_response_code="00",
    )
    result = await brain.process_single(case)

    assert result.stage == DisputeLifecycleStage.RESOLVED
    assert result.category == DisputeCategory.CONSUMER_DISPUTES


# ---------------------------------------------------------------------------
# 3. Validation rejects missing transaction id
# ---------------------------------------------------------------------------

async def test_brain_validation_rejects_missing_txn_id():
    brain = await _make_brain()
    case = _make_case(transaction_id="", statement="test")
    result = await brain.process_single(case)

    assert result.stage == DisputeLifecycleStage.REJECTED


# ---------------------------------------------------------------------------
# 4. Validation rejects zero amount
# ---------------------------------------------------------------------------

async def test_brain_validation_rejects_zero_amount():
    brain = await _make_brain()
    case = _make_case(statement="test")
    # Bypass Pydantic gt=0 validation by setting after construction
    case.transaction.amount = 0
    result = await brain.process_single(case)

    assert result.stage == DisputeLifecycleStage.REJECTED


# ---------------------------------------------------------------------------
# 5. Validation rejects missing cardholder name
# ---------------------------------------------------------------------------

async def test_brain_validation_rejects_missing_cardholder():
    brain = await _make_brain()
    case = DisputeCase(
        transaction=_base_transaction(),
        cardholder=CardholderInfo(
            cardholder_name="",
            partial_payment_credential="****1234",
            cardholder_statement="test",
        ),
    )
    result = await brain.process_single(case)

    assert result.stage == DisputeLifecycleStage.REJECTED


# ---------------------------------------------------------------------------
# 6. Agent routing - fraud
# ---------------------------------------------------------------------------

async def test_brain_agent_routing_fraud():
    brain = await _make_brain()
    case = _make_case(
        fraud_type_code=FraudTypeCode.ACCOUNT_TAKEOVER,
        statement="unauthorized transaction",
    )
    result = await brain.process_single(case)

    assert result.assigned_agent == "fraud_agent"


# ---------------------------------------------------------------------------
# 7. Agent routing - authorization
# ---------------------------------------------------------------------------

async def test_brain_agent_routing_authorization():
    brain = await _make_brain()
    case = _make_case(
        statement="declined transaction",
        authorization_response_code="14",
    )
    result = await brain.process_single(case)

    assert result.assigned_agent == "authorization_agent"


# ---------------------------------------------------------------------------
# 8. Agent routing - processing errors
# ---------------------------------------------------------------------------

async def test_brain_agent_routing_processing_errors():
    brain = await _make_brain()
    case = _make_case(
        statement="duplicate charge",
        authorization_code="ABC",
        authorization_response_code="00",
    )
    result = await brain.process_single(case)

    assert result.assigned_agent == "processing_errors_agent"


# ---------------------------------------------------------------------------
# 9. Agent routing - consumer disputes
# ---------------------------------------------------------------------------

async def test_brain_agent_routing_consumer():
    brain = await _make_brain()
    case = _make_case(
        statement="merchandise not received",
        authorization_code="ABC",
        authorization_response_code="00",
    )
    result = await brain.process_single(case)

    assert result.assigned_agent == "consumer_disputes_agent"


# ---------------------------------------------------------------------------
# 10. Get case summary
# ---------------------------------------------------------------------------

async def test_brain_get_case_summary():
    brain = await _make_brain()
    case = _make_case(
        fraud_type_code=FraudTypeCode.ACCOUNT_TAKEOVER,
        statement="unauthorized transaction",
    )
    result = await brain.process_single(case)
    summary = brain.get_case_summary(result.case_id)

    assert summary is not None
    expected_keys = {
        "case_id",
        "stage",
        "category",
        "condition",
        "resolution",
        "confidence",
        "requires_human_review",
        "assigned_agent",
        "rule_evaluations_count",
        "evidence_count",
        "processing_notes_count",
        "created_at",
        "updated_at",
    }
    assert expected_keys == set(summary.keys())


# ---------------------------------------------------------------------------
# 11. Escalate to pre-arbitration
# ---------------------------------------------------------------------------

async def test_brain_escalate_pre_arbitration():
    brain = await _make_brain()
    case = _make_case(
        fraud_type_code=FraudTypeCode.ACCOUNT_TAKEOVER,
        statement="unauthorized transaction",
    )
    result = await brain.process_single(case)
    assert result.stage == DisputeLifecycleStage.RESOLVED

    escalated = await brain.escalate_to_pre_arbitration(result.case_id)
    assert escalated is not None
    assert escalated.stage in (
        DisputeLifecycleStage.PRE_ARBITRATION,
        DisputeLifecycleStage.PRE_ARBITRATION_RESPONSE,
        DisputeLifecycleStage.RESOLVED,
        DisputeLifecycleStage.HUMAN_REVIEW,
    )


# ---------------------------------------------------------------------------
# 12. Escalate to arbitration
# ---------------------------------------------------------------------------

async def test_brain_escalate_arbitration():
    brain = await _make_brain()
    case = _make_case(
        fraud_type_code=FraudTypeCode.ACCOUNT_TAKEOVER,
        statement="unauthorized transaction",
    )
    result = await brain.process_single(case)
    await brain.escalate_to_pre_arbitration(result.case_id)

    arb = await brain.escalate_to_arbitration(result.case_id)
    assert arb is not None
    assert arb.stage in (
        DisputeLifecycleStage.ARBITRATION,
        DisputeLifecycleStage.HUMAN_REVIEW,
    )


# ---------------------------------------------------------------------------
# 13. Human review - approve
# ---------------------------------------------------------------------------

async def test_brain_human_review_approve():
    brain = await _make_brain()
    # Use a fraud case without fraud_type_code or certification to trigger
    # low-confidence human review (missing docs path in the mock).
    case = _make_case(statement="unauthorized transaction")
    result = await brain.process_single(case)

    if result.stage != DisputeLifecycleStage.HUMAN_REVIEW:
        # Force into HUMAN_REVIEW for the test
        result.advance_stage(DisputeLifecycleStage.HUMAN_REVIEW, "Forced for test")

    approved = await brain.approve_human_review(result.case_id, approved=True)
    assert approved is not None
    assert approved.stage == DisputeLifecycleStage.RESOLVED


# ---------------------------------------------------------------------------
# 14. Human review - reject
# ---------------------------------------------------------------------------

async def test_brain_human_review_reject():
    brain = await _make_brain()
    case = _make_case(statement="unauthorized transaction")
    result = await brain.process_single(case)

    if result.stage != DisputeLifecycleStage.HUMAN_REVIEW:
        result.advance_stage(DisputeLifecycleStage.HUMAN_REVIEW, "Forced for test")

    rejected = await brain.approve_human_review(result.case_id, approved=False)
    assert rejected is not None
    assert rejected.stage == DisputeLifecycleStage.PROCESSING
    assert rejected.decision is None


# ---------------------------------------------------------------------------
# 15. Stage history recorded
# ---------------------------------------------------------------------------

async def test_brain_stage_history_recorded():
    brain = await _make_brain()
    case = _make_case(
        fraud_type_code=FraudTypeCode.ACCOUNT_TAKEOVER,
        statement="unauthorized transaction",
    )
    result = await brain.process_single(case)

    assert len(result.stage_history) > 0
    stages_visited = [entry["to_stage"] for entry in result.stage_history]
    assert "validation" in stages_visited
    assert "categorization" in stages_visited
