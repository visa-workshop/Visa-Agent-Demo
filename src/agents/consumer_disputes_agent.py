"""AI-powered consumer disputes processing agent (Category 13).

Uses OpenAI to reason over Visa Core Rules Section 11.10 to evaluate
consumer disputes and render decisions.

Handles consumer dispute conditions:
- 13.1: Merchandise/Services Not Received
- 13.2: Cancelled Recurring Transaction
- 13.3: Not as Described or Defective Merchandise/Services
- 13.4: Counterfeit Merchandise
- 13.5: Misrepresentation
- 13.6: Credit Not Processed
- 13.7: Cancelled Merchandise/Services
- 13.8: Original Credit Transaction Not Accepted
- 13.9: Non-Receipt of Cash at an ATM
"""

from src.agents.base_agent import BaseDisputeAgent
from src.llm.visa_rules import get_consumer_disputes_rules
from src.models.dispute import DisputeCase, RuleEvaluationResult
from src.models.enums import (
    AgentType,
    DisputeCategory,
    DisputeLifecycleStage,
    DisputeResolution,
)

# TODO: Define _CONSUMER_SYSTEM_PROMPT — instruct the LLM to evaluate consumer
# disputes according to Visa Core Rules Section 11.10. Include condition-specific
# checks for all 13.x conditions. Require JSON output with same schema as other agents.
_CONSUMER_SYSTEM_PROMPT = (
    "You are a Visa consumer disputes processing agent for Category 13 (Consumer Disputes). "
    "Evaluate the dispute according to Visa Core Rules Section 11.10.\n\n"
    "Check condition-specific requirements for all 13.x conditions including:\n"
    "- 13.1: Merchandise/Services Not Received\n"
    "- 13.2: Cancelled Recurring Transaction\n"
    "- 13.3: Not as Described or Defective\n"
    "- 13.4: Counterfeit Merchandise\n"
    "- 13.5: Misrepresentation\n"
    "- 13.6: Credit Not Processed\n"
    "- 13.7: Cancelled Merchandise/Services\n"
    "- 13.8: Original Credit Transaction Not Accepted\n"
    "- 13.9: Non-Receipt of Cash at ATM\n\n"
    "Return JSON with: is_valid (bool), validity_reason (str), resolution (str), "
    "confidence (float 0-1), rationale (str), rule_citations (list of objects with "
    "rule_section, rule_description, is_satisfied, details), requires_human_review (bool), "
    "human_review_reason (str or null)"
)


class ConsumerDisputesAgent(BaseDisputeAgent):
    """AI-powered agent specializing in Category 13 (Consumer Disputes)."""

    def __init__(self) -> None:
        super().__init__(AgentType.CONSUMER_DISPUTES)

    async def validate(self, case: DisputeCase) -> bool:
        """Validate this agent can handle the case.

        TODO: Return True only if case.condition belongs to DisputeCategory.CONSUMER_DISPUTES.
        """
        if case.condition is None:
            return False
        return case.condition.category == DisputeCategory.CONSUMER_DISPUTES

    async def process(self, case: DisputeCase) -> DisputeCase:
        """Process a consumer dispute using AI reasoning over Visa rules.

        TODO: Follow the same pattern as FraudDisputeAgent.process():
        Use get_consumer_disputes_rules() for rules context and
        _CONSUMER_SYSTEM_PROMPT for the system prompt.
        """
        case.assigned_agent = self.agent_type.value
        case.advance_stage(DisputeLifecycleStage.RULE_EVALUATION, "Starting consumer disputes rule evaluation")

        rules_context = get_consumer_disputes_rules()
        result = self._evaluate_dispute_with_llm(case, rules_context, _CONSUMER_SYSTEM_PROMPT)

        rule_evaluations = []
        for citation in result.get("rule_citations", []):
            evaluation = RuleEvaluationResult(
                rule_id=citation.get("rule_section", "unknown"),
                rule_section=citation.get("rule_section", "unknown"),
                rule_description=citation.get("rule_description", ""),
                is_satisfied=citation.get("is_satisfied", False),
                details=citation.get("details", ""),
            )
            case.add_rule_evaluation(evaluation)
            rule_evaluations.append(evaluation)

        case.advance_stage(DisputeLifecycleStage.DECISION, "Rule evaluation complete")

        if not result.get("is_valid", True):
            decision = self.create_decision(
                resolution=DisputeResolution.INVALID_DISPUTE,
                rationale=result.get("validity_reason", result.get("rationale", "Invalid dispute")),
                rule_evaluations=rule_evaluations,
                confidence=result.get("confidence", 0.95),
            )
            case.decision = decision
            case.advance_stage(DisputeLifecycleStage.RESOLVED, "Invalid dispute")
            return case

        confidence = result.get("confidence", 0.85)
        resolution_str = result.get("resolution", "issuer_win")
        resolution, fallback_review, fallback_reason = self._parse_resolution(resolution_str)
        requires_human = result.get("requires_human_review", False) or fallback_review
        human_reason = result.get("human_review_reason") or fallback_reason

        if not requires_human:
            requires_human = self._should_escalate_to_human(confidence, case)
            if requires_human:
                human_reason = "Low confidence or high-value dispute"

        decision = self.create_decision(
            resolution=resolution,
            rationale=result.get("rationale", "Consumer disputes evaluation complete"),
            rule_evaluations=rule_evaluations,
            confidence=confidence,
            requires_human_review=requires_human,
            human_review_reason=human_reason,
        )
        case.decision = decision

        if requires_human:
            case.advance_stage(DisputeLifecycleStage.HUMAN_REVIEW, human_reason or "Requires human review")
        else:
            case.advance_stage(DisputeLifecycleStage.RESOLVED, "Consumer dispute resolved")

        return case
