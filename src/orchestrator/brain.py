"""The Brain - Central orchestration agent for dispute processing.

This is the core orchestrator that:
1. Picks tasks from the queue
2. Routes them to specialized sub-agents
3. Manages the end-to-end lifecycle of each dispute
4. Maintains audit trails and checkpoints
"""

import asyncio
import logging
from typing import Any

from src.agents.authorization_agent import AuthorizationDisputeAgent
from src.agents.base_agent import BaseDisputeAgent
from src.agents.consumer_disputes_agent import ConsumerDisputesAgent
from src.agents.fraud_agent import FraudDisputeAgent
from src.agents.pre_arbitration_agent import PreArbitrationAgent
from src.agents.processing_errors_agent import ProcessingErrorsAgent
from src.models.dispute import DisputeCase
from src.models.enums import (
    AgentType,
    DisputeCategory,
    DisputeLifecycleStage,
)
from src.models.task import DisputeTask
from src.queue.task_queue import DisputeTaskQueue
from src.rules.categorizer import categorize_dispute

logger = logging.getLogger(__name__)


class DisputeBrain:
    """Central orchestration agent for the Visa Disputes Processing system.

    The Brain is responsible for:
    - Consuming tasks from the priority queue
    - Categorizing incoming disputes using AI-powered categorization
    - Routing disputes to AI-powered specialized sub-agents
    - Managing lifecycle state transitions
    - Coordinating pre-arbitration and arbitration escalation
    - Maintaining a complete audit trail
    - Enforcing human-in-the-loop checkpoints

    Architecture:
        Queue -> Brain -> [AI Categorizer] -> AI Sub-Agent -> Decision -> Resolution
    """

    def __init__(self, task_queue: DisputeTaskQueue) -> None:
        self._queue = task_queue
        self._cases: dict[str, DisputeCase] = {}
        self._running = False
        self._worker_count = 3
        self._workers: list[asyncio.Task[None]] = []

        self._agents: dict[str, BaseDisputeAgent] = {
            AgentType.FRAUD.value: FraudDisputeAgent(),
            AgentType.AUTHORIZATION.value: AuthorizationDisputeAgent(),
            AgentType.PROCESSING_ERRORS.value: ProcessingErrorsAgent(),
            AgentType.CONSUMER_DISPUTES.value: ConsumerDisputesAgent(),
            AgentType.PRE_ARBITRATION.value: PreArbitrationAgent(),
        }

        self._category_agent_map: dict[DisputeCategory, str] = {
            DisputeCategory.FRAUD: AgentType.FRAUD.value,
            DisputeCategory.AUTHORIZATION: AgentType.AUTHORIZATION.value,
            DisputeCategory.PROCESSING_ERRORS: AgentType.PROCESSING_ERRORS.value,
            DisputeCategory.CONSUMER_DISPUTES: AgentType.CONSUMER_DISPUTES.value,
        }

        logger.info("DisputeBrain initialized with %d sub-agents", len(self._agents))

    # --- Public accessors (2.3) ---

    @property
    def agent_count(self) -> int:
        """Return the number of loaded sub-agents."""
        return len(self._agents)

    @property
    def queue_depth(self) -> dict[str, int]:
        """Return current queue depth via the task queue."""
        return self._queue.get_queue_depth()

    @property
    def queue_stats(self) -> dict[str, int]:
        """Return queue statistics."""
        return self._queue.get_stats()

    async def start(self) -> None:
        """Start the brain's worker loops to process tasks from the queue."""
        if self._running:
            return
        self._running = True
        for i in range(self._worker_count):
            worker = asyncio.create_task(self._worker_loop(f"worker-{i}"))
            self._workers.append(worker)

    async def stop(self) -> None:
        """Stop the brain and all workers gracefully."""
        self._running = False
        for worker in self._workers:
            worker.cancel()
        if self._workers:
            await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()

    async def submit_dispute(self, case: DisputeCase) -> str:
        """Submit a new dispute case for processing via the queue.

        TODO: Implement:
        1. Store the case in self._cases
        2. Advance stage to INTAKE
        3. Create a DisputeTask with action="process_dispute"
        4. Enqueue the task
        5. Return the case_id
        """
        self._cases[case.case_id] = case
        case.advance_stage(DisputeLifecycleStage.INTAKE, "Dispute submitted to queue")
        task = DisputeTask(
            case_id=case.case_id,
            action="process_dispute",
        )
        await self._queue.enqueue(task)
        return case.case_id

    async def process_single(self, case: DisputeCase) -> DisputeCase:
        """Process a single dispute case synchronously (without the queue).

        TODO: Store the case and call _execute_dispute_processing() directly.
        """
        self._cases[case.case_id] = case
        return await self._execute_dispute_processing(case)

    def get_case(self, case_id: str) -> DisputeCase | None:
        """Retrieve a dispute case by ID."""
        return self._cases.get(case_id)

    def get_all_cases(self) -> list[DisputeCase]:
        """Get all tracked dispute cases."""
        return list(self._cases.values())

    def get_case_summary(self, case_id: str) -> dict[str, Any] | None:
        """Get a summary of a dispute case.

        TODO: Return a dict with: case_id, stage, category, condition, resolution,
        confidence, requires_human_review, assigned_agent, rule_evaluations_count,
        evidence_count, processing_notes_count, created_at, updated_at.
        Return None if case not found.
        """
        case = self._cases.get(case_id)
        if case is None:
            return None

        return {
            "case_id": case.case_id,
            "stage": case.stage.value,
            "category": case.category.value if case.category else None,
            "condition": case.condition.value if case.condition else None,
            "resolution": case.decision.resolution.value if case.decision else None,
            "confidence": case.decision.confidence_score if case.decision else None,
            "requires_human_review": case.decision.requires_human_review if case.decision else None,
            "assigned_agent": case.assigned_agent,
            "rule_evaluations_count": len(case.rule_evaluations),
            "evidence_count": len(case.evidence),
            "processing_notes_count": len(case.processing_notes),
            "created_at": case.created_at.isoformat(),
            "updated_at": case.updated_at.isoformat(),
        }

    async def escalate_to_pre_arbitration(self, case_id: str) -> DisputeCase | None:
        """Escalate a resolved dispute to pre-arbitration.

        TODO: Look up the case, advance to PRE_ARBITRATION stage,
        clear the previous decision, and run the PreArbitrationAgent.
        """
        case = self._cases.get(case_id)
        if case is None:
            return None
        case.advance_stage(DisputeLifecycleStage.PRE_ARBITRATION, "Escalated to pre-arbitration")
        case.decision = None
        agent = self._agents.get(AgentType.PRE_ARBITRATION.value)
        if agent is None:
            return None
        return await agent.process(case)

    async def escalate_to_arbitration(self, case_id: str) -> DisputeCase | None:
        """Escalate a case to arbitration after pre-arbitration cycle.

        TODO: Similar to escalate_to_pre_arbitration but advance to ARBITRATION.
        """
        case = self._cases.get(case_id)
        if case is None:
            return None
        case.advance_stage(DisputeLifecycleStage.ARBITRATION, "Escalated to arbitration")
        case.decision = None
        agent = self._agents.get(AgentType.PRE_ARBITRATION.value)
        if agent is None:
            return None
        return await agent.process(case)

    async def approve_human_review(
        self,
        case_id: str,
        approved: bool,
        reviewer_notes: str = "",
    ) -> DisputeCase | None:
        """Process a human review decision.

        TODO: Look up the case, verify it's in HUMAN_REVIEW stage.
        If approved -> advance to RESOLVED.
        If rejected -> advance to PROCESSING, clear decision.
        """
        case = self._cases.get(case_id)
        if case is None:
            return None
        if case.stage != DisputeLifecycleStage.HUMAN_REVIEW:
            return case
        if approved:
            case.add_processing_note(f"Human review approved: {reviewer_notes}")
            case.advance_stage(DisputeLifecycleStage.RESOLVED, "Approved by human reviewer")
        else:
            case.add_processing_note(f"Human review rejected: {reviewer_notes}")
            case.decision = None
            case.advance_stage(DisputeLifecycleStage.PROCESSING, "Rejected by human reviewer")
        return case

    # Internal methods

    async def _worker_loop(self, worker_id: str) -> None:
        """Main worker loop that continuously processes tasks from the queue."""
        while self._running:
            try:
                task = await self._queue.dequeue()
                if task is None:
                    await asyncio.sleep(0.5)
                    continue
                try:
                    result = await self._handle_task(task)
                    await self._queue.complete_task(task.task_id, result)
                except Exception as e:
                    logger.exception("Task %s failed: %s", task.task_id, e)
                    await self._queue.fail_task(task.task_id, str(e))
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Worker %s error", worker_id)
                await asyncio.sleep(1)

    async def _handle_task(self, task: DisputeTask) -> dict[str, Any]:
        """Handle a single task from the queue.

        TODO: Look up the case, route based on task.action:
        - "process_dispute" -> _execute_dispute_processing()
        - "pre_arbitration" -> escalate_to_pre_arbitration()
        - "arbitration" -> escalate_to_arbitration()
        Return a result dict with case_id and outcome.
        """
        case = self._cases.get(task.case_id)
        if case is None:
            return {"case_id": task.case_id, "outcome": "case_not_found"}

        if task.action == "process_dispute":
            result_case = await self._execute_dispute_processing(case)
            return {"case_id": result_case.case_id, "outcome": result_case.stage.value}
        elif task.action == "pre_arbitration":
            escalated = await self.escalate_to_pre_arbitration(task.case_id)
            if escalated is None:
                return {"case_id": task.case_id, "outcome": "escalation_failed"}
            return {"case_id": escalated.case_id, "outcome": escalated.stage.value}
        elif task.action == "arbitration":
            escalated = await self.escalate_to_arbitration(task.case_id)
            if escalated is None:
                return {"case_id": task.case_id, "outcome": "escalation_failed"}
            return {"case_id": escalated.case_id, "outcome": escalated.stage.value}
        else:
            return {"case_id": task.case_id, "outcome": f"unknown_action_{task.action}"}

    async def _execute_dispute_processing(self, case: DisputeCase) -> DisputeCase:
        """Execute the full dispute processing pipeline.

        TODO: Implement the 3-stage pipeline:
        Stage 1 - Validation:
          - Advance to VALIDATION, run _validate_case()
          - If errors, advance to REJECTED and return

        Stage 2 - Categorization:
          - Advance to CATEGORIZATION
          - Call categorize_dispute(case) to get category + condition
          - Set case.category and case.condition
          - Set dispute_amount, dispute_currency, dispute_filed_date defaults

        Stage 3 - Agent Processing:
          - Advance to PROCESSING
          - Call _get_agent_for_case() to find the right agent
          - Validate the agent can handle the case
          - Call agent.process(case) and return the result
        """
        # Stage 1 - Validation
        case.advance_stage(DisputeLifecycleStage.VALIDATION, "Starting validation")
        errors = self._validate_case(case)
        if errors:
            case.add_processing_note(f"Validation failed: {'; '.join(errors)}")
            case.advance_stage(DisputeLifecycleStage.REJECTED, "Validation failed")
            return case

        # Stage 2 - Categorization
        case.advance_stage(DisputeLifecycleStage.CATEGORIZATION, "Starting categorization")
        cat_result = categorize_dispute(case)
        case.category = cat_result.category
        case.condition = cat_result.condition
        case.add_processing_note(
            f"Categorized as {cat_result.category.value}/{cat_result.condition.value} "
            f"(confidence: {cat_result.confidence:.2f})"
        )
        if case.dispute_amount is None:
            case.dispute_amount = case.transaction.amount
        if case.dispute_currency is None:
            case.dispute_currency = case.transaction.currency
        if case.dispute_filed_date is None:
            from datetime import UTC, datetime
            case.dispute_filed_date = datetime.now(UTC)

        # Stage 3 - Agent Processing
        case.advance_stage(DisputeLifecycleStage.PROCESSING, "Routing to agent")
        agent = self._get_agent_for_case(case)
        if agent is None:
            case.add_processing_note("No agent found for case")
            case.advance_stage(DisputeLifecycleStage.FAILED, "No suitable agent")
            return case

        if not await agent.validate(case):
            case.add_processing_note(f"Agent {agent.agent_type.value} cannot handle this case")
            case.advance_stage(DisputeLifecycleStage.FAILED, "Agent validation failed")
            return case

        return await agent.process(case)

    def _validate_case(self, case: DisputeCase) -> list[str]:
        """Perform basic validation on the dispute case.

        TODO: Check for:
        - Missing transaction_id
        - Amount <= 0
        - Missing cardholder_name
        - Missing partial_payment_credential
        Return a list of error messages (empty if valid).
        """
        errors: list[str] = []
        if not case.transaction.transaction_id:
            errors.append("Missing transaction_id")
        if case.transaction.amount <= 0:
            errors.append("Amount must be greater than 0")
        if not case.cardholder.cardholder_name:
            errors.append("Missing cardholder_name")
        if not case.cardholder.partial_payment_credential:
            errors.append("Missing partial_payment_credential")
        return errors

    def _get_agent_for_case(self, case: DisputeCase) -> BaseDisputeAgent | None:
        """Route a case to the appropriate sub-agent.

        TODO: Route based on:
        1. If case is in pre-arb/arbitration stage -> PreArbitrationAgent
        2. Otherwise, use case.category to look up in _category_agent_map
        """
        if case.stage in (
            DisputeLifecycleStage.PRE_ARBITRATION,
            DisputeLifecycleStage.PRE_ARBITRATION_RESPONSE,
            DisputeLifecycleStage.ARBITRATION,
        ):
            return self._agents.get(AgentType.PRE_ARBITRATION.value)
        if case.category is not None:
            agent_key = self._category_agent_map.get(case.category)
            if agent_key is not None:
                return self._agents.get(agent_key)
        return None
