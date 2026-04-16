const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

// --- Enums ---

export type TransactionEnvironment =
  | 'card_present'
  | 'card_absent'
  | 'atm'
  | 'ecommerce'
  | 'mail_order_telephone_order';

export type FraudTypeCode = '0' | '1' | '2' | '4' | '7' | 'C' | 'D';

export type Region = 'ap' | 'cemea' | 'europe' | 'lac' | 'us' | 'canada' | 'global';

export type TaskPriority = 1 | 2 | 3 | 4;

// --- Request Types ---

export interface TransactionRequest {
  transaction_id: string;
  acquirer_reference_number?: string | null;
  transaction_date: string;
  processing_date: string;
  amount: number;
  currency: string;
  merchant_name: string;
  merchant_category_code?: string;
  merchant_country?: string;
  acquirer_bin?: string;
  issuer_bin?: string;
  environment?: TransactionEnvironment;
  is_chip_card?: boolean;
  is_chip_initiated?: boolean;
  is_contactless?: boolean;
  is_token_transaction?: boolean;
  is_recurring?: boolean;
  pos_entry_mode?: string | null;
  terminal_entry_capability?: string | null;
  cvv_present?: boolean;
  cvv_verified?: boolean | null;
  avs_result_code?: string | null;
  three_d_secure_authenticated?: boolean;
  authorization_code?: string | null;
  authorization_response_code?: string | null;
  full_chip_data_transmitted?: boolean;
  is_fallback_transaction?: boolean;
  is_delayed_charge?: boolean;
  is_mobile_push_payment?: boolean;
  is_emergency_cash_disbursement?: boolean;
  is_veps_transaction?: boolean;
  region?: Region;
}

export interface CardholderRequest {
  cardholder_name: string;
  partial_payment_credential: string;
  contact_email?: string | null;
  contact_phone?: string | null;
  cardholder_statement?: string | null;
  signed_letter_provided?: boolean;
}

export interface EvidenceRequest {
  description: string;
  evidence_type: string;
  provided_by?: string;
  is_compelling_evidence?: boolean;
  document_references?: string[];
}

export interface DisputeSubmitRequest {
  transaction: TransactionRequest;
  cardholder: CardholderRequest;
  fraud_type_code?: FraudTypeCode | null;
  evidence?: EvidenceRequest[];
  issuer_certification?: string | null;
  dispute_amount?: number | null;
  dispute_currency?: string | null;
  priority?: TaskPriority;
}

// --- Response Types ---

export interface DisputeSummaryResponse {
  case_id: string;
  stage: string;
  category: string | null;
  condition: string | null;
  resolution: string | null;
  assigned_agent: string | null;
  confidence: number | null;
  requires_human_review: boolean | null;
  rule_evaluations_count: number;
  evidence_count: number;
  processing_notes_count: number;
  created_at: string;
  updated_at: string;
}

export interface RuleEvaluation {
  rule_id: string;
  rule_section: string;
  description: string;
  satisfied: boolean;
  details: string;
}

export interface Evidence {
  evidence_id: string;
  description: string;
  type: string;
  provided_by: string;
  is_compelling: boolean;
}

export interface StageHistoryEntry {
  from_stage: string;
  to_stage: string;
  timestamp: string;
  note: string;
}

export interface DisputeDetailResponse {
  case_id: string;
  stage: string;
  category: string | null;
  condition: string | null;
  transaction_id: string;
  transaction_amount: number;
  transaction_currency: string;
  merchant_name: string;
  transaction_environment: string;
  resolution: string | null;
  rationale: string | null;
  decided_by: string | null;
  confidence: number | null;
  requires_human_review: boolean;
  rule_evaluations: RuleEvaluation[];
  evidence: Evidence[];
  processing_notes: string[];
  stage_history: StageHistoryEntry[];
  created_at: string;
  updated_at: string;
}

export interface HealthResponse {
  status: string;
  [key: string]: unknown;
}

// --- API Functions ---

export async function submitDispute(data: DisputeSubmitRequest): Promise<DisputeSummaryResponse> {
  const response = await fetch(`${API_URL}/api/v1/disputes`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  if (!response.ok) {
    const errorBody = await response.text();
    throw new Error(`Failed to submit dispute: ${response.status} ${response.statusText} - ${errorBody}`);
  }
  return response.json();
}

export async function listDisputes(): Promise<DisputeSummaryResponse[]> {
  const response = await fetch(`${API_URL}/api/v1/disputes`);
  if (!response.ok) {
    const errorBody = await response.text();
    throw new Error(`Failed to list disputes: ${response.status} ${response.statusText} - ${errorBody}`);
  }
  return response.json();
}

export async function getDisputeDetail(caseId: string): Promise<DisputeDetailResponse> {
  const response = await fetch(`${API_URL}/api/v1/disputes/${encodeURIComponent(caseId)}`);
  if (!response.ok) {
    const errorBody = await response.text();
    throw new Error(`Failed to get dispute detail: ${response.status} ${response.statusText} - ${errorBody}`);
  }
  return response.json();
}

export async function healthCheck(): Promise<HealthResponse> {
  const response = await fetch(`${API_URL}/api/v1/health`);
  if (!response.ok) {
    const errorBody = await response.text();
    throw new Error(`Health check failed: ${response.status} ${response.statusText} - ${errorBody}`);
  }
  return response.json();
}
