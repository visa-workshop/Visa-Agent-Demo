"""Core data models for dispute processing."""

from datetime import UTC, date, datetime
from uuid import uuid4

from pydantic import BaseModel, Field

from src.models.enums import (
    DisputeCategory,
    DisputeCondition,
    DisputeLifecycleStage,
    DisputeResolution,
    FraudTypeCode,
    Region,
    TransactionEnvironment,
)


class TransactionDetails(BaseModel):
    """Details of the original transaction being disputed."""

    transaction_id: str = Field(..., description="Unique transaction identifier")
    acquirer_reference_number: str | None = None
    transaction_date: date
    processing_date: date
    amount: float = Field(..., gt=0)
    currency: str = Field(..., min_length=3, max_length=3)
    merchant_name: str
    merchant_category_code: str
    merchant_country: str
    acquirer_bin: str
    issuer_bin: str
    environment: TransactionEnvironment
    is_chip_card: bool = False
    is_chip_initiated: bool = False
    is_contactless: bool = False
    is_token_transaction: bool = False
    is_recurring: bool = False
    pos_entry_mode: str | None = None
    terminal_entry_capability: str | None = None
    cvv_present: bool = False
    cvv_verified: bool | None = None
    avs_result_code: str | None = None
    three_d_secure_authenticated: bool = False
    authorization_code: str | None = None
    authorization_response_code: str | None = None
    full_chip_data_transmitted: bool = False
    is_fallback_transaction: bool = False
    is_delayed_charge: bool = False
    is_mobile_push_payment: bool = False
    is_emergency_cash_disbursement: bool = False
    is_veps_transaction: bool = False
    region: Region = Region.GLOBAL


class CardholderInfo(BaseModel):
    """Information about the cardholder filing the dispute."""

    cardholder_name: str
    partial_payment_credential: str
    contact_email: str | None = None
    contact_phone: str | None = None
    cardholder_statement: str | None = None
    signed_letter_provided: bool = False


class DisputeEvidence(BaseModel):
    """Evidence and documentation associated with a dispute."""

    evidence_id: str = Field(default_factory=lambda: str(uuid4()))
    description: str
    evidence_type: str
    provided_by: str  # "issuer" or "acquirer"
    submitted_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    is_compelling_evidence: bool = False
    document_references: list[str] = Field(default_factory=list)


class RuleEvaluationResult(BaseModel):
    """Result of evaluating Visa rules against a dispute."""

    rule_id: str
    rule_section: str
    rule_description: str
    is_satisfied: bool
    details: str
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class DisputeDecision(BaseModel):
    """Decision made on a dispute with rule citations."""

    decision_id: str = Field(default_factory=lambda: str(uuid4()))
    resolution: DisputeResolution
    rationale: str
    rule_citations: list[RuleEvaluationResult] = Field(default_factory=list)
    confidence_score: float = Field(..., ge=0.0, le=1.0)
    requires_human_review: bool = False
    human_review_reason: str | None = None
    decided_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    decided_by: str = "system"


class TimeLimit(BaseModel):
    """Time limit specification for a dispute action."""

    calendar_days: int
    from_event: str
    region_exceptions: dict[str, int] = Field(default_factory=dict)
    description: str


class DisputeCase(BaseModel):
    """Complete dispute case model tracking the full lifecycle."""

    case_id: str = Field(default_factory=lambda: str(uuid4()))
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    # Classification
    category: DisputeCategory | None = None
    condition: DisputeCondition | None = None
    stage: DisputeLifecycleStage = DisputeLifecycleStage.INTAKE

    # Core data
    transaction: TransactionDetails
    cardholder: CardholderInfo
    fraud_type_code: FraudTypeCode | None = None

    # Evidence and documentation
    evidence: list[DisputeEvidence] = Field(default_factory=list)
    issuer_certification: str | None = None

    # Processing
    rule_evaluations: list[RuleEvaluationResult] = Field(default_factory=list)
    decision: DisputeDecision | None = None
    dispute_amount: float | None = None
    dispute_currency: str | None = None

    # Lifecycle tracking
    stage_history: list[dict[str, str]] = Field(default_factory=list)
    assigned_agent: str | None = None
    processing_notes: list[str] = Field(default_factory=list)

    # Pre-arbitration / Arbitration
    pre_arbitration_attempts: int = 0
    arbitration_filed: bool = False

    # Credits
    prior_credits: list[dict[str, float]] = Field(default_factory=list)

    # Time tracking
    dispute_filed_date: datetime | None = None
    time_limit_deadline: datetime | None = None
    is_within_time_limit: bool | None = None

    def advance_stage(self, new_stage: DisputeLifecycleStage, note: str = "") -> None:
        """Advance the dispute to a new lifecycle stage."""
        self.stage_history.append(
            {
                "from_stage": self.stage.value,
                "to_stage": new_stage.value,
                "timestamp": datetime.now(UTC).isoformat(),
                "note": note,
            }
        )
        self.stage = new_stage
        self.updated_at = datetime.now(UTC)

    def add_evidence(self, evidence: DisputeEvidence) -> None:
        """Add evidence to the dispute case."""
        self.evidence.append(evidence)
        self.updated_at = datetime.now(UTC)

    def add_rule_evaluation(self, evaluation: RuleEvaluationResult) -> None:
        """Record a rule evaluation result."""
        self.rule_evaluations.append(evaluation)
        self.updated_at = datetime.now(UTC)

    def add_processing_note(self, note: str) -> None:
        """Add a processing note to the case."""
        self.processing_notes.append(f"[{datetime.now(UTC).isoformat()}] {note}")
        self.updated_at = datetime.now(UTC)
