"""AI-powered pre-arbitration and arbitration processing agent.

Uses OpenAI to reason over Visa Core Rules Sections 11.2, 11.5, and 11.11
to evaluate pre-arbitration attempts, responses, and arbitration filings.
"""

from typing import Any

from src.agents.base_agent import BaseDisputeAgent
from src.llm.openai_client import chat_json
from src.llm.visa_rules import get_arbitration_rules, get_compelling_evidence_rules
from src.models.dispute import DisputeCase, RuleEvaluationResult
from src.models.enums import (
    AgentType,
    DisputeLifecycleStage,
    DisputeResolution,
)

# TODO: Define _PRE_ARB_SYSTEM_PROMPT — instruct the LLM to evaluate
# pre-arbitration and arbitration cases. The prompt should cover:
# 1. Compelling evidence evaluation (Section 11.5.2)
# 2. Timeliness of pre-arbitration/arbitration
# 3. Acquirer's grounds for pre-arbitration
# 4. Issuer's response adequacy
# 5. Whether escalation to arbitration is warranted
#
# Require JSON output with: has_compelling_evidence, resolution, confidence,
# rationale, rule_citations[], next_action, requires_human_review, human_review_reason
_PRE_ARB_SYSTEM_PROMPT = (
    "You are a Visa pre-arbitration and arbitration processing agent. "
    "Evaluate cases according to Visa Core Rules Sections 11.2, 11.5, and 11.11.\n\n"
    "Evaluate:\n"
    "1. Compelling evidence per Section 11.5.2\n"
    "2. Timeliness of pre-arbitration/arbitration\n"
    "3. Acquirer's grounds for pre-arbitration\n"
    "4. Issuer's response adequacy\n"
    "5. Whether escalation to arbitration is warranted\n\n"
    "Return JSON with: has_compelling_evidence (bool), resolution (str), confidence (float 0-1), "
    "rationale (str), rule_citations (list of objects with rule_section, rule_description, "
    "is_satisfied, details), next_action (str: resolved/awaiting_issuer_response/escalate_arbitration/human_review), "
    "requires_human_review (bool), human_review_reason (str or null)"
)


class PreArbitrationAgent(BaseDisputeAgent):
    """AI-powered agent handling pre-arbitration and arbitration stages."""

    def __init__(self) -> None:
        super().__init__(AgentType.PRE_ARBITRATION)

    async def validate(self, case: DisputeCase) -> bool:
        """This agent handles cases in pre-arbitration or arbitration stages.

        TODO: Return True if case.stage is PRE_ARBITRATION, PRE_ARBITRATION_RESPONSE,
        or ARBITRATION.
        """
        return case.stage in (
            DisputeLifecycleStage.PRE_ARBITRATION,
            DisputeLifecycleStage.PRE_ARBITRATION_RESPONSE,
            DisputeLifecycleStage.ARBITRATION,
        )

    async def process(self, case: DisputeCase) -> DisputeCase:
        """Process a pre-arbitration or arbitration action using AI reasoning.

        TODO: Route based on case.stage:
        - PRE_ARBITRATION -> _process_pre_arbitration()
        - PRE_ARBITRATION_RESPONSE -> _process_pre_arbitration_response()
        - ARBITRATION -> _process_arbitration()
        """
        case.assigned_agent = self.agent_type.value
        if case.stage == DisputeLifecycleStage.PRE_ARBITRATION:
            return await self._process_pre_arbitration(case)
        elif case.stage == DisputeLifecycleStage.PRE_ARBITRATION_RESPONSE:
            return await self._process_pre_arbitration_response(case)
        elif case.stage == DisputeLifecycleStage.ARBITRATION:
            return await self._process_arbitration(case)
        return case

    async def _process_pre_arbitration(self, case: DisputeCase) -> DisputeCase:
        """Process a pre-arbitration attempt using AI evaluation.

        TODO: Increment pre_arbitration_attempts, get rules context from
        get_compelling_evidence_rules() + get_arbitration_rules(),
        evaluate with LLM, apply result.
        """
        case.pre_arbitration_attempts += 1
        rules_context = get_compelling_evidence_rules() + "\n\n" + get_arbitration_rules()
        result = self._evaluate_pre_arb_with_llm(case, rules_context)
        return self._apply_pre_arb_result(case, result, "Pre-arbitration")

    async def _process_pre_arbitration_response(self, case: DisputeCase) -> DisputeCase:
        """Process the issuer response to a pre-arbitration attempt using AI.

        TODO: Get rules context, evaluate with LLM, apply result.
        """
        rules_context = get_compelling_evidence_rules() + "\n\n" + get_arbitration_rules()
        result = self._evaluate_pre_arb_with_llm(case, rules_context)
        return self._apply_pre_arb_result(case, result, "Pre-arbitration response")

    async def _process_arbitration(self, case: DisputeCase) -> DisputeCase:
        """Process an arbitration filing using AI evaluation.

        TODO: Set arbitration_filed=True, evaluate with LLM,
        create ESCALATED_ARBITRATION decision with human review required,
        advance to HUMAN_REVIEW stage.
        """
        case.arbitration_filed = True
        rules_context = get_arbitration_rules()
        result = self._evaluate_pre_arb_with_llm(case, rules_context)

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

        decision = self.create_decision(
            resolution=DisputeResolution.ESCALATED_ARBITRATION,
            rationale=result.get("rationale", "Case escalated to arbitration"),
            rule_evaluations=rule_evaluations,
            confidence=result.get("confidence", 0.85),
            requires_human_review=True,
            human_review_reason="Arbitration cases require human oversight",
        )
        case.decision = decision
        case.advance_stage(DisputeLifecycleStage.HUMAN_REVIEW, "Arbitration requires human review")
        return case

    def _apply_pre_arb_result(
        self, case: DisputeCase, result: dict[str, Any], prefix: str
    ) -> DisputeCase:
        """Apply the LLM evaluation result to the case.

        TODO: Parse rule citations, determine next_action from result:
        - "resolved" -> create decision, advance to RESOLVED
        - "awaiting_issuer_response" -> advance to PRE_ARBITRATION_RESPONSE
        - "escalate_arbitration" -> create ESCALATED_ARBITRATION decision, HUMAN_REVIEW
        - else -> human review
        """
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

        next_action = result.get("next_action", "human_review")
        resolution_str = result.get("resolution", "issuer_win")
        confidence = result.get("confidence", 0.80)

        if next_action == "resolved":
            decision = self.create_decision(
                resolution=DisputeResolution(resolution_str),
                rationale=result.get("rationale", f"{prefix} resolved"),
                rule_evaluations=rule_evaluations,
                confidence=confidence,
            )
            case.decision = decision
            case.advance_stage(DisputeLifecycleStage.RESOLVED, f"{prefix} resolved")
        elif next_action == "awaiting_issuer_response":
            case.add_processing_note(f"{prefix}: awaiting issuer response")
            case.advance_stage(DisputeLifecycleStage.PRE_ARBITRATION_RESPONSE, "Awaiting issuer response")
        elif next_action == "escalate_arbitration":
            decision = self.create_decision(
                resolution=DisputeResolution.ESCALATED_ARBITRATION,
                rationale=result.get("rationale", "Escalating to arbitration"),
                rule_evaluations=rule_evaluations,
                confidence=confidence,
                requires_human_review=True,
                human_review_reason=result.get("human_review_reason", "Arbitration filing decision required"),
            )
            case.decision = decision
            case.advance_stage(DisputeLifecycleStage.HUMAN_REVIEW, "Arbitration escalation requires review")
        else:
            decision = self.create_decision(
                resolution=DisputeResolution(resolution_str),
                rationale=result.get("rationale", f"{prefix} requires review"),
                rule_evaluations=rule_evaluations,
                confidence=confidence,
                requires_human_review=True,
                human_review_reason=result.get("human_review_reason", "Manual review required"),
            )
            case.decision = decision
            case.advance_stage(DisputeLifecycleStage.HUMAN_REVIEW, "Requires human review")

        return case

    def _evaluate_pre_arb_with_llm(
        self, case: DisputeCase, rules_context: str
    ) -> dict[str, Any]:
        """Use the LLM to evaluate a pre-arbitration/arbitration case.

        TODO: Build a user prompt with case details including:
        - Case stage, category, condition
        - Transaction details
        - Pre-arbitration attempts count
        - All evidence (separated by acquirer/issuer)
        - Issuer certification
        - Processing notes
        Call chat_json() with _PRE_ARB_SYSTEM_PROMPT and return result.
        """
        category = case.category.value if case.category else "Unknown"
        condition = case.condition.value if case.condition else "Unknown"

        issuer_evidence = "\n".join(
            f"  - {e.description} (compelling: {e.is_compelling_evidence})"
            for e in case.evidence if e.provided_by == "issuer"
        ) or "  None"
        acquirer_evidence = "\n".join(
            f"  - {e.description} (compelling: {e.is_compelling_evidence})"
            for e in case.evidence if e.provided_by == "acquirer"
        ) or "  None"
        notes = "\n".join(f"  - {n}" for n in case.processing_notes) or "  None"

        user_prompt = (
            f"Current Stage: {case.stage.value}\n"
            f"Category: {category}\n"
            f"Condition: {condition}\n"
            f"Transaction ID: {case.transaction.transaction_id}\n"
            f"Amount: {case.transaction.amount} {case.transaction.currency}\n"
            f"Merchant: {case.transaction.merchant_name}\n"
            f"Pre-arbitration Attempts: {case.pre_arbitration_attempts}\n"
            f"Issuer Certification: {case.issuer_certification or 'None'}\n"
            f"Issuer Evidence:\n{issuer_evidence}\n"
            f"Acquirer Evidence:\n{acquirer_evidence}\n"
            f"Processing Notes:\n{notes}\n\n"
            f"Visa Rules Reference:\n{rules_context}"
        )

        return chat_json(_PRE_ARB_SYSTEM_PROMPT, user_prompt)
