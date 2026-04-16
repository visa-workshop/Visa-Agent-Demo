import { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import {
  submitDispute,
  type DisputeSubmitRequest,
  type DisputeSummaryResponse,
  type TransactionEnvironment,
  type Region,
  type FraudTypeCode,
  type EvidenceRequest,
} from '@/lib/api';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Textarea } from '@/components/ui/textarea';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import {
  Select,
  SelectTrigger,
  SelectValue,
  SelectContent,
  SelectItem,
} from '@/components/ui/select';
import {
  Collapsible,
  CollapsibleTrigger,
  CollapsibleContent,
} from '@/components/ui/collapsible';
import { ChevronDown, ChevronUp, Plus, Trash2, Loader2, CheckCircle2 } from 'lucide-react';

function generateTxnId(): string {
  const hex = Array.from(crypto.getRandomValues(new Uint8Array(8)))
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('');
  return `TXN-${hex}`;
}

function todayStr(): string {
  return new Date().toISOString().split('T')[0];
}

const BOOLEAN_FLAGS = [
  { key: 'is_chip_card', label: 'Chip Card' },
  { key: 'is_chip_initiated', label: 'Chip Initiated' },
  { key: 'is_contactless', label: 'Contactless' },
  { key: 'is_token_transaction', label: 'Token Transaction' },
  { key: 'is_recurring', label: 'Recurring' },
  { key: 'cvv_present', label: 'CVV Present' },
  { key: 'three_d_secure_authenticated', label: '3D Secure Authenticated' },
  { key: 'full_chip_data_transmitted', label: 'Full Chip Data Transmitted' },
  { key: 'is_fallback_transaction', label: 'Fallback Transaction' },
  { key: 'is_delayed_charge', label: 'Delayed Charge' },
  { key: 'is_mobile_push_payment', label: 'Mobile Push Payment' },
  { key: 'is_emergency_cash_disbursement', label: 'Emergency Cash Disbursement' },
  { key: 'is_veps_transaction', label: 'VEPS Transaction' },
] as const;

const ENVIRONMENT_OPTIONS: { value: TransactionEnvironment; label: string }[] = [
  { value: 'card_present', label: 'Card Present' },
  { value: 'card_absent', label: 'Card Absent' },
  { value: 'atm', label: 'ATM' },
  { value: 'ecommerce', label: 'E-Commerce' },
  { value: 'mail_order_telephone_order', label: 'Mail Order / Telephone Order' },
];

const REGION_OPTIONS: { value: Region; label: string }[] = [
  { value: 'ap', label: 'Asia Pacific' },
  { value: 'cemea', label: 'CEMEA' },
  { value: 'europe', label: 'Europe' },
  { value: 'lac', label: 'Latin America & Caribbean' },
  { value: 'us', label: 'United States' },
  { value: 'canada', label: 'Canada' },
  { value: 'global', label: 'Global' },
];

const FRAUD_TYPE_OPTIONS: { value: FraudTypeCode; label: string }[] = [
  { value: '0', label: '0 - Lost' },
  { value: '1', label: '1 - Stolen' },
  { value: '2', label: '2 - Not Received' },
  { value: '4', label: '4 - Counterfeit' },
  { value: '7', label: '7 - Account Takeover' },
  { value: 'C', label: 'C - Merchant Misrepresentation' },
  { value: 'D', label: 'D - Manipulation' },
];

interface EvidenceFormItem {
  description: string;
  evidence_type: string;
  provided_by: string;
  is_compelling_evidence: boolean;
  document_references: string;
}

function emptyEvidence(): EvidenceFormItem {
  return {
    description: '',
    evidence_type: '',
    provided_by: 'issuer',
    is_compelling_evidence: false,
    document_references: '',
  };
}

export default function DisputeFormPage() {
  const navigate = useNavigate();

  // --- Section open/close state ---
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [cardholderOpen, setCardholderOpen] = useState(true);
  const [disputeDetailsOpen, setDisputeDetailsOpen] = useState(true);
  const [evidenceOpen, setEvidenceOpen] = useState(true);

  // --- Transaction Details (required) ---
  const [transactionId, setTransactionId] = useState(generateTxnId());
  const [transactionDate, setTransactionDate] = useState(todayStr());
  const [processingDate, setProcessingDate] = useState(todayStr());
  const [amount, setAmount] = useState('');
  const [currency, setCurrency] = useState('USD');
  const [merchantName, setMerchantName] = useState('');

  // --- Transaction Details (advanced/optional) ---
  const [acquirerRefNum, setAcquirerRefNum] = useState('');
  const [merchantCategoryCode, setMerchantCategoryCode] = useState('5411');
  const [merchantCountry, setMerchantCountry] = useState('US');
  const [acquirerBin, setAcquirerBin] = useState('000000');
  const [issuerBin, setIssuerBin] = useState('000000');
  const [environment, setEnvironment] = useState<TransactionEnvironment>('ecommerce');
  const [region, setRegion] = useState<Region>('us');
  const [booleanFlags, setBooleanFlags] = useState<Record<string, boolean>>({});
  const [posEntryMode, setPosEntryMode] = useState('');
  const [terminalEntryCap, setTerminalEntryCap] = useState('');
  const [cvvVerified, setCvvVerified] = useState<'true' | 'false' | 'null'>('null');
  const [avsResultCode, setAvsResultCode] = useState('');
  const [authorizationCode, setAuthorizationCode] = useState('');
  const [authResponseCode, setAuthResponseCode] = useState('');

  // --- Cardholder Info ---
  const [cardholderName, setCardholderName] = useState('');
  const [partialPaymentCred, setPartialPaymentCred] = useState('');
  const [contactEmail, setContactEmail] = useState('');
  const [contactPhone, setContactPhone] = useState('');
  const [cardholderStatement, setCardholderStatement] = useState('');
  const [signedLetterProvided, setSignedLetterProvided] = useState(false);

  // --- Dispute Details ---
  const [fraudTypeCode, setFraudTypeCode] = useState<FraudTypeCode | ''>('');
  const [issuerCertification, setIssuerCertification] = useState('');
  const [disputeAmount, setDisputeAmount] = useState('');
  const [disputeCurrency, setDisputeCurrency] = useState('');

  // --- Evidence ---
  const [evidenceItems, setEvidenceItems] = useState<EvidenceFormItem[]>([]);

  // --- Submit state ---
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<DisputeSummaryResponse | null>(null);

  // --- Validation ---
  const [validationErrors, setValidationErrors] = useState<string[]>([]);

  function validate(): string[] {
    const errs: string[] = [];
    if (!transactionId.trim()) errs.push('Transaction ID is required.');
    if (!transactionDate) errs.push('Transaction Date is required.');
    if (!processingDate) errs.push('Processing Date is required.');
    const amt = parseFloat(amount);
    if (!amount || isNaN(amt) || amt <= 0) errs.push('Amount must be greater than 0.');
    if (!currency.trim() || currency.trim().length !== 3) errs.push('Currency must be exactly 3 characters.');
    if (!merchantName.trim()) errs.push('Merchant Name is required.');
    if (!cardholderName.trim()) errs.push('Cardholder Name is required.');
    if (!partialPaymentCred.trim()) errs.push('Partial Payment Credential is required.');
    for (let i = 0; i < evidenceItems.length; i++) {
      const ev = evidenceItems[i];
      if (!ev.description.trim()) errs.push(`Evidence #${i + 1}: Description is required.`);
      if (!ev.evidence_type.trim()) errs.push(`Evidence #${i + 1}: Evidence Type is required.`);
    }
    return errs;
  }

  async function handleSubmit() {
    setError(null);
    setResult(null);
    const errs = validate();
    if (errs.length > 0) {
      setValidationErrors(errs);
      return;
    }
    setValidationErrors([]);

    const evidence: EvidenceRequest[] = evidenceItems.map((ev) => ({
      description: ev.description,
      evidence_type: ev.evidence_type,
      provided_by: ev.provided_by,
      is_compelling_evidence: ev.is_compelling_evidence,
      document_references: ev.document_references
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean),
    }));

    const req: DisputeSubmitRequest = {
      transaction: {
        transaction_id: transactionId.trim(),
        transaction_date: transactionDate,
        processing_date: processingDate,
        amount: parseFloat(amount),
        currency: currency.trim(),
        merchant_name: merchantName.trim(),
        acquirer_reference_number: acquirerRefNum.trim() || null,
        merchant_category_code: merchantCategoryCode.trim() || '5411',
        merchant_country: merchantCountry.trim() || 'US',
        acquirer_bin: acquirerBin.trim() || '000000',
        issuer_bin: issuerBin.trim() || '000000',
        environment,
        region,
        is_chip_card: booleanFlags['is_chip_card'] ?? false,
        is_chip_initiated: booleanFlags['is_chip_initiated'] ?? false,
        is_contactless: booleanFlags['is_contactless'] ?? false,
        is_token_transaction: booleanFlags['is_token_transaction'] ?? false,
        is_recurring: booleanFlags['is_recurring'] ?? false,
        cvv_present: booleanFlags['cvv_present'] ?? false,
        three_d_secure_authenticated: booleanFlags['three_d_secure_authenticated'] ?? false,
        full_chip_data_transmitted: booleanFlags['full_chip_data_transmitted'] ?? false,
        is_fallback_transaction: booleanFlags['is_fallback_transaction'] ?? false,
        is_delayed_charge: booleanFlags['is_delayed_charge'] ?? false,
        is_mobile_push_payment: booleanFlags['is_mobile_push_payment'] ?? false,
        is_emergency_cash_disbursement: booleanFlags['is_emergency_cash_disbursement'] ?? false,
        is_veps_transaction: booleanFlags['is_veps_transaction'] ?? false,
        pos_entry_mode: posEntryMode.trim() || null,
        terminal_entry_capability: terminalEntryCap.trim() || null,
        cvv_verified: cvvVerified === 'null' ? null : cvvVerified === 'true',
        avs_result_code: avsResultCode.trim() || null,
        authorization_code: authorizationCode.trim() || null,
        authorization_response_code: authResponseCode.trim() || null,
      },
      cardholder: {
        cardholder_name: cardholderName.trim(),
        partial_payment_credential: partialPaymentCred.trim(),
        contact_email: contactEmail.trim() || null,
        contact_phone: contactPhone.trim() || null,
        cardholder_statement: cardholderStatement.trim() || null,
        signed_letter_provided: signedLetterProvided,
      },
      fraud_type_code: fraudTypeCode || null,
      issuer_certification: issuerCertification.trim() || null,
      dispute_amount: disputeAmount ? parseFloat(disputeAmount) : null,
      dispute_currency: disputeCurrency.trim() || null,
      evidence: evidence.length > 0 ? evidence : undefined,
    };

    setSubmitting(true);
    try {
      const res = await submitDispute(req);
      setResult(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'An unexpected error occurred.');
    } finally {
      setSubmitting(false);
    }
  }

  function toggleBooleanFlag(key: string) {
    setBooleanFlags((prev) => ({ ...prev, [key]: !prev[key] }));
  }

  function updateEvidence(index: number, field: keyof EvidenceFormItem, value: string | boolean) {
    setEvidenceItems((prev) =>
      prev.map((item, i) => (i === index ? { ...item, [field]: value } : item))
    );
  }

  function removeEvidence(index: number) {
    setEvidenceItems((prev) => prev.filter((_, i) => i !== index));
  }

  if (result) {
    return (
      <div className="max-w-2xl mx-auto py-8">
        <Card className="border-green-200 bg-green-50">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-green-800">
              <CheckCircle2 className="h-6 w-6" />
              Dispute Submitted Successfully
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-sm">
              <div>
                <span className="font-medium text-gray-600">Case ID:</span>{' '}
                <Link
                  to={`/disputes/${result.case_id}`}
                  className="text-[#1a1f71] underline font-semibold"
                >
                  {result.case_id}
                </Link>
              </div>
              <div>
                <span className="font-medium text-gray-600">Stage:</span>{' '}
                <span className="font-semibold">{result.stage}</span>
              </div>
              <div>
                <span className="font-medium text-gray-600">Category:</span>{' '}
                <span>{result.category ?? 'N/A'}</span>
              </div>
              <div>
                <span className="font-medium text-gray-600">Condition:</span>{' '}
                <span>{result.condition ?? 'N/A'}</span>
              </div>
              <div>
                <span className="font-medium text-gray-600">Resolution:</span>{' '}
                <span>{result.resolution ?? 'Pending'}</span>
              </div>
              <div>
                <span className="font-medium text-gray-600">Confidence:</span>{' '}
                <span>{result.confidence != null ? `${(result.confidence * 100).toFixed(1)}%` : 'N/A'}</span>
              </div>
              <div className="sm:col-span-2">
                <span className="font-medium text-gray-600">Human Review Required:</span>{' '}
                <span className={result.requires_human_review ? 'text-amber-600 font-semibold' : ''}>
                  {result.requires_human_review ? 'Yes' : 'No'}
                </span>
              </div>
            </div>
            <div className="flex gap-3 pt-4">
              <Button
                onClick={() => navigate(`/disputes/${result.case_id}`)}
                style={{ backgroundColor: '#1a1f71' }}
                className="text-white hover:opacity-90"
              >
                View Dispute Details
              </Button>
              <Button
                variant="outline"
                onClick={() => {
                  setResult(null);
                  setTransactionId(generateTxnId());
                  setTransactionDate(todayStr());
                  setProcessingDate(todayStr());
                  setAmount('');
                  setMerchantName('');
                  setCardholderName('');
                  setPartialPaymentCred('');
                  setContactEmail('');
                  setContactPhone('');
                  setCardholderStatement('');
                  setSignedLetterProvided(false);
                  setFraudTypeCode('');
                  setIssuerCertification('');
                  setDisputeAmount('');
                  setDisputeCurrency('');
                  setEvidenceItems([]);
                  setError(null);
                  setValidationErrors([]);
                }}
              >
                Submit Another Dispute
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="max-w-4xl mx-auto py-8 space-y-6">
      <h1 className="text-2xl font-bold" style={{ color: '#1a1f71' }}>
        Submit a New Dispute
      </h1>

      {validationErrors.length > 0 && (
        <Alert variant="destructive">
          <AlertTitle>Validation Errors</AlertTitle>
          <AlertDescription>
            <ul className="list-disc pl-4 space-y-1">
              {validationErrors.map((err, i) => (
                <li key={i}>{err}</li>
              ))}
            </ul>
          </AlertDescription>
        </Alert>
      )}

      {error && (
        <Alert variant="destructive">
          <AlertTitle>Submission Error</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {/* Section 1: Transaction Details */}
      <Card>
        <CardHeader>
          <CardTitle style={{ color: '#1a1f71' }}>Transaction Details</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            <div className="space-y-2">
              <Label htmlFor="transaction_id">
                Transaction ID <span className="text-red-500">*</span>
              </Label>
              <Input
                id="transaction_id"
                value={transactionId}
                onChange={(e) => setTransactionId(e.target.value)}
                placeholder="TXN-..."
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="transaction_date">
                Transaction Date <span className="text-red-500">*</span>
              </Label>
              <Input
                id="transaction_date"
                type="date"
                value={transactionDate}
                onChange={(e) => setTransactionDate(e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="processing_date">
                Processing Date <span className="text-red-500">*</span>
              </Label>
              <Input
                id="processing_date"
                type="date"
                value={processingDate}
                onChange={(e) => setProcessingDate(e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="amount">
                Amount <span className="text-red-500">*</span>
              </Label>
              <Input
                id="amount"
                type="number"
                min="0.01"
                step="0.01"
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
                placeholder="0.00"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="currency">
                Currency <span className="text-red-500">*</span>
              </Label>
              <Input
                id="currency"
                value={currency}
                onChange={(e) => setCurrency(e.target.value.toUpperCase())}
                maxLength={3}
                placeholder="USD"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="merchant_name">
                Merchant Name <span className="text-red-500">*</span>
              </Label>
              <Input
                id="merchant_name"
                value={merchantName}
                onChange={(e) => setMerchantName(e.target.value)}
                placeholder="Merchant name"
              />
            </div>
          </div>

          {/* Advanced Transaction Details */}
          <Collapsible open={advancedOpen} onOpenChange={setAdvancedOpen}>
            <CollapsibleTrigger asChild>
              <Button variant="ghost" className="flex items-center gap-2 px-0 text-sm text-gray-600 hover:text-gray-900">
                {advancedOpen ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
                Advanced Transaction Details
              </Button>
            </CollapsibleTrigger>
            <CollapsibleContent className="space-y-4 pt-4">
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                <div className="space-y-2">
                  <Label htmlFor="acquirer_ref">Acquirer Reference Number</Label>
                  <Input
                    id="acquirer_ref"
                    value={acquirerRefNum}
                    onChange={(e) => setAcquirerRefNum(e.target.value)}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="mcc">Merchant Category Code</Label>
                  <Input
                    id="mcc"
                    value={merchantCategoryCode}
                    onChange={(e) => setMerchantCategoryCode(e.target.value)}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="merchant_country">Merchant Country</Label>
                  <Input
                    id="merchant_country"
                    value={merchantCountry}
                    onChange={(e) => setMerchantCountry(e.target.value)}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="acquirer_bin">Acquirer BIN</Label>
                  <Input
                    id="acquirer_bin"
                    value={acquirerBin}
                    onChange={(e) => setAcquirerBin(e.target.value)}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="issuer_bin">Issuer BIN</Label>
                  <Input
                    id="issuer_bin"
                    value={issuerBin}
                    onChange={(e) => setIssuerBin(e.target.value)}
                  />
                </div>
                <div className="space-y-2">
                  <Label>Environment</Label>
                  <Select value={environment} onValueChange={(v) => setEnvironment(v as TransactionEnvironment)}>
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {ENVIRONMENT_OPTIONS.map((opt) => (
                        <SelectItem key={opt.value} value={opt.value}>
                          {opt.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label>Region</Label>
                  <Select value={region} onValueChange={(v) => setRegion(v as Region)}>
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {REGION_OPTIONS.map((opt) => (
                        <SelectItem key={opt.value} value={opt.value}>
                          {opt.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="pos_entry_mode">POS Entry Mode</Label>
                  <Input
                    id="pos_entry_mode"
                    value={posEntryMode}
                    onChange={(e) => setPosEntryMode(e.target.value)}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="terminal_entry_cap">Terminal Entry Capability</Label>
                  <Input
                    id="terminal_entry_cap"
                    value={terminalEntryCap}
                    onChange={(e) => setTerminalEntryCap(e.target.value)}
                  />
                </div>
                <div className="space-y-2">
                  <Label>CVV Verified</Label>
                  <Select value={cvvVerified} onValueChange={(v) => setCvvVerified(v as 'true' | 'false' | 'null')}>
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="null">Unknown</SelectItem>
                      <SelectItem value="true">Yes</SelectItem>
                      <SelectItem value="false">No</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="avs_result">AVS Result Code</Label>
                  <Input
                    id="avs_result"
                    value={avsResultCode}
                    onChange={(e) => setAvsResultCode(e.target.value)}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="auth_code">Authorization Code</Label>
                  <Input
                    id="auth_code"
                    value={authorizationCode}
                    onChange={(e) => setAuthorizationCode(e.target.value)}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="auth_response_code">Authorization Response Code</Label>
                  <Input
                    id="auth_response_code"
                    value={authResponseCode}
                    onChange={(e) => setAuthResponseCode(e.target.value)}
                  />
                </div>
              </div>

              {/* Boolean Flags Grid */}
              <div className="space-y-2">
                <Label className="text-sm font-medium">Transaction Flags</Label>
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                  {BOOLEAN_FLAGS.map((flag) => (
                    <div key={flag.key} className="flex items-center space-x-2">
                      <Checkbox
                        id={flag.key}
                        checked={booleanFlags[flag.key] ?? false}
                        onCheckedChange={() => toggleBooleanFlag(flag.key)}
                      />
                      <Label htmlFor={flag.key} className="text-sm font-normal cursor-pointer">
                        {flag.label}
                      </Label>
                    </div>
                  ))}
                </div>
              </div>
            </CollapsibleContent>
          </Collapsible>
        </CardContent>
      </Card>

      {/* Section 2: Cardholder Information */}
      <Collapsible open={cardholderOpen} onOpenChange={setCardholderOpen}>
        <Card>
          <CollapsibleTrigger asChild>
            <CardHeader className="cursor-pointer hover:bg-gray-50 transition-colors">
              <CardTitle className="flex items-center justify-between" style={{ color: '#1a1f71' }}>
                Cardholder Information
                {cardholderOpen ? <ChevronUp className="h-5 w-5" /> : <ChevronDown className="h-5 w-5" />}
              </CardTitle>
            </CardHeader>
          </CollapsibleTrigger>
          <CollapsibleContent>
            <CardContent className="space-y-4">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label htmlFor="cardholder_name">
                    Cardholder Name <span className="text-red-500">*</span>
                  </Label>
                  <Input
                    id="cardholder_name"
                    value={cardholderName}
                    onChange={(e) => setCardholderName(e.target.value)}
                    placeholder="John Doe"
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="partial_payment_cred">
                    Partial Payment Credential <span className="text-red-500">*</span>
                  </Label>
                  <Input
                    id="partial_payment_cred"
                    value={partialPaymentCred}
                    onChange={(e) => setPartialPaymentCred(e.target.value)}
                    placeholder="XXXX-XXXX-XXXX-1234"
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="contact_email">Contact Email</Label>
                  <Input
                    id="contact_email"
                    type="email"
                    value={contactEmail}
                    onChange={(e) => setContactEmail(e.target.value)}
                    placeholder="john@example.com"
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="contact_phone">Contact Phone</Label>
                  <Input
                    id="contact_phone"
                    type="tel"
                    value={contactPhone}
                    onChange={(e) => setContactPhone(e.target.value)}
                    placeholder="+1 (555) 000-0000"
                  />
                </div>
              </div>
              <div className="space-y-2">
                <Label htmlFor="cardholder_statement">Cardholder Statement</Label>
                <Textarea
                  id="cardholder_statement"
                  value={cardholderStatement}
                  onChange={(e) => setCardholderStatement(e.target.value)}
                  placeholder="Describe the dispute from the cardholder's perspective..."
                  rows={3}
                />
              </div>
              <div className="flex items-center space-x-2">
                <Checkbox
                  id="signed_letter"
                  checked={signedLetterProvided}
                  onCheckedChange={(checked) => setSignedLetterProvided(checked === true)}
                />
                <Label htmlFor="signed_letter" className="font-normal cursor-pointer">
                  Signed Letter Provided
                </Label>
              </div>
            </CardContent>
          </CollapsibleContent>
        </Card>
      </Collapsible>

      {/* Section 3: Dispute Details */}
      <Collapsible open={disputeDetailsOpen} onOpenChange={setDisputeDetailsOpen}>
        <Card>
          <CollapsibleTrigger asChild>
            <CardHeader className="cursor-pointer hover:bg-gray-50 transition-colors">
              <CardTitle className="flex items-center justify-between" style={{ color: '#1a1f71' }}>
                Dispute Details
                {disputeDetailsOpen ? <ChevronUp className="h-5 w-5" /> : <ChevronDown className="h-5 w-5" />}
              </CardTitle>
            </CardHeader>
          </CollapsibleTrigger>
          <CollapsibleContent>
            <CardContent className="space-y-4">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label>Fraud Type Code</Label>
                  <Select value={fraudTypeCode || '_none'} onValueChange={(v) => setFraudTypeCode(v === '_none' ? '' : v as FraudTypeCode)}>
                    <SelectTrigger>
                      <SelectValue placeholder="Select fraud type..." />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="_none">None</SelectItem>
                      {FRAUD_TYPE_OPTIONS.map((opt) => (
                        <SelectItem key={opt.value} value={opt.value}>
                          {opt.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="issuer_cert">Issuer Certification</Label>
                  <Input
                    id="issuer_cert"
                    value={issuerCertification}
                    onChange={(e) => setIssuerCertification(e.target.value)}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="dispute_amount">
                    Dispute Amount{' '}
                    <span className="text-xs text-gray-500">(defaults to transaction amount)</span>
                  </Label>
                  <Input
                    id="dispute_amount"
                    type="number"
                    min="0.01"
                    step="0.01"
                    value={disputeAmount}
                    onChange={(e) => setDisputeAmount(e.target.value)}
                    placeholder={amount || '0.00'}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="dispute_currency">
                    Dispute Currency{' '}
                    <span className="text-xs text-gray-500">(defaults to transaction currency)</span>
                  </Label>
                  <Input
                    id="dispute_currency"
                    value={disputeCurrency}
                    onChange={(e) => setDisputeCurrency(e.target.value.toUpperCase())}
                    maxLength={3}
                    placeholder={currency || 'USD'}
                  />
                </div>
              </div>
            </CardContent>
          </CollapsibleContent>
        </Card>
      </Collapsible>

      {/* Section 4: Evidence */}
      <Collapsible open={evidenceOpen} onOpenChange={setEvidenceOpen}>
        <Card>
          <CollapsibleTrigger asChild>
            <CardHeader className="cursor-pointer hover:bg-gray-50 transition-colors">
              <CardTitle className="flex items-center justify-between" style={{ color: '#1a1f71' }}>
                <span>
                  Evidence{' '}
                  <span className="text-sm font-normal text-gray-500">(optional)</span>
                </span>
                {evidenceOpen ? <ChevronUp className="h-5 w-5" /> : <ChevronDown className="h-5 w-5" />}
              </CardTitle>
            </CardHeader>
          </CollapsibleTrigger>
          <CollapsibleContent>
            <CardContent className="space-y-4">
              {evidenceItems.map((ev, idx) => (
                <Card key={idx} className="border-dashed">
                  <CardContent className="pt-4 space-y-3">
                    <div className="flex items-center justify-between">
                      <span className="text-sm font-medium text-gray-600">Evidence #{idx + 1}</span>
                      <Button
                        variant="ghost"
                        size="sm"
                        className="text-red-500 hover:text-red-700 hover:bg-red-50"
                        onClick={() => removeEvidence(idx)}
                      >
                        <Trash2 className="h-4 w-4 mr-1" />
                        Remove
                      </Button>
                    </div>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                      <div className="space-y-2">
                        <Label>
                          Description <span className="text-red-500">*</span>
                        </Label>
                        <Input
                          value={ev.description}
                          onChange={(e) => updateEvidence(idx, 'description', e.target.value)}
                          placeholder="Evidence description"
                        />
                      </div>
                      <div className="space-y-2">
                        <Label>
                          Evidence Type <span className="text-red-500">*</span>
                        </Label>
                        <Input
                          value={ev.evidence_type}
                          onChange={(e) => updateEvidence(idx, 'evidence_type', e.target.value)}
                          placeholder="receipt, correspondence, etc."
                        />
                      </div>
                      <div className="space-y-2">
                        <Label>Provided By</Label>
                        <Select
                          value={ev.provided_by}
                          onValueChange={(v) => updateEvidence(idx, 'provided_by', v)}
                        >
                          <SelectTrigger>
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="issuer">Issuer</SelectItem>
                            <SelectItem value="acquirer">Acquirer</SelectItem>
                          </SelectContent>
                        </Select>
                      </div>
                      <div className="space-y-2">
                        <Label>Document References</Label>
                        <Input
                          value={ev.document_references}
                          onChange={(e) => updateEvidence(idx, 'document_references', e.target.value)}
                          placeholder="doc1, doc2, doc3 (comma-separated)"
                        />
                      </div>
                    </div>
                    <div className="flex items-center space-x-2">
                      <Checkbox
                        checked={ev.is_compelling_evidence}
                        onCheckedChange={(checked) =>
                          updateEvidence(idx, 'is_compelling_evidence', checked === true)
                        }
                      />
                      <Label className="font-normal cursor-pointer">Is Compelling Evidence</Label>
                    </div>
                  </CardContent>
                </Card>
              ))}
              <Button
                variant="outline"
                onClick={() => setEvidenceItems((prev) => [...prev, emptyEvidence()])}
                className="w-full"
              >
                <Plus className="h-4 w-4 mr-2" />
                Add Evidence
              </Button>
            </CardContent>
          </CollapsibleContent>
        </Card>
      </Collapsible>

      {/* Submit Button */}
      <Button
        size="lg"
        className="w-full text-lg py-6 text-white hover:opacity-90"
        style={{ backgroundColor: '#1a1f71' }}
        onClick={handleSubmit}
        disabled={submitting}
      >
        {submitting ? (
          <>
            <Loader2 className="h-5 w-5 mr-2 animate-spin" />
            Submitting Dispute...
          </>
        ) : (
          'Submit Dispute'
        )}
      </Button>
    </div>
  );
}
