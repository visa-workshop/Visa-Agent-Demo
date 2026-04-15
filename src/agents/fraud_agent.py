"""AI-powered fraud dispute processing agent (Category 10).

Uses OpenAI to reason over Visa Core Rules Section 11.7 to evaluate
fraud disputes and render decisions.

Handles all fraud-related disputes including:
- 10.1: EMV Liability Shift Counterfeit Fraud
- 10.2: EMV Liability Shift Non-Counterfeit Fraud
- 10.3: Other Fraud - Card-Present Environment
- 10.4: Other Fraud - Card-Absent Environment
- 10.5: Visa Fraud Monitoring Program
"""

from typing import Any

from src.agents.base_agent import BaseDisputeAgent
from src.instrumentation.tracing import (
    record_agent_decision,
    record_agent_validation,
    trace_agent_process,
    trace_llm_call,
)
from src.llm.visa_rules import get_fraud_rules
from src.models.dispute import DisputeCase, RuleEvaluationResult
from src.models.enums import (
    AgentType,
    DisputeCategory,
    DisputeLifecycleStage,
    DisputeResolution,
)

# TODO: Define _FRAUD_SYSTEM_PROMPT — instruct the LLM to evaluate fraud disputes
# according to Visa Core Rules Section 11.7. The prompt should tell the LLM to:
# 1. Check validity (invalid dispute conditions per Section 11.7)
# 2. Check time limits
# 3. Check required documentation and fraud type code
# 4. Check EMV liability shift (conditions 10.1, 10.2)
# 5. Assess evidence strength
# 6. Return JSON with: is_valid, validity_reason, resolution, confidence,
#    rationale, rule_citations[], requires_human_review, human_review_reason
_FRAUD_SYSTEM_PROMPT = (
    "You are a Visa fraud dispute processing agent for Category 10 (Fraud) disputes. "
    "Evaluate the dispute according to Visa Core Rules Section 11.7.\n\n"
    "Check:\n"
    "1. Validity: invalid dispute conditions per Section 11.7\n"
    "2. Time limits\n"
    "3. Required documentation and fraud type code\n"
    "4. EMV liability shift (conditions 10.1, 10.2)\n"
    "5. Evidence strength\n\n"
    "Return JSON with: is_valid (bool), validity_reason (str), resolution (str), "
    "confidence (float 0-1), rationale (str), rule_citations (list of objects with "
    "rule_section, rule_description, is_satisfied, details), requires_human_review (bool), "
    "human_review_reason (str or null)"
)


class FraudDisputeAgent(BaseDisputeAgent):
    """AI-powered agent specializing in Category 10 (Fraud) dispute processing."""

    def __init__(self) -> None:
        super().__init__(AgentType.FRAUD)

    @record_agent_validation("fraud_agent")
    async def validate(self, case: DisputeCase) -> bool:
        """Validate that this agent can handle the case.

        TODO: Return True only if case.condition is set and belongs to
        DisputeCategory.FRAUD (Category 10).
        """
        if case.condition is None:
            return False
        return case.condition.category == DisputeCategory.FRAUD

    @trace_agent_process("fraud_agent")
    async def process(self, case: DisputeCase) -> DisputeCase:
        """Process a fraud dispute using AI reasoning over Visa rules.

        TODO: Implement the full processing pipeline:
        1. Set case.assigned_agent to this agent's type
        2. Advance stage to RULE_EVALUATION
        3. Get fraud rules context via get_fraud_rules()
        4. Call self._evaluate_dispute_with_llm() with the rules and system prompt
        5. Parse rule_citations from the result into RuleEvaluationResult objects
        6. Advance stage to DECISION
        7. If result says dispute is invalid -> create INVALID_DISPUTE decision, resolve
        8. Otherwise -> create decision based on result resolution/confidence
        9. Check _should_escalate_to_human() for human review
        10. Advance to RESOLVED or HUMAN_REVIEW stage
        11. Return the updated case
        """
        case.assigned_agent = self.agent_type.value
        case.advance_stage(DisputeLifecycleStage.RULE_EVALUATION, "Starting fraud rule evaluation")

        rules_context = get_fraud_rules()
        result = self._evaluate_dispute_with_llm(case, rules_context, _FRAUD_SYSTEM_PROMPT)

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
            record_agent_decision(
                agent_name="fraud_agent",
                case_id=case.case_id,
                resolution=decision.resolution.value,
                confidence=decision.confidence_score,
                requires_human_review=decision.requires_human_review,
                rule_count=len(rule_evaluations),
            )
            case.advance_stage(DisputeLifecycleStage.RESOLVED, "Invalid dispute")
            return case

        confidence = result.get("confidence", 0.85)
        resolution_str = result.get("resolution", "issuer_win")
        resolution = DisputeResolution(resolution_str)
        requires_human = result.get("requires_human_review", False)
        human_reason = result.get("human_review_reason")

        if not requires_human:
            requires_human = self._should_escalate_to_human(confidence, case)
            if requires_human:
                human_reason = "Low confidence or high-value dispute"

        decision = self.create_decision(
            resolution=resolution,
            rationale=result.get("rationale", "Fraud evaluation complete"),
            rule_evaluations=rule_evaluations,
            confidence=confidence,
            requires_human_review=requires_human,
            human_review_reason=human_reason,
        )
        case.decision = decision

        record_agent_decision(
            agent_name="fraud_agent",
            case_id=case.case_id,
            resolution=decision.resolution.value,
            confidence=decision.confidence_score,
            requires_human_review=decision.requires_human_review,
            rule_count=len(rule_evaluations),
        )

        if requires_human:
            case.advance_stage(DisputeLifecycleStage.HUMAN_REVIEW, human_reason or "Requires human review")
        else:
            case.advance_stage(DisputeLifecycleStage.RESOLVED, "Fraud dispute resolved")

        return case

    @trace_llm_call("fraud_agent")
    def _evaluate_dispute_with_llm(
        self,
        case: DisputeCase,
        rules_context: str,
        system_prompt: str,
    ) -> dict[str, Any]:
        """Override to add Sentry LLM call tracing."""
        return super()._evaluate_dispute_with_llm(case, rules_context, system_prompt)
