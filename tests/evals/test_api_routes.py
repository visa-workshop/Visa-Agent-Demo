"""Eval tests for FastAPI API routes.

Validates that the API endpoints correctly handle requests and return
proper responses. Uses httpx.AsyncClient with ASGITransport for async testing.
"""

import httpx
import pytest
from httpx import ASGITransport

from src.api.routes import set_brain
from src.app import app
from src.orchestrator.brain import DisputeBrain
from src.queue.task_queue import DisputeTaskQueue


@pytest.fixture
async def client():
    queue = DisputeTaskQueue()
    brain = DisputeBrain(queue)
    await brain.start()
    set_brain(brain)
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    await brain.stop()


def _fraud_dispute_payload():
    return {
        "transaction": {
            "transaction_id": "TXN-API-001",
            "transaction_date": "2026-02-15",
            "processing_date": "2026-02-16",
            "amount": 500.00,
            "currency": "USD",
            "merchant_name": "FraudMerchant",
            "merchant_category_code": "5411",
            "merchant_country": "US",
            "acquirer_bin": "411111",
            "issuer_bin": "422222",
            "environment": "ecommerce",
        },
        "cardholder": {
            "cardholder_name": "Test User",
            "partial_payment_credential": "****1234",
            "cardholder_statement": "unauthorized transaction on my account",
        },
        "fraud_type_code": "7",  # ACCOUNT_TAKEOVER
    }


def _consumer_dispute_payload():
    return {
        "transaction": {
            "transaction_id": "TXN-API-002",
            "transaction_date": "2026-02-15",
            "processing_date": "2026-02-16",
            "amount": 200.00,
            "currency": "USD",
            "merchant_name": "ConsumerMerchant",
            "merchant_category_code": "5411",
            "merchant_country": "US",
            "acquirer_bin": "411111",
            "issuer_bin": "422222",
            "environment": "ecommerce",
            "authorization_code": "ABC",
            "authorization_response_code": "00",
        },
        "cardholder": {
            "cardholder_name": "Test User",
            "partial_payment_credential": "****1234",
            "cardholder_statement": "merchandise not received",
        },
    }


def _human_review_dispute_payload():
    """Fraud case without fraud_type_code and without issuer_certification
    to trigger human review due to missing docs."""
    return {
        "transaction": {
            "transaction_id": "TXN-API-HR",
            "transaction_date": "2026-02-15",
            "processing_date": "2026-02-16",
            "amount": 500.00,
            "currency": "USD",
            "merchant_name": "FraudMerchant",
            "merchant_category_code": "5411",
            "merchant_country": "US",
            "acquirer_bin": "411111",
            "issuer_bin": "422222",
            "environment": "ecommerce",
        },
        "cardholder": {
            "cardholder_name": "Test User",
            "partial_payment_credential": "****1234",
            "cardholder_statement": "unauthorized transaction on my account",
        },
        # No fraud_type_code, no issuer_certification -> triggers human review
    }


async def _submit_and_get_case_id(client: httpx.AsyncClient, payload: dict) -> str:
    """Helper: submit a dispute and return the case_id."""
    resp = await client.post("/api/v1/disputes", json=payload)
    assert resp.status_code == 200
    return resp.json()["case_id"]


# ── Test 1: Health check ──────────────────────────────────────────────


async def test_health_check(client: httpx.AsyncClient):
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"


# ── Test 2: Submit fraud dispute ──────────────────────────────────────


async def test_submit_dispute_fraud(client: httpx.AsyncClient):
    response = await client.post("/api/v1/disputes", json=_fraud_dispute_payload())
    assert response.status_code == 200
    data = response.json()
    assert "case_id" in data
    assert "stage" in data
    assert "category" in data


# ── Test 3: Submit consumer dispute ───────────────────────────────────


async def test_submit_dispute_consumer(client: httpx.AsyncClient):
    response = await client.post("/api/v1/disputes", json=_consumer_dispute_payload())
    assert response.status_code == 200
    data = response.json()
    assert data["category"] == "13"


# ── Test 4: List disputes ────────────────────────────────────────────


async def test_list_disputes(client: httpx.AsyncClient):
    # Submit at least one dispute first
    await client.post("/api/v1/disputes", json=_fraud_dispute_payload())
    response = await client.get("/api/v1/disputes")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 1


# ── Test 5: Get dispute detail ───────────────────────────────────────


async def test_get_dispute_detail(client: httpx.AsyncClient):
    case_id = await _submit_and_get_case_id(client, _fraud_dispute_payload())
    response = await client.get(f"/api/v1/disputes/{case_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["case_id"] == case_id
    assert "stage" in data
    assert "transaction_id" in data
    assert "rule_evaluations" in data
    assert "evidence" in data
    assert "created_at" in data
    assert "updated_at" in data


# ── Test 6: Get dispute not found ────────────────────────────────────


async def test_get_dispute_not_found(client: httpx.AsyncClient):
    response = await client.get("/api/v1/disputes/nonexistent-id")
    assert response.status_code == 404


# ── Test 7: Human review approve ────────────────────────────────────


async def test_human_review_approve(client: httpx.AsyncClient):
    # Submit a fraud case without fraud_type_code/issuer_certification to trigger human review
    case_id = await _submit_and_get_case_id(client, _human_review_dispute_payload())

    # Verify the case is in human review stage
    detail_resp = await client.get(f"/api/v1/disputes/{case_id}")
    assert detail_resp.status_code == 200
    assert detail_resp.json()["stage"] == "human_review"

    # Approve the human review
    response = await client.post(
        f"/api/v1/disputes/{case_id}/review",
        json={"approved": True, "reviewer_notes": "Looks good"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["stage"] == "resolved"


# ── Test 8: Human review not found ──────────────────────────────────


async def test_human_review_not_found(client: httpx.AsyncClient):
    response = await client.post(
        "/api/v1/disputes/bad-id/review",
        json={"approved": True, "reviewer_notes": "test"},
    )
    assert response.status_code == 404


# ── Test 9: Escalate to pre-arbitration ──────────────────────────────


async def test_escalate_pre_arbitration(client: httpx.AsyncClient):
    # Submit and resolve a case first
    case_id = await _submit_and_get_case_id(client, _fraud_dispute_payload())

    # Escalate to pre-arbitration with acquirer evidence
    response = await client.post(
        f"/api/v1/disputes/{case_id}/pre-arbitration",
        json={
            "acquirer_evidence": [
                {
                    "description": "Counter evidence",
                    "evidence_type": "document",
                    "provided_by": "acquirer",
                }
            ]
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert "stage" in data
    assert "case_id" in data


# ── Test 10: Escalate to arbitration ─────────────────────────────────


async def test_escalate_arbitration(client: httpx.AsyncClient):
    # Submit a case, then pre-arb, then arbitration
    case_id = await _submit_and_get_case_id(client, _fraud_dispute_payload())

    # Pre-arbitration first
    pre_arb_resp = await client.post(
        f"/api/v1/disputes/{case_id}/pre-arbitration",
        json={
            "acquirer_evidence": [
                {
                    "description": "Counter evidence",
                    "evidence_type": "document",
                    "provided_by": "acquirer",
                }
            ]
        },
    )
    assert pre_arb_resp.status_code == 200

    # Now escalate to arbitration
    response = await client.post(f"/api/v1/disputes/{case_id}/arbitration")
    assert response.status_code == 200
    data = response.json()
    assert "stage" in data
    assert "case_id" in data


# ── Test 11: Add evidence ────────────────────────────────────────────


async def test_add_evidence(client: httpx.AsyncClient):
    case_id = await _submit_and_get_case_id(client, _fraud_dispute_payload())

    # Check initial evidence count
    detail_resp = await client.get(f"/api/v1/disputes/{case_id}")
    initial_evidence_count = len(detail_resp.json()["evidence"])

    # Add evidence
    response = await client.post(
        f"/api/v1/disputes/{case_id}/evidence",
        json={
            "description": "Additional docs",
            "evidence_type": "document",
            "provided_by": "issuer",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["evidence_count"] > initial_evidence_count


# ── Test 12: Queue stats ────────────────────────────────────────────


async def test_queue_stats(client: httpx.AsyncClient):
    response = await client.get("/api/v1/queue/stats")
    assert response.status_code == 200
    data = response.json()
    assert "queue_depth" in data
    assert "stats" in data
