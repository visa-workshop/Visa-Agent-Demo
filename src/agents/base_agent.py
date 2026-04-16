"""Base agent class for AI-powered dispute processing sub-agents.

Each agent uses OpenAI to reason over the Visa Core Rules document
to validate disputes and render decisions.
"""

import logging
import time
from abc import ABC, abstractmethod
from typing import Any

from src.llm.openai_client import chat_json
from src.models.dispute import DisputeCase, DisputeDecision, RuleEvaluationResult
from src.models.enums import (
    AgentType,
    DisputeResolution,
)


class BaseDisputeAgent(ABC):
    """Abstract base class for all dispute processing sub-agents.

    Each sub-agent specializes in processing disputes for a specific
    category or lifecycle stage. Sub-agents use OpenAI to reason over
    the Visa Core Rules document and render decisions.
    """

    def __init__(self, agent_type: AgentType) -> None:
        self.agent_type = agent_type
        self.logger = logging.getLogger(f"agent.{agent_type.value}")

    @abstractmethod
    async def process(self, case: DisputeCase) -> DisputeCase:
        """Process a dispute case through this agent's specialized logic."""
        ...

    @abstractmethod
    async def validate(self, case: DisputeCase) -> bool:
        """Validate that this agent can handle the given case."""
        ...

    def create_decision(
        self,
        resolution: DisputeResolution,
        rationale: str,
        rule_evaluations: list[RuleEvaluationResult],
        confidence: float,
        requires_human_review: bool = False,
        human_review_reason: str | None = None,
    ) -> DisputeDecision:
        """Create a dispute decision with proper audit trail.

        TODO: Implement this method to return a DisputeDecision with:
        - The given resolution, rationale, confidence
        - rule_citations from rule_evaluations
        - Human review flags
        - decided_by set to self.agent_type.value
        """
        decision = DisputeDecision(
            resolution=resolution,
            rationale=rationale,
            rule_citations=rule_evaluations,
            confidence_score=confidence,
            requires_human_review=requires_human_review,
            human_review_reason=human_review_reason,
            decided_by=self.agent_type.value,
        )
        self.logger.info(
            "Decision created: resolution=%s, confidence_score=%.2f, "
            "decided_by=%s, requires_human_review=%s",
            resolution.value,
            confidence,
            self.agent_type.value,
            requires_human_review,
        )
        if requires_human_review:
            self.logger.warning(
                "Decision requires human review: reason=%s",
                human_review_reason,
            )
        return decision

    def _should_escalate_to_human(self, confidence: float, case: DisputeCase) -> bool:
        """Determine if a case should be escalated to human review.

        TODO: Implement escalation logic:
        - Confidence below 0.70 -> escalate
        - Dispute amount over $25,000 -> escalate
        """
        dispute_amount = case.dispute_amount
        self.logger.info(
            "Escalation check: confidence=%.2f, dispute_amount=%s",
            confidence,
            dispute_amount,
        )
        if confidence < 0.70:
            self.logger.warning(
                "Escalating to human: low confidence %.2f (threshold 0.70)",
                confidence,
            )
            return True
        if dispute_amount is not None and dispute_amount > 25000:
            self.logger.warning(
                "Escalating to human: high dispute amount $%.2f (threshold $25,000)",
                dispute_amount,
            )
            return True
        self.logger.info("No escalation needed")
        return False

    def _evaluate_dispute_with_llm(
        self,
        case: DisputeCase,
        rules_context: str,
        system_prompt: str,
    ) -> dict[str, Any]:
        """Use OpenAI to evaluate a dispute against the Visa rules.

        TODO: Implement this method:
        1. Build a user prompt with all case details (case ID, category, condition,
           transaction details, cardholder statement, evidence, etc.)
        2. Append the rules_context as reference
        3. Call chat_json(system_prompt, user_prompt) and return the result
        """
        category = case.category.value if case.category else "Unknown"
        condition = case.condition.value if case.condition else "Unknown"
        self.logger.info(
            "Evaluating dispute with LLM: case_id=%s, category=%s, condition=%s",
            case.case_id,
            category,
            condition,
        )
        statement = case.cardholder.cardholder_statement or "None"
        fraud_type = case.fraud_type_code.value if case.fraud_type_code else "None"
        evidence_lines = "\n".join(
            f"  - [{e.provided_by}] {e.description} (compelling: {e.is_compelling_evidence})"
            for e in case.evidence
        ) or "  None"
        dispute_amount = case.dispute_amount if case.dispute_amount is not None else "none"
        dispute_filed = case.dispute_filed_date.strftime("%Y-%m-%d %H:%M:%S") if case.dispute_filed_date else "Unknown"

        user_prompt = (
            f"Case ID: {case.case_id}\n"
            f"Category: {category}\n"
            f"Condition: {condition}\n"
            f"Transaction ID: {case.transaction.transaction_id}\n"
            f"Amount: {case.transaction.amount} {case.transaction.currency}\n"
            f"Dispute Amount: {dispute_amount}\n"
            f"Merchant: {case.transaction.merchant_name}\n"
            f"Transaction Date: {case.transaction.transaction_date}\n"
            f"Processing Date: {case.transaction.processing_date}\n"
            f"Dispute Filed Date: {dispute_filed}\n"
            f"Environment: {case.transaction.environment.value}\n"
            f"Is Chip Card: {case.transaction.is_chip_card}\n"
            f"Is Chip Initiated: {case.transaction.is_chip_initiated}\n"
            f"Is Recurring: {case.transaction.is_recurring}\n"
            f"Authorization Code: {case.transaction.authorization_code or 'None'}\n"
            f"Authorization Response Code: {case.transaction.authorization_response_code or 'None'}\n"
            f"Fraud Type Code: {fraud_type}\n"
            f"Issuer Certification: {case.issuer_certification or 'None'}\n"
            f"Cardholder Statement: {statement}\n"
            f"Evidence:\n{evidence_lines}\n\n"
            f"Visa Rules Reference:\n{rules_context}"
        )

        start_time = time.time()
        try:
            result = chat_json(system_prompt, user_prompt)
        except Exception:
            elapsed = time.time() - start_time
            self.logger.error(
                "LLM call failed after %.2fs for case_id=%s",
                elapsed,
                case.case_id,
            )
            raise
        elapsed = time.time() - start_time
        self.logger.info(
            "LLM call completed in %.2fs: resolution=%s, confidence=%s, is_valid=%s",
            elapsed,
            result.get("resolution"),
            result.get("confidence"),
            result.get("is_valid"),
        )
        return result
