"""Shared test fixtures for the AI-powered dispute processing system.

Provides an autouse mock for chat_json that returns contextually appropriate
responses based on the system/user prompts, allowing all tests to run without
an actual OpenAI API key.
"""

import re
from datetime import datetime

import pytest


def _mock_chat_json(system_prompt: str, user_prompt: str, **kwargs: object) -> dict:
    """Smart mock for chat_json that returns contextually appropriate responses.

    Analyzes the system and user prompts to determine what kind of call is
    being made (categorization, agent evaluation, pre-arbitration) and returns
    a response that matches the expected format and is contextually sensible.
    """
    lower_system = system_prompt.lower()
    lower_user = user_prompt.lower()

    # Categorization call
    if "categorization" in lower_system:
        return _mock_categorization(lower_user, user_prompt)

    # Pre-arbitration / arbitration call
    if "pre-arbitration" in lower_system or "arbitration" in lower_system:
        return _mock_pre_arbitration(lower_user, user_prompt)

    # Agent evaluation calls - use specific phrases to avoid ambiguity
    # (e.g. "consumer disputes processing agent" contains "processing")
    if "consumer disputes" in lower_system:
        return _mock_consumer_evaluation(lower_user, user_prompt)

    if "fraud" in lower_system and "category 10" in lower_system:
        return _mock_fraud_evaluation(lower_user, user_prompt)

    if "authorization" in lower_system and "category 11" in lower_system:
        return _mock_authorization_evaluation(lower_user, user_prompt)

    if "processing error" in lower_system and "category 12" in lower_system:
        return _mock_processing_errors_evaluation(lower_user, user_prompt)

    # Default fallback
    return {
        "is_valid": True,
        "resolution": "issuer_win",
        "confidence": 0.85,
        "rationale": "Mock evaluation based on available case details",
        "rule_citations": [
            {
                "rule_section": "11.1",
                "rule_description": "General dispute rule",
                "is_satisfied": True,
                "details": "Mock rule evaluation",
            }
        ],
        "requires_human_review": False,
        "human_review_reason": None,
    }


def _mock_categorization(lower_user: str, user_prompt: str) -> dict:
    """Mock categorization response based on case details in the prompt."""

    # Check for fraud indicators
    fraud_type_match = re.search(r"fraud type code:\s*(\S+)", lower_user)
    has_fraud_type = fraud_type_match and fraud_type_match.group(1).lower() != "none"

    statement_match = re.search(r"cardholder statement:\s*(.+?)(?:\n|$)", user_prompt, re.IGNORECASE)
    statement = statement_match.group(1).lower() if statement_match else ""

    environment_match = re.search(r"environment:\s*(\S+)", lower_user)
    environment = environment_match.group(1) if environment_match else "ecommerce"

    is_recurring = "is recurring: true" in lower_user
    auth_code_match = re.search(r"authorization code:\s*(\S+)", lower_user)
    auth_code = auth_code_match.group(1) if auth_code_match else "none"
    auth_response_match = re.search(r"authorization response code:\s*(\S+)", lower_user)
    auth_response = auth_response_match.group(1) if auth_response_match else "none"

    is_chip_card = "is chip card: true" in lower_user
    is_chip_initiated = "is chip initiated: true" in lower_user

    # ATM environment -> 13.9
    if environment == "atm":
        return _cat_result("13", "13.9", 0.95, "ATM cash not received - consumer dispute 13.9")

    # Fraud type code present -> fraud
    if has_fraud_type:
        fraud_code = fraud_type_match.group(1) if fraud_type_match else ""
        # EMV counterfeit fraud (FraudTypeCode.COUNTERFEIT = '4')
        if fraud_code == "4" and environment == "card_present" and is_chip_card:
            if is_chip_initiated:
                # Still categorized as fraud but agent will reject
                return _cat_result("10", "10.1", 0.90, "EMV counterfeit fraud", ["10.5"])
            return _cat_result("10", "10.1", 0.95, "EMV counterfeit fraud at non-chip terminal", ["10.5"])
        # Lost/stolen card with chip -> 10.2
        # FraudTypeCode.LOST = '0', FraudTypeCode.STOLEN = '1'
        if fraud_code in ("0", "1") and is_chip_card:
            return _cat_result("10", "10.2", 0.90, "EMV non-counterfeit fraud (lost/stolen)")
        # Card-present fraud -> 10.3
        if environment == "card_present":
            return _cat_result("10", "10.3", 0.90, "Card-present fraud", ["10.5"])
        # Card-absent fraud -> 10.4
        return _cat_result("10", "10.4", 0.90, "Card-absent fraud (e-commerce/MOTO)", ["10.5"])

    # Statement-based fraud detection
    fraud_keywords = ["unauthorized", "did not authorize", "not mine", "identity theft",
                      "stolen card", "stolen", "fraud"]
    if any(kw in statement for kw in fraud_keywords) and ("counterfeit" not in statement or "card" in statement):
        if environment == "card_present":
            return _cat_result("10", "10.3", 0.85, "Statement indicates fraud - card present", ["10.5"])
        return _cat_result("10", "10.4", 0.85, "Statement indicates fraud - card absent", ["10.5"])

    # Authorization disputes
    if auth_response != "none" and not auth_response.startswith("0"):
        return _cat_result("11", "11.2", 0.92, "Declined authorization response code")

    auth_keywords = ["declined", "expired card"]
    if any(kw in statement for kw in auth_keywords):
        if auth_response != "none" and not auth_response.startswith("0"):
            return _cat_result("11", "11.2", 0.90, "Declined authorization")
        # Declined but no auth code means no valid authorization was obtained
        if auth_code == "none":
            return _cat_result("11", "11.3", 0.85, "Authorization declined - no valid authorization obtained")
        return _cat_result("11", "11.2", 0.80, "Statement indicates authorization issue")

    if "card recovery bulletin" in statement or "recovery bulletin" in statement:
        return _cat_result("11", "11.1", 0.90, "Card on recovery bulletin")

    if "no authorization" in statement and auth_code == "none":
        return _cat_result("11", "11.3", 0.90, "No authorization obtained")

    if auth_code == "none" and not is_recurring:
        # Only classify as auth issue if no stronger consumer signals
        consumer_keywords = ["not received", "never received", "did not arrive",
                            "cancel", "defective", "not as described", "counterfeit",
                            "fake", "refund", "return", "duplicate", "wrong amount",
                            "incorrect"]
        if not any(kw in statement for kw in consumer_keywords):
            return _cat_result("11", "11.3", 0.80, "No authorization code present")

    # Processing errors
    processing_keywords_map = {
        "duplicate": ("12", "12.6", "Duplicate processing"),
        "charged twice": ("12", "12.6", "Duplicate charge"),
        "paid by other means": ("12", "12.6", "Paid by other means"),
        "incorrect amount": ("12", "12.5", "Incorrect amount charged"),
        "wrong amount": ("12", "12.5", "Wrong amount charged"),
        "incorrect currency": ("12", "12.3", "Incorrect currency"),
        "wrong currency": ("12", "12.3", "Wrong currency"),
        "wrong account": ("12", "12.4", "Wrong account number"),
        "incorrect account": ("12", "12.4", "Incorrect account number"),
        "incorrect code": ("12", "12.2", "Incorrect transaction code"),
        "wrong code": ("12", "12.2", "Wrong transaction code"),
        "invalid data": ("12", "12.7", "Invalid transaction data"),
    }
    for kw, (cat, cond, rationale) in processing_keywords_map.items():
        if kw in statement:
            return _cat_result(cat, cond, 0.90, rationale)

    # Consumer disputes
    if "not received" in statement or "never received" in statement or "did not arrive" in statement:
        return _cat_result("13", "13.1", 0.90, "Merchandise/services not received")

    if is_recurring and ("cancel" in statement or "stopped" in statement):
        return _cat_result("13", "13.2", 0.90, "Cancelled recurring transaction")

    if "not as described" in statement or "defective" in statement or "different" in statement:
        return _cat_result("13", "13.3", 0.85, "Not as described or defective")

    if "counterfeit" in statement or "fake" in statement:
        return _cat_result("13", "13.4", 0.85, "Counterfeit merchandise")

    if "misrepresent" in statement or "misleading" in statement or "false" in statement:
        return _cat_result("13", "13.5", 0.80, "Misrepresentation")

    if "refund not" in statement or "credit not" in statement or "no refund" in statement:
        return _cat_result("13", "13.6", 0.85, "Credit not processed")

    if "cancel" in statement or "return" in statement:
        return _cat_result("13", "13.7", 0.80, "Cancelled merchandise/services")

    if "original credit" in statement or "oct" in statement:
        return _cat_result("13", "13.8", 0.80, "Original credit transaction not accepted")

    # Default to consumer dispute
    return _cat_result("13", "13.1", 0.50, "Unable to determine specific category; defaulting to consumer dispute")


def _cat_result(
    category: str, condition: str, confidence: float, rationale: str,
    alternatives: list[str] | None = None,
) -> dict:
    return {
        "category": category,
        "condition": condition,
        "confidence": confidence,
        "rationale": rationale,
        "alternative_conditions": alternatives or [],
    }


def _mock_fraud_evaluation(lower_user: str, user_prompt: str) -> dict:
    """Mock fraud agent evaluation."""
    # Check for time limit issues
    if _is_time_expired(user_prompt):
        return _agent_result(
            is_valid=False,
            validity_reason="Dispute filed outside time limit",
            resolution="invalid_dispute",
            confidence=0.99,
            rationale="Dispute filed outside the allowed 120-day time limit per Section 11.7",
        )

    # Check for invalid dispute conditions (e.g., chip-initiated 10.1)
    condition_match = re.search(r"condition:\s*(\S+)", lower_user)
    condition = condition_match.group(1) if condition_match else ""
    is_chip_initiated = "is chip initiated: true" in lower_user

    if condition == "10.1" and is_chip_initiated:
        return _agent_result(
            is_valid=False,
            validity_reason="EMV counterfeit fraud dispute invalid for chip-initiated transaction",
            resolution="invalid_dispute",
            confidence=0.95,
            rationale="Per Section 11.7, condition 10.1 is not valid when the transaction was chip-initiated",
        )

    # Check for missing documentation
    fraud_type_match = re.search(r"fraud type code:\s*(\S+)", lower_user)
    has_fraud_type = fraud_type_match and fraud_type_match.group(1).lower() != "none"

    statement_match = re.search(r"cardholder statement:\s*(.+?)(?:\n|$)", user_prompt, re.IGNORECASE)
    statement = statement_match.group(1).lower() if statement_match else ""

    has_certification = "issuer_certification" in lower_user or "certification" in statement

    # Check for high-value dispute
    amount_match = re.search(r"dispute amount:\s*(\d+\.?\d*)", lower_user)
    dispute_amount = float(amount_match.group(1)) if amount_match else 0

    if not has_fraud_type and not has_certification:
        return _agent_result(
            is_valid=True,
            resolution="issuer_win",
            confidence=0.60,
            rationale="Fraud dispute requires additional documentation. Provisional decision pending human review.",
            requires_human_review=True,
            human_review_reason="Missing fraud type code and/or certification",
            rule_ids=["time_limit_check", "documentation_check", "fraud_type_code_check"],
        )

    if dispute_amount > 25000:
        return _agent_result(
            is_valid=True,
            resolution="issuer_win",
            confidence=0.90,
            rationale="Fraud dispute validated. All checks passed. High-value dispute requires human review.",
            requires_human_review=True,
            human_review_reason="High-value dispute exceeds $25,000 threshold",
            rule_ids=["time_limit_check", "documentation_check", "fraud_type_code_check"],
        )

    return _agent_result(
        is_valid=True,
        resolution="issuer_win",
        confidence=0.90,
        rationale="Fraud dispute validated under Visa rules Section 11.7. All validity checks passed, documentation complete.",
        rule_ids=["time_limit_check", "documentation_check", "fraud_type_code_check"],
    )


def _mock_authorization_evaluation(lower_user: str, user_prompt: str) -> dict:
    """Mock authorization agent evaluation."""
    if _is_time_expired(user_prompt):
        return _agent_result(
            is_valid=False,
            validity_reason="Dispute filed outside time limit",
            resolution="invalid_dispute",
            confidence=0.99,
            rationale="Authorization dispute filed outside time limit per Section 11.8",
        )

    condition_match = re.search(r"condition:\s*(\S+)", lower_user)
    condition = condition_match.group(1) if condition_match else ""

    auth_code_match = re.search(r"authorization code:\s*(\S+)", lower_user)
    auth_code = auth_code_match.group(1) if auth_code_match else "none"
    auth_response_match = re.search(r"authorization response code:\s*(\S+)", lower_user)
    auth_response = auth_response_match.group(1) if auth_response_match else "none"

    # 11.1: CRB - check for CRB evidence
    if condition == "11.1":
        has_crb = "crb" in lower_user or "card recovery" in lower_user
        if has_crb:
            return _agent_result(is_valid=True, resolution="issuer_win", confidence=0.90,
                                rationale="Card on CRB with evidence provided")
        return _agent_result(is_valid=True, resolution="acquirer_win", confidence=0.85,
                            rationale="No CRB evidence provided - acquirer wins")

    # 11.2: Declined auth
    if condition == "11.2":
        if auth_response != "none" and auth_response.startswith("0"):
            return _agent_result(is_valid=False, validity_reason="Authorization was not actually declined",
                                resolution="invalid_dispute", confidence=0.95,
                                rationale="Auth response code indicates approval, not decline")
        return _agent_result(is_valid=True, resolution="issuer_win", confidence=0.90,
                            rationale="Authorization was declined per response code")

    # 11.3: No auth
    if condition == "11.3":
        if auth_code != "none":
            return _agent_result(is_valid=False, validity_reason="Authorization code exists",
                                resolution="invalid_dispute", confidence=0.95,
                                rationale="Authorization code present - dispute is invalid")
        return _agent_result(is_valid=True, resolution="issuer_win", confidence=0.90,
                            rationale="No authorization code found - dispute valid")

    return _agent_result(is_valid=True, resolution="issuer_win", confidence=0.85,
                        rationale="Authorization dispute validated")


def _mock_processing_errors_evaluation(lower_user: str, user_prompt: str) -> dict:
    """Mock processing errors agent evaluation."""
    if _is_time_expired(user_prompt):
        return _agent_result(
            is_valid=False,
            validity_reason="Dispute filed outside time limit",
            resolution="invalid_dispute",
            confidence=0.99,
            rationale="Processing error dispute filed outside time limit per Section 11.9",
        )

    condition_match = re.search(r"condition:\s*(\S+)", lower_user)
    condition = condition_match.group(1) if condition_match else ""

    # Check for amount evidence
    dispute_amount_match = re.search(r"dispute amount:\s*(\S+)", lower_user)
    dispute_amount = dispute_amount_match.group(1) if dispute_amount_match else "none"

    if condition == "12.5" and dispute_amount == "none":
        return _agent_result(
            is_valid=False,
            validity_reason="No disputed amount provided for incorrect amount claim",
            resolution="invalid_dispute",
            confidence=0.90,
            rationale="Condition 12.5 requires a dispute amount to compare",
        )

    return _agent_result(
        is_valid=True,
        resolution="issuer_win",
        confidence=0.90,
        rationale="Processing error dispute validated per Section 11.9",
    )


def _mock_consumer_evaluation(lower_user: str, user_prompt: str) -> dict:
    """Mock consumer disputes agent evaluation."""
    if _is_time_expired(user_prompt):
        return _agent_result(
            is_valid=False,
            validity_reason="Dispute filed outside time limit",
            resolution="invalid_dispute",
            confidence=0.99,
            rationale="Consumer dispute filed outside time limit per Section 11.10",
        )

    condition_match = re.search(r"condition:\s*(\S+)", lower_user)
    condition = condition_match.group(1) if condition_match else ""

    # 13.2: Cancelled recurring - check if actually recurring
    if condition == "13.2":
        is_recurring = "is recurring: true" in lower_user
        if not is_recurring:
            return _agent_result(
                is_valid=False,
                validity_reason="Transaction is not a recurring transaction",
                resolution="invalid_dispute",
                confidence=0.90,
                rationale="Condition 13.2 requires a recurring transaction",
            )

    return _agent_result(
        is_valid=True,
        resolution="issuer_win",
        confidence=0.88,
        rationale="Consumer dispute validated per Section 11.10",
    )


def _mock_pre_arbitration(lower_user: str, user_prompt: str) -> dict:
    """Mock pre-arbitration/arbitration evaluation."""
    # Detect the current stage from the prompt
    stage_match = re.search(r"current stage:\s*(\S+)", lower_user)
    stage = stage_match.group(1) if stage_match else ""

    # Check for compelling evidence
    has_compelling = "compelling: true" in lower_user or "is_compelling_evidence: true" in lower_user

    # Check for specific evidence types
    has_acceptance = "accepts" in lower_user or "acceptance" in lower_user
    has_certification = "certification" in lower_user and "none" not in lower_user.split("certification")[1][:10]
    has_withdrawal = "withdrawal" in lower_user or "no longer disputes" in lower_user
    has_credit_claim = "credit" in lower_user and "not addressed" in lower_user

    # Arbitration stage
    if stage == "arbitration":
        return {
            "has_compelling_evidence": False,
            "resolution": "escalated_arbitration",
            "confidence": 0.85,
            "rationale": "Case escalated to arbitration per Section 11.11",
            "rule_citations": [
                {
                    "rule_section": "11.11",
                    "rule_description": "Arbitration procedures",
                    "is_satisfied": True,
                    "details": "Pre-arbitration cycle completed, arbitration warranted",
                }
            ],
            "next_action": "human_review",
            "requires_human_review": True,
            "human_review_reason": "Arbitration cases require human oversight",
        }

    # Pre-arbitration response stage
    if stage == "pre_arbitration_response":
        if has_acceptance:
            return {
                "has_compelling_evidence": False,
                "resolution": "acquirer_win",
                "confidence": 0.90,
                "rationale": "Issuer accepted financial responsibility",
                "rule_citations": [
                    {
                        "rule_section": "11.5",
                        "rule_description": "Pre-arbitration response",
                        "is_satisfied": True,
                        "details": "Issuer accepted responsibility",
                    }
                ],
                "next_action": "resolved",
                "requires_human_review": False,
                "human_review_reason": None,
            }
        if has_certification:
            return {
                "has_compelling_evidence": False,
                "resolution": "escalated_arbitration",
                "confidence": 0.85,
                "rationale": "Issuer provided certification, escalating to arbitration",
                "rule_citations": [
                    {
                        "rule_section": "11.5",
                        "rule_description": "Pre-arbitration response with certification",
                        "is_satisfied": True,
                        "details": "Issuer certification provided",
                    }
                ],
                "next_action": "escalate_arbitration",
                "requires_human_review": True,
                "human_review_reason": "Arbitration filing decision required",
            }
        # No adequate response
        return {
            "has_compelling_evidence": False,
            "resolution": "acquirer_win",
            "confidence": 0.85,
            "rationale": "Issuer failed to provide adequate pre-arbitration response",
            "rule_citations": [
                {
                    "rule_section": "11.5",
                    "rule_description": "Pre-arbitration response requirements",
                    "is_satisfied": False,
                    "details": "No adequate response from issuer",
                }
            ],
            "next_action": "resolved",
            "requires_human_review": False,
            "human_review_reason": None,
        }

    # Pre-arbitration stage (default)
    if has_compelling:
        return {
            "has_compelling_evidence": True,
            "resolution": "acquirer_win",
            "confidence": 0.85,
            "rationale": "Acquirer provided compelling evidence per Section 11.5.2",
            "rule_citations": [
                {
                    "rule_section": "11.5.2",
                    "rule_description": "Compelling evidence requirements",
                    "is_satisfied": True,
                    "details": "Compelling evidence meets requirements",
                }
            ],
            "next_action": "awaiting_issuer_response",
            "requires_human_review": False,
            "human_review_reason": None,
        }

    if has_withdrawal:
        return {
            "has_compelling_evidence": False,
            "resolution": "withdrawn",
            "confidence": 0.90,
            "rationale": "Cardholder no longer disputes the transaction",
            "rule_citations": [
                {
                    "rule_section": "11.5",
                    "rule_description": "Dispute withdrawal",
                    "is_satisfied": True,
                    "details": "Cardholder withdrew the dispute",
                }
            ],
            "next_action": "resolved",
            "requires_human_review": False,
            "human_review_reason": None,
        }

    if has_credit_claim:
        return {
            "has_compelling_evidence": False,
            "resolution": "issuer_win",
            "confidence": 0.80,
            "rationale": "Credit not addressed in the dispute",
            "rule_citations": [
                {
                    "rule_section": "11.5",
                    "rule_description": "Credit not addressed",
                    "is_satisfied": True,
                    "details": "Credit was not addressed",
                }
            ],
            "next_action": "awaiting_issuer_response",
            "requires_human_review": False,
            "human_review_reason": None,
        }

    return {
        "has_compelling_evidence": False,
        "resolution": "issuer_win",
        "confidence": 0.80,
        "rationale": "No compelling evidence provided by acquirer",
        "rule_citations": [
            {
                "rule_section": "11.5.2",
                "rule_description": "Compelling evidence requirements",
                "is_satisfied": False,
                "details": "No compelling evidence provided",
            }
        ],
        "next_action": "resolved",
        "requires_human_review": False,
        "human_review_reason": None,
    }


def _agent_result(
    is_valid: bool = True,
    validity_reason: str = "",
    resolution: str = "issuer_win",
    confidence: float = 0.90,
    rationale: str = "Evaluation complete",
    requires_human_review: bool = False,
    human_review_reason: str | None = None,
    rule_ids: list[str] | None = None,
) -> dict:
    """Build a standard agent evaluation response."""
    if rule_ids is None:
        rule_ids = ["general_check"]

    citations = []
    for rule_id in rule_ids:
        citations.append({
            "rule_section": rule_id.replace("_", "."),
            "rule_description": f"Rule check: {rule_id}",
            "is_satisfied": is_valid,
            "details": rationale,
        })

    return {
        "is_valid": is_valid,
        "validity_reason": validity_reason,
        "resolution": resolution,
        "confidence": confidence,
        "rationale": rationale,
        "rule_citations": citations,
        "requires_human_review": requires_human_review,
        "human_review_reason": human_review_reason,
    }


def _is_time_expired(user_prompt: str) -> bool:
    """Check if the dispute was filed outside the time limit based on dates in the prompt."""
    processing_match = re.search(r"processing date:\s*(\d{4}-\d{2}-\d{2})", user_prompt, re.IGNORECASE)
    filed_match = re.search(r"dispute filed date:\s*(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})", user_prompt, re.IGNORECASE)

    if not processing_match or not filed_match:
        return False

    try:
        processing_date = datetime.strptime(processing_match.group(1), "%Y-%m-%d")
        filed_date = datetime.strptime(filed_match.group(1), "%Y-%m-%d %H:%M:%S")
        days_diff = (filed_date - processing_date).days
        return days_diff > 120
    except (ValueError, TypeError):
        return False


@pytest.fixture(autouse=True)
def _mock_openai_chat(monkeypatch: pytest.MonkeyPatch) -> None:
    """Auto-mock chat_json for all tests so no real OpenAI API key is needed.

    We patch at every location where chat_json is imported:
    - src.llm.openai_client (source module)
    - src.agents.base_agent (imported by all agents)
    - src.rules.categorizer (imported for categorization)
    """
    monkeypatch.setattr("src.llm.openai_client.chat_json", _mock_chat_json)
    monkeypatch.setattr("src.agents.base_agent.chat_json", _mock_chat_json)
    monkeypatch.setattr("src.agents.pre_arbitration_agent.chat_json", _mock_chat_json)
    monkeypatch.setattr("src.rules.categorizer.chat_json", _mock_chat_json)


@pytest.fixture(autouse=True)
def _mock_visa_rules_loading(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mock visa rules loading to avoid reading the full document in tests."""
    def mock_get_section(section_number: str) -> str:
        return f"[Mock Visa Rules Section {section_number}]"

    def mock_get_categorization_context() -> str:
        return "[Mock Categorization Context - All Visa dispute categories and conditions]"

    def mock_get_rules() -> str:
        return "[Mock Rules Section]"

    # Patch at source module
    monkeypatch.setattr("src.llm.visa_rules.get_section", mock_get_section)
    monkeypatch.setattr("src.llm.visa_rules.get_categorization_context", mock_get_categorization_context)
    monkeypatch.setattr("src.llm.visa_rules.get_fraud_rules", mock_get_rules)
    monkeypatch.setattr("src.llm.visa_rules.get_authorization_rules", mock_get_rules)
    monkeypatch.setattr("src.llm.visa_rules.get_processing_errors_rules", mock_get_rules)
    monkeypatch.setattr("src.llm.visa_rules.get_consumer_disputes_rules", mock_get_rules)
    monkeypatch.setattr("src.llm.visa_rules.get_arbitration_rules", mock_get_rules)
    monkeypatch.setattr("src.llm.visa_rules.get_compelling_evidence_rules", mock_get_rules)
    monkeypatch.setattr("src.llm.visa_rules.get_dispute_overview", mock_get_rules)

    # Patch where imported directly in agent/categorizer modules
    monkeypatch.setattr("src.rules.categorizer.get_categorization_context", mock_get_categorization_context)
    monkeypatch.setattr("src.agents.fraud_agent.get_fraud_rules", mock_get_rules)
    monkeypatch.setattr("src.agents.authorization_agent.get_authorization_rules", mock_get_rules)
    monkeypatch.setattr("src.agents.processing_errors_agent.get_processing_errors_rules", mock_get_rules)
    monkeypatch.setattr("src.agents.consumer_disputes_agent.get_consumer_disputes_rules", mock_get_rules)
    monkeypatch.setattr("src.agents.pre_arbitration_agent.get_arbitration_rules", mock_get_rules)
    monkeypatch.setattr("src.agents.pre_arbitration_agent.get_compelling_evidence_rules", mock_get_rules)
