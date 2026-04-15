"""AI-powered processing errors dispute agent (Category 12).

Uses OpenAI to reason over Visa Core Rules Section 11.9 to evaluate
processing error disputes and render decisions.

Handles processing error disputes:
- 12.2: Incorrect Transaction Code
- 12.3: Incorrect Currency
- 12.4: Incorrect Account Number
- 12.5: Incorrect Amount
- 12.6: Duplicate Processing / Paid by Other Means
- 12.7: Invalid Data
"""

from typing import Any

from src.agents.base_agent import BaseDisputeAgent
from src.instrumentation.tracing import (
    record_agent_decision,
    record_agent_validation,
    trace_agent_process,
    trace_llm_call,
)
from src.llm.visa_rules import get_processing_errors_rules
from src.models.dispute import DisputeCase, RuleEvaluationResult
from src.models.enums import (
    AgentType,
    DisputeCategory,
    DisputeLifecycleStage,
    DisputeResolution,
)

# TODO: Define _PROC_ERRORS_SYSTEM_PROMPT — instruct the LLM to evaluate processing
# error disputes according to Visa Core Rules Section 11.9. Include condition-specific
# checks for all 12.x conditions. Require JSON output with same schema as other agents.
_PROC_ERRORS_SYSTEM_PROMPT = (
    "You are a Visa processing errors dispute agent for Category 12 (Processing Errors). "
    "Evaluate the dispute according to Visa Core Rules Section 11.9.\n\n"
    "Check condition-specific requirements for all 12.x conditions:\n"
    "- 12.2: Incorrect Transaction Code\n"
    "- 12.3: Incorrect Currency\n"
    "- 12.4: Incorrect Account Number\n"
    "- 12.5: Incorrect Amount\n"
    "- 12.6: Duplicate Processing / Paid by Other Means\n"
    "- 12.7: Invalid Data\n\n"
    "Return JSON with: is_valid (bool), validity_reason (str), resolution (str), "
    "confidence (float 0-1), rationale (str), rule_citations (list of objects with "
    "rule_section, rule_description, is_satisfied, details), requires_human_review (bool), "
    "human_review_reason (str or null)"
)


class ProcessingErrorsAgent(BaseDisputeAgent):
    """AI-powered agent specializing in Category 12 (Processing Errors) disputes."""

    def __init__(self) -> None:
        super().__init__(AgentType.PROCESSING_ERRORS)

    @record_agent_validation("processing_errors_agent")
    async def validate(self, case: DisputeCase) -> bool:
        """Validate this agent can handle the case.

        TODO: Return True only if case.condition belongs to DisputeCategory.PROCESSING_ERRORS.
        """
        if case.condition is None:
            return False
        return case.condition.category == DisputeCategory.PROCESSING_ERRORS

    @trace_agent_process("processing_errors_agent")
    async def process(self, case: DisputeCase) -> DisputeCase:
        """Process a processing error dispute using AI reasoning over Visa rules.

        TODO: Follow the same pattern as FraudDisputeAgent.process():
        Use get_processing_errors_rules() for rules context and
        _PROC_ERRORS_SYSTEM_PROMPT for the system prompt.
        """
        case.assigned_agent = self.agent_type.value
        case.advance_stage(DisputeLifecycleStage.RULE_EVALUATION, "Starting processing errors rule evaluation")

        rules_context = get_processing_errors_rules()
        result = self._evaluate_dispute_with_llm(case, rules_context, _PROC_ERRORS_SYSTEM_PROMPT)

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
        resolution = DisputeResolution(resolution_str)
        requires_human = result.get("requires_human_review", False)
        human_reason = result.get("human_review_reason")

        if not requires_human:
            requires_human = self._should_escalate_to_human(confidence, case)
            if requires_human:
                human_reason = "Low confidence or high-value dispute"

        decision = self.create_decision(
            resolution=resolution,
            rationale=result.get("rationale", "Processing errors evaluation complete"),
            rule_evaluations=rule_evaluations,
            confidence=confidence,
            requires_human_review=requires_human,
            human_review_reason=human_reason,
        )
        case.decision = decision

        record_agent_decision(
            agent_name="processing_errors_agent",
            case_id=case.case_id,
            resolution=resolution.value,
            confidence=confidence,
            requires_human_review=requires_human,
            rule_count=len(rule_evaluations),
        )

        if requires_human:
            case.advance_stage(DisputeLifecycleStage.HUMAN_REVIEW, human_reason or "Requires human review")
        else:
            case.advance_stage(DisputeLifecycleStage.RESOLVED, "Processing error dispute resolved")

        return case

    @trace_llm_call("processing_errors_agent")
    def _evaluate_dispute_with_llm(
        self,
        case: DisputeCase,
        rules_context: str,
        system_prompt: str,
    ) -> dict[str, Any]:
        """Override to add Sentry LLM call tracing."""
        return super()._evaluate_dispute_with_llm(case, rules_context, system_prompt)
