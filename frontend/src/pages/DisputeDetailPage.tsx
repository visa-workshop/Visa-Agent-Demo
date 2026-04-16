import { useState, useEffect, useCallback } from 'react';
import { useParams, Link } from 'react-router-dom';
import {
  getDisputeDetail,
  type DisputeDetailResponse,
  type RuleEvaluation,
  type Evidence,
  type StageHistoryEntry,
} from '@/lib/api';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Separator } from '@/components/ui/separator';
import { Progress } from '@/components/ui/progress';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import {
  ArrowLeft,
  RefreshCw,
  Loader2,
  AlertCircle,
  CheckCircle,
  XCircle,
  Clock,
  Plus,
  Pause,
  Play,
  AlertTriangle,
  FileText,
  Scale,
  CreditCard,
  Shield,
  History,
} from 'lucide-react';

const TERMINAL_STAGES = ['resolved', 'rejected', 'failed'];

function getStageBadgeClasses(stage: string): string {
  switch (stage) {
    case 'resolved':
      return 'bg-green-100 text-green-800 border-green-200';
    case 'rejected':
    case 'failed':
      return 'bg-red-100 text-red-800 border-red-200';
    case 'human_review':
      return 'bg-amber-100 text-amber-800 border-amber-200';
    case 'processing':
    case 'rule_evaluation':
    case 'decision':
      return 'bg-blue-100 text-blue-800 border-blue-200';
    case 'intake':
    case 'validation':
    case 'categorization':
      return 'bg-gray-100 text-gray-800 border-gray-200';
    case 'pre_arbitration':
    case 'arbitration':
      return 'bg-purple-100 text-purple-800 border-purple-200';
    default:
      return 'bg-gray-100 text-gray-800 border-gray-200';
  }
}

function getResolutionBadgeClasses(resolution: string): string {
  switch (resolution) {
    case 'issuer_win':
      return 'bg-green-100 text-green-800 border-green-200';
    case 'acquirer_win':
      return 'bg-red-100 text-red-800 border-red-200';
    case 'split_liability':
      return 'bg-amber-100 text-amber-800 border-amber-200';
    default:
      return 'bg-gray-100 text-gray-800 border-gray-200';
  }
}

function formatDate(dateStr: string): string {
  try {
    return new Date(dateStr).toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    });
  } catch {
    return dateStr;
  }
}

function formatCurrency(amount: number, currency: string): string {
  try {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: currency.toUpperCase(),
    }).format(amount);
  } catch {
    return `${amount} ${currency}`;
  }
}

export default function DisputeDetailPage() {
  const { caseId } = useParams<{ caseId: string }>();
  const [dispute, setDispute] = useState<DisputeDetailResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const fetchDetail = useCallback(
    async (showSpinner = false) => {
      if (!caseId) return;
      if (showSpinner) setLoading(true);
      setRefreshing(true);
      try {
        const data = await getDisputeDetail(caseId);
        setDispute(data);
        setError(null);
      } catch (err) {
        setError(
          err instanceof Error ? err.message : 'Failed to fetch dispute details'
        );
      } finally {
        setLoading(false);
        setRefreshing(false);
      }
    },
    [caseId]
  );

  useEffect(() => {
    fetchDetail(true);
  }, [fetchDetail]);

  useEffect(() => {
    if (!autoRefresh || !dispute) return;
    if (TERMINAL_STAGES.includes(dispute.stage)) return;
    const interval = setInterval(() => fetchDetail(false), 5000);
    return () => clearInterval(interval);
  }, [autoRefresh, dispute, fetchDetail]);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="h-8 w-8 animate-spin text-[#1a1f71]" />
        <span className="ml-3 text-lg text-gray-600">Loading dispute details...</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="max-w-2xl mx-auto mt-8">
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>Error</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
        <div className="mt-4 flex gap-3 justify-center">
          <Link to="/disputes">
            <Button variant="outline">
              <ArrowLeft className="mr-2 h-4 w-4" />
              Back to List
            </Button>
          </Link>
          <Button onClick={() => fetchDetail(true)} variant="outline">
            <RefreshCw className="mr-2 h-4 w-4" />
            Retry
          </Button>
        </div>
      </div>
    );
  }

  if (!dispute) return null;

  const isTerminal = TERMINAL_STAGES.includes(dispute.stage);

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      {/* Navigation Bar */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Link to="/disputes">
            <Button variant="outline" size="sm">
              <ArrowLeft className="mr-1 h-3 w-3" />
              Back to List
            </Button>
          </Link>
          <Link to="/">
            <Button variant="outline" size="sm">
              <Plus className="mr-1 h-3 w-3" />
              Submit New Dispute
            </Button>
          </Link>
        </div>
        <div className="flex items-center gap-3">
          {!isTerminal && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => setAutoRefresh(!autoRefresh)}
              className={autoRefresh ? 'text-green-600 border-green-300' : 'text-gray-500'}
            >
              {autoRefresh ? (
                <>
                  <Pause className="mr-1 h-3 w-3" />
                  Auto-refresh ON
                </>
              ) : (
                <>
                  <Play className="mr-1 h-3 w-3" />
                  Auto-refresh OFF
                </>
              )}
            </Button>
          )}
          <Button
            variant="outline"
            size="sm"
            onClick={() => fetchDetail(false)}
            disabled={refreshing}
          >
            <RefreshCw className={`mr-1 h-3 w-3 ${refreshing ? 'animate-spin' : ''}`} />
            Refresh
          </Button>
        </div>
      </div>

      {/* Header Section */}
      <Card>
        <CardHeader>
          <div className="flex items-start justify-between">
            <div>
              <CardTitle className="text-xl text-[#1a1f71]">
                Case: {dispute.case_id}
              </CardTitle>
              <div className="flex items-center gap-3 mt-2">
                <Badge variant="outline" className={getStageBadgeClasses(dispute.stage)}>
                  {dispute.stage.replace(/_/g, ' ')}
                </Badge>
                {dispute.category && (
                  <span className="text-sm text-gray-600">{dispute.category}</span>
                )}
                {dispute.condition && (
                  <span className="text-sm text-gray-500">| {dispute.condition}</span>
                )}
              </div>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
            <div>
              <span className="text-gray-500">Created</span>
              <p className="font-medium">{formatDate(dispute.created_at)}</p>
            </div>
            <div>
              <span className="text-gray-500">Updated</span>
              <p className="font-medium">{formatDate(dispute.updated_at)}</p>
            </div>
            <div>
              <span className="text-gray-500">Category</span>
              <p className="font-medium">{dispute.category ?? '-'}</p>
            </div>
            <div>
              <span className="text-gray-500">Condition</span>
              <p className="font-medium">{dispute.condition ?? '-'}</p>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Decision Section */}
      {dispute.resolution && (
        <Card>
          <CardHeader>
            <CardTitle className="text-lg text-[#1a1f71] flex items-center gap-2">
              <Scale className="h-5 w-5" />
              Decision
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex items-center gap-4">
              <div>
                <span className="text-sm text-gray-500">Resolution</span>
                <div className="mt-1">
                  <Badge
                    variant="outline"
                    className={`text-base px-3 py-1 ${getResolutionBadgeClasses(dispute.resolution)}`}
                  >
                    {dispute.resolution.replace(/_/g, ' ')}
                  </Badge>
                </div>
              </div>
              {dispute.confidence != null && (
                <div className="flex-1 max-w-xs">
                  <span className="text-sm text-gray-500">Confidence</span>
                  <div className="flex items-center gap-2 mt-1">
                    <Progress value={dispute.confidence * 100} className="h-3" />
                    <span className="text-sm font-semibold">
                      {Math.round(dispute.confidence * 100)}%
                    </span>
                  </div>
                </div>
              )}
            </div>

            {dispute.rationale && (
              <div>
                <span className="text-sm text-gray-500">Rationale</span>
                <p className="mt-1 text-sm leading-relaxed bg-gray-50 rounded-md p-3">
                  {dispute.rationale}
                </p>
              </div>
            )}

            <div className="flex items-center gap-6 text-sm">
              {dispute.decided_by && (
                <div>
                  <span className="text-gray-500">Decided By</span>
                  <p className="font-medium">{dispute.decided_by}</p>
                </div>
              )}
              {dispute.requires_human_review && (
                <Badge variant="outline" className="bg-amber-100 text-amber-800 border-amber-200">
                  <AlertTriangle className="mr-1 h-3 w-3" />
                  Human Review Required
                </Badge>
              )}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Transaction Section */}
      <Card>
        <CardHeader>
          <CardTitle className="text-lg text-[#1a1f71] flex items-center gap-2">
            <CreditCard className="h-5 w-5" />
            Transaction Details
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
            <div>
              <span className="text-gray-500">Transaction ID</span>
              <p className="font-mono font-medium">{dispute.transaction_id}</p>
            </div>
            <div>
              <span className="text-gray-500">Amount</span>
              <p className="font-medium text-lg">
                {formatCurrency(dispute.transaction_amount, dispute.transaction_currency)}
              </p>
            </div>
            <div>
              <span className="text-gray-500">Merchant</span>
              <p className="font-medium">{dispute.merchant_name}</p>
            </div>
            <div>
              <span className="text-gray-500">Environment</span>
              <p className="font-medium">{dispute.transaction_environment.replace(/_/g, ' ')}</p>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Rule Evaluations Section */}
      {dispute.rule_evaluations.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-lg text-[#1a1f71] flex items-center gap-2">
              <Shield className="h-5 w-5" />
              Rule Evaluations ({dispute.rule_evaluations.length})
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-3">
              {dispute.rule_evaluations.map((rule: RuleEvaluation, index: number) => (
                <div key={index} className="border rounded-lg p-3">
                  <div className="flex items-start justify-between">
                    <div className="flex-1">
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-sm font-semibold text-[#1a1f71]">
                          {rule.rule_id}
                        </span>
                        <span className="text-xs text-gray-400">|</span>
                        <span className="text-sm text-gray-600">{rule.rule_section}</span>
                      </div>
                      <p className="text-sm mt-1">{rule.description}</p>
                      {rule.details && (
                        <p className="text-xs text-gray-500 mt-1">{rule.details}</p>
                      )}
                    </div>
                    <div className="ml-3 flex-shrink-0">
                      {rule.satisfied ? (
                        <Badge variant="outline" className="bg-green-100 text-green-800 border-green-200">
                          <CheckCircle className="mr-1 h-3 w-3" />
                          Satisfied
                        </Badge>
                      ) : (
                        <Badge variant="outline" className="bg-red-100 text-red-800 border-red-200">
                          <XCircle className="mr-1 h-3 w-3" />
                          Not Satisfied
                        </Badge>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Evidence Section */}
      {dispute.evidence.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-lg text-[#1a1f71] flex items-center gap-2">
              <FileText className="h-5 w-5" />
              Evidence ({dispute.evidence.length})
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-3">
              {dispute.evidence.map((item: Evidence, index: number) => (
                <div key={index} className="border rounded-lg p-3">
                  <div className="flex items-start justify-between">
                    <div className="flex-1">
                      <p className="text-sm font-medium">{item.description}</p>
                      <div className="flex items-center gap-3 mt-1 text-xs text-gray-500">
                        <span>Type: {item.type}</span>
                        <span>Provided by: {item.provided_by}</span>
                        <span className="font-mono">ID: {item.evidence_id}</span>
                      </div>
                    </div>
                    <div className="ml-3 flex-shrink-0">
                      {item.is_compelling ? (
                        <Badge variant="outline" className="bg-green-100 text-green-800 border-green-200">
                          Compelling
                        </Badge>
                      ) : (
                        <Badge variant="outline" className="bg-gray-100 text-gray-600 border-gray-200">
                          Standard
                        </Badge>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Processing Timeline */}
      {dispute.stage_history.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-lg text-[#1a1f71] flex items-center gap-2">
              <History className="h-5 w-5" />
              Processing Timeline
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="relative">
              <div className="absolute left-3 top-0 bottom-0 w-0.5 bg-gray-200" />
              <div className="space-y-4">
                {dispute.stage_history.map((entry: StageHistoryEntry, index: number) => (
                  <div key={index} className="relative pl-8">
                    <div className="absolute left-1.5 top-1.5 w-3 h-3 rounded-full bg-[#1a1f71] border-2 border-white" />
                    <div>
                      <div className="flex items-center gap-2">
                        <Badge variant="outline" className={getStageBadgeClasses(entry.from_stage)}>
                          {entry.from_stage.replace(/_/g, ' ')}
                        </Badge>
                        <span className="text-gray-400">&rarr;</span>
                        <Badge variant="outline" className={getStageBadgeClasses(entry.to_stage)}>
                          {entry.to_stage.replace(/_/g, ' ')}
                        </Badge>
                      </div>
                      <div className="flex items-center gap-2 mt-1 text-xs text-gray-500">
                        <Clock className="h-3 w-3" />
                        {formatDate(entry.timestamp)}
                      </div>
                      {entry.note && (
                        <p className="text-sm text-gray-600 mt-1">{entry.note}</p>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {dispute.processing_notes.length > 0 && (
              <>
                <Separator className="my-4" />
                <div>
                  <h4 className="text-sm font-semibold text-gray-700 mb-2">Processing Notes</h4>
                  <ul className="space-y-1">
                    {dispute.processing_notes.map((note: string, index: number) => (
                      <li key={index} className="text-sm text-gray-600 flex items-start gap-2">
                        <span className="text-[#f7b600] mt-0.5">&#8226;</span>
                        {note}
                      </li>
                    ))}
                  </ul>
                </div>
              </>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
