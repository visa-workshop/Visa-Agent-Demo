import { useState, useEffect, useCallback } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { listDisputes, type DisputeSummaryResponse } from '@/lib/api';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import {
  RefreshCw,
  Loader2,
  AlertCircle,
  Plus,
  Pause,
  Play,
} from 'lucide-react';

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

function formatDate(dateStr: string): string {
  try {
    return new Date(dateStr).toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return dateStr;
  }
}

function truncateId(id: string, maxLen = 12): string {
  if (id.length <= maxLen) return id;
  return id.slice(0, maxLen) + '...';
}

export default function DisputeListPage() {
  const [disputes, setDisputes] = useState<DisputeSummaryResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const navigate = useNavigate();

  const fetchDisputes = useCallback(async (showSpinner = false) => {
    if (showSpinner) setLoading(true);
    setRefreshing(true);
    try {
      const data = await listDisputes();
      setDisputes(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch disputes');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    fetchDisputes(true);
  }, [fetchDisputes]);

  useEffect(() => {
    if (!autoRefresh) return;
    const interval = setInterval(() => fetchDisputes(false), 10000);
    return () => clearInterval(interval);
  }, [autoRefresh, fetchDisputes]);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="h-8 w-8 animate-spin text-[#1a1f71]" />
        <span className="ml-3 text-lg text-gray-600">Loading disputes...</span>
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
        <div className="mt-4 flex justify-center">
          <Button onClick={() => fetchDisputes(true)} variant="outline">
            <RefreshCw className="mr-2 h-4 w-4" />
            Retry
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-7xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-[#1a1f71]">All Disputes</h1>
        <div className="flex items-center gap-3">
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
          <Button
            variant="outline"
            size="sm"
            onClick={() => fetchDisputes(false)}
            disabled={refreshing}
          >
            <RefreshCw className={`mr-1 h-3 w-3 ${refreshing ? 'animate-spin' : ''}`} />
            Refresh
          </Button>
          <Link to="/">
            <Button size="sm" className="bg-[#1a1f71] hover:bg-[#141861]">
              <Plus className="mr-1 h-3 w-3" />
              New Dispute
            </Button>
          </Link>
        </div>
      </div>

      {disputes.length === 0 ? (
        <div className="text-center py-16 border rounded-lg bg-gray-50">
          <p className="text-gray-500 text-lg mb-4">No disputes found</p>
          <Link to="/">
            <Button className="bg-[#1a1f71] hover:bg-[#141861]">
              <Plus className="mr-2 h-4 w-4" />
              Submit Your First Dispute
            </Button>
          </Link>
        </div>
      ) : (
        <div className="border rounded-lg">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="font-semibold">Case ID</TableHead>
                <TableHead className="font-semibold">Stage</TableHead>
                <TableHead className="font-semibold">Category</TableHead>
                <TableHead className="font-semibold">Condition</TableHead>
                <TableHead className="font-semibold">Resolution</TableHead>
                <TableHead className="font-semibold">Confidence</TableHead>
                <TableHead className="font-semibold">Created At</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {disputes.map((dispute) => (
                <TableRow
                  key={dispute.case_id}
                  className="cursor-pointer"
                  onClick={() => navigate(`/disputes/${encodeURIComponent(dispute.case_id)}`)}
                >
                  <TableCell>
                    <Link
                      to={`/disputes/${encodeURIComponent(dispute.case_id)}`}
                      className="text-[#1a1f71] hover:underline font-mono text-sm"
                      onClick={(e) => e.stopPropagation()}
                    >
                      {truncateId(dispute.case_id)}
                    </Link>
                  </TableCell>
                  <TableCell>
                    <Badge variant="outline" className={getStageBadgeClasses(dispute.stage)}>
                      {dispute.stage.replace(/_/g, ' ')}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-sm">{dispute.category ?? '-'}</TableCell>
                  <TableCell className="text-sm">{dispute.condition ?? '-'}</TableCell>
                  <TableCell>
                    {dispute.resolution ? (
                      <Badge
                        variant="outline"
                        className={
                          dispute.resolution === 'issuer_win'
                            ? 'bg-green-100 text-green-800 border-green-200'
                            : dispute.resolution === 'acquirer_win'
                              ? 'bg-red-100 text-red-800 border-red-200'
                              : dispute.resolution === 'split_liability'
                                ? 'bg-amber-100 text-amber-800 border-amber-200'
                                : 'bg-gray-100 text-gray-800 border-gray-200'
                        }
                      >
                        {dispute.resolution.replace(/_/g, ' ')}
                      </Badge>
                    ) : (
                      <span className="text-gray-400">-</span>
                    )}
                  </TableCell>
                  <TableCell className="text-sm">
                    {dispute.confidence != null
                      ? `${Math.round(dispute.confidence * 100)}%`
                      : '-'}
                  </TableCell>
                  <TableCell className="text-sm text-gray-600">
                    {formatDate(dispute.created_at)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}
