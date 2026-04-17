"""AI-powered authorization dispute processing agent (Category 11).

Uses OpenAI to reason over Visa Core Rules Section 11.8 to evaluate
authorization disputes and render decisions.

Handles authorization-related disputes:
- 11.1: Card Recovery Bulletin
- 11.2: Declined Authorization
- 11.3: No Authorization / Late Presentment
"""

from src.agents.base_agent import BaseDisputeAgent
from src.llm.visa_rules import get_authorization_rules
from src.models.dispute import DisputeCase, RuleEvaluationResult
from src.models.enums import (
    AgentType,
    DisputeCategory,
    DisputeLifecycleStage,
    DisputeResolution,
)

# TODO: Define _AUTH_SYSTEM_PROMPT — instruct the LLM to evaluate authorization
# disputes according to Visa Core Rules Section 11.8. Include authorization-specific
# checks for CRB (11.1), declined auth (11.2), and no auth (11.3).
# Require JSON output matching the same schema as the fraud agent.
_AUTH_SYSTEM_PROMPT = (
    "You are a Visa authorization dispute processing agent for Category 11 (Authorization) disputes. "
    "Evaluate the dispute according to Visa Core Rules Section 11.8.\n\n"
    "Check authorization-specific conditions:\n"
    "- 11.1: Card Recovery Bulletin (CRB)\n"
    "- 11.2: Declined Authorization\n"
    "- 11.3: No Authorization / Late Presentment\n\n"
    "Return JSON with: is_valid (bool), validity_reason (str), resolution (str), "
    "confidence (float 0-1), rationale (str), rule_citations (list of objects with "
    "rule_section, rule_description, is_satisfied, details), requires_human_review (bool), "
    "human_review_reason (str or null)"
)


class AuthorizationDisputeAgent(BaseDisputeAgent):
    """AI-powered agent specializing in Category 11 (Authorization) disputes."""

    def __init__(self) -> None:
        super().__init__(AgentType.AUTHORIZATION)

    async def validate(self, case: DisputeCase) -> bool:
        """Validate this agent can handle the case.

        TODO: Return True only if case.condition belongs to DisputeCategory.AUTHORIZATION.
        """
        if case.condition is None:
            return False
        return case.condition.category == DisputeCategory.AUTHORIZATION

    async def process(self, case: DisputeCase) -> DisputeCase:
        """Process an authorization dispute using AI reasoning over Visa rules.

        TODO: Follow the same pattern as FraudDisputeAgent.process():
        1. Set assigned_agent, advance to RULE_EVALUATION
        2. Get rules via get_authorization_rules()
        3. Call _evaluate_dispute_with_llm()
        4. Parse citations, advance to DECISION
        5. Handle invalid disputes vs valid decisions
        6. Check human escalation, advance to final stage
        """
        case.assigned_agent = self.agent_type.value
        case.advance_stage(DisputeLifecycleStage.RULE_EVALUATION, "Starting authorization rule evaluation")

        rules_context = get_authorization_rules()
        result = self._evaluate_dispute_with_llm(case, rules_context, _AUTH_SYSTEM_PROMPT)

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
            rationale=result.get("rationale", "Authorization evaluation complete"),
            rule_evaluations=rule_evaluations,
            confidence=confidence,
            requires_human_review=requires_human,
            human_review_reason=human_reason,
        )
        case.decision = decision

        if requires_human:
            case.advance_stage(DisputeLifecycleStage.HUMAN_REVIEW, human_reason or "Requires human review")
        else:
            case.advance_stage(DisputeLifecycleStage.RESOLVED, "Authorization dispute resolved")

        return case
