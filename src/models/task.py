"""Task models for the dispute processing queue."""

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from src.models.enums import TaskPriority, TaskStatus


class DisputeTask(BaseModel):
    """A task in the dispute processing queue."""

    task_id: str = Field(default_factory=lambda: str(uuid4()))
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    # Task metadata
    priority: TaskPriority = TaskPriority.MEDIUM
    status: TaskStatus = TaskStatus.PENDING

    # Payload
    case_id: str
    action: str  # e.g., "process_dispute", "evaluate_pre_arbitration", "file_arbitration"
    payload: dict[str, Any] = Field(default_factory=dict)

    # Processing
    assigned_agent: str | None = None
    retry_count: int = 0
    max_retries: int = 3
    error_message: str | None = None
    result: dict[str, Any] | None = None

    # Timing
    started_at: datetime | None = None
    completed_at: datetime | None = None

    def mark_in_progress(self, agent: str) -> None:
        """Mark this task as being processed."""
        self.status = TaskStatus.IN_PROGRESS
        self.assigned_agent = agent
        self.started_at = datetime.now(UTC)
        self.updated_at = datetime.now(UTC)

    def mark_completed(self, result: dict[str, Any]) -> None:
        """Mark this task as completed."""
        self.status = TaskStatus.COMPLETED
        self.result = result
        self.completed_at = datetime.now(UTC)
        self.updated_at = datetime.now(UTC)

    def mark_failed(self, error: str) -> None:
        """Mark this task as failed, with retry logic."""
        self.retry_count += 1
        self.error_message = error
        self.updated_at = datetime.now(UTC)

        if self.retry_count >= self.max_retries:
            self.status = TaskStatus.DEAD_LETTER
        else:
            self.status = TaskStatus.RETRY

    @property
    def is_retriable(self) -> bool:
        """Check if this task can be retried."""
        return self.retry_count < self.max_retries
