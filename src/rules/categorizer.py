"""AI-powered dispute categorization engine.

Uses OpenAI to analyze incoming dispute cases against the Visa Core Rules
document (Section 11.6-11.10) and determine the appropriate dispute category
and condition.

This replaces the previous hardcoded rules engine with an LLM-powered
approach that reasons directly over the Visa rules text.
"""

import logging
from dataclasses import dataclass

from src.llm.openai_client import chat_json
from src.llm.visa_rules import get_categorization_context
from src.models.dispute import DisputeCase
from src.models.enums import (
    DisputeCategory,
    DisputeCondition,
)

logger = logging.getLogger(__name__)


@dataclass
class CategorizationResult:
    """Result of dispute categorization."""

    category: DisputeCategory
    condition: DisputeCondition
    confidence: float
    rationale: str
    alternative_conditions: list[DisputeCondition]


# TODO: Define _SYSTEM_PROMPT — a system prompt that instructs the LLM to categorize
# disputes into one of the 4 Visa categories (10-Fraud, 11-Authorization,
# 12-Processing Errors, 13-Consumer Disputes) and their specific conditions.
#
# The prompt should:
# 1. List all valid categories and conditions
# 2. Explain key categorization principles from the Visa rules
# 3. Clarify important distinctions (e.g., counterfeit merchandise vs counterfeit card)
# 4. Require JSON output with: category, condition, confidence, rationale, alternative_conditions
_SYSTEM_PROMPT = (
    "You are a Visa dispute categorization specialist. Categorize the dispute into one of "
    "the 4 Visa categories:\n"
    "- 10 (Fraud): Conditions 10.1-10.5\n"
    "- 11 (Authorization): Conditions 11.1-11.3\n"
    "- 12 (Processing Errors): Conditions 12.2-12.7\n"
    "- 13 (Consumer Disputes): Conditions 13.1-13.9\n\n"
    "Key principles:\n"
    "- Counterfeit merchandise (fake goods) is 13.4, NOT 10.1 (counterfeit card fraud)\n"
    "- Fraud requires unauthorized use indicators or fraud type codes\n"
    "- Authorization issues involve declined/missing authorizations\n"
    "- Processing errors involve incorrect amounts, currencies, duplicates\n\n"
    "Return JSON with: category, condition, confidence (0-1), rationale, alternative_conditions (list)"
)


def categorize_dispute(case: DisputeCase) -> CategorizationResult:
    """Categorize a dispute using OpenAI reasoning over Visa rules.

    The LLM analyzes the transaction details, cardholder statement, evidence,
    and fraud indicators against the Visa Core Rules to determine the
    appropriate dispute category and condition.

    TODO: Implement this function:
    1. Build a user prompt with case details using _build_case_prompt()
    2. Call chat_json() with the system prompt and user prompt
    3. Parse the JSON response into a CategorizationResult
    """
    user_prompt = _build_case_prompt(case)
    result = chat_json(_SYSTEM_PROMPT, user_prompt)

    return CategorizationResult(
        category=DisputeCategory(result["category"]),
        condition=DisputeCondition(result["condition"]),
        confidence=float(result["confidence"]),
        rationale=str(result["rationale"]),
        alternative_conditions=[
            DisputeCondition(c) for c in result.get("alternative_conditions", [])
        ],
    )


def _build_case_prompt(case: DisputeCase) -> str:
    """Build the user prompt with case details and relevant Visa rules context.

    TODO: Implement this function to format the dispute case into a prompt:
    - Include transaction details (ID, amount, merchant, dates, environment, etc.)
    - Include cardholder statement and fraud type code
    - Include evidence summary
    - Append the Visa rules context from get_categorization_context()
    """
    rules_context = get_categorization_context()
    fraud_type = case.fraud_type_code.value if case.fraud_type_code else "None"
    statement = case.cardholder.cardholder_statement or "None"
    evidence_summary = "; ".join(e.description for e in case.evidence) or "None"

    return (
        f"Transaction ID: {case.transaction.transaction_id}\n"
        f"Amount: {case.transaction.amount} {case.transaction.currency}\n"
        f"Merchant: {case.transaction.merchant_name}\n"
        f"Transaction Date: {case.transaction.transaction_date}\n"
        f"Processing Date: {case.transaction.processing_date}\n"
        f"Environment: {case.transaction.environment.value}\n"
        f"Is Chip Card: {case.transaction.is_chip_card}\n"
        f"Is Chip Initiated: {case.transaction.is_chip_initiated}\n"
        f"Is Recurring: {case.transaction.is_recurring}\n"
        f"Authorization Code: {case.transaction.authorization_code or 'None'}\n"
        f"Authorization Response Code: {case.transaction.authorization_response_code or 'None'}\n"
        f"Fraud Type Code: {fraud_type}\n"
        f"Cardholder Statement: {statement}\n"
        f"Evidence: {evidence_summary}\n\n"
        f"Visa Rules Context:\n{rules_context}"
    )
