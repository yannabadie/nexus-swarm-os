/**
 * NEXUS CEREBRO - Causality Timeline View
 * V12.4 P2.1 OBSERVABILITY
 *
 * Visualizes the decision chain for a task execution with:
 * - Chronological event timeline
 * - Cost, latency, tokens per event
 * - State diff viewer
 * - Filtering and search
 */

import { useEffect, useState } from 'react';
import type { TimelineEvent, TimelineResponse, TimelineFilter } from '../../types/timeline';
import { apiClient } from '../../api/client';

interface CausalityTimelineProps {
  taskId: string;
  autoRefresh?: boolean;
  refreshInterval?: number;
}

interface TimelineEventCardProps {
  event: TimelineEvent;
  showDiff?: boolean;
  showCost?: boolean;
}

function TimelineEventCard({ event, showDiff = true, showCost = true }: TimelineEventCardProps) {
  const [diffExpanded, setDiffExpanded] = useState(false);

  // Format timestamp
  const formatTime = (timestamp: string) => {
    return new Date(timestamp).toLocaleTimeString('fr-FR', {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      fractionalSecondDigits: 3,
    });
  };

  // Format cost
  const formatCost = (cost?: number) => {
    if (!cost) return '-';
    return `$${cost.toFixed(6)}`;
  };

  // Get result color
  const getResultColor = (result: string) => {
    switch (result) {
      case 'success': return 'text-green-600 bg-green-50';
      case 'failure': return 'text-red-600 bg-red-50';
      case 'rollback': return 'text-yellow-600 bg-yellow-50';
      default: return 'text-gray-600 bg-gray-50';
    }
  };

  // Get phase icon
  const getPhaseIcon = (phase: string) => {
    const icons: Record<string, string> = {
      analysis: '🔍',
      debate: '💬',
      architecture: '🏗️',
      execution: '⚙️',
      diagnosis: '🔬',
      retry: '🔄',
      consolidation: '📦',
    };
    return icons[phase] || '📌';
  };

  return (
    <div className="timeline-event border-l-4 border-blue-500 pl-4 py-3 mb-4 bg-white rounded-r shadow-sm hover:shadow-md transition-shadow">
      {/* Header */}
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-3">
          <span className="text-2xl">{getPhaseIcon(event.phase)}</span>
          <div>
            <span className="font-semibold text-gray-800">{event.action}</span>
            <span className="text-gray-500 text-sm ml-2">- {event.agent_id}</span>
            {event.model && (
              <span className="text-gray-400 text-sm ml-2">- {event.model}</span>
            )}
          </div>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-sm text-gray-500">{formatTime(event.timestamp)}</span>
          <span className={`px-2 py-1 rounded text-xs font-medium ${getResultColor(event.result)}`}>
            {event.result}
          </span>
        </div>
      </div>

      {/* Metrics */}
      <div className="flex gap-4 text-sm text-gray-600 mb-2">
        {event.latency_ms && (
          <div className="flex items-center gap-1">
            <span className="text-gray-500">⏱️</span>
            <span>{event.latency_ms}ms</span>
          </div>
        )}
        {event.tokens && (
          <div className="flex items-center gap-1">
            <span className="text-gray-500">🔢</span>
            <span>
              {event.tokens.input}↓ / {event.tokens.output}↑
              {event.tokens.cache_read && (
                <span className="text-green-600 ml-1">(💾 {event.tokens.cache_read})</span>
              )}
            </span>
          </div>
        )}
        {showCost && event.cost && (
          <div className="flex items-center gap-1">
            <span className="text-gray-500">💰</span>
            <span>{formatCost(event.cost)}</span>
          </div>
        )}
      </div>

      {/* Error message */}
      {event.error && (
        <div className="bg-red-50 border border-red-200 rounded p-2 text-sm text-red-700 mb-2">
          <strong>Error:</strong> {event.error}
        </div>
      )}

      {/* State diff */}
      {showDiff && event.diff && Object.keys(event.diff).length > 0 && (
        <div className="mt-2">
          <button
            onClick={() => setDiffExpanded(!diffExpanded)}
            className="text-sm text-blue-600 hover:text-blue-800 font-medium"
          >
            {diffExpanded ? 'v' : '>'} State Changes ({Object.keys(event.diff).length})
          </button>
          {diffExpanded && (
            <pre className="mt-2 bg-gray-50 border border-gray-200 rounded p-3 text-xs overflow-x-auto">
              {JSON.stringify(event.diff, null, 2)}
            </pre>
          )}
        </div>
      )}
    </div>
  );
}

export function CausalityTimeline({
  taskId,
  autoRefresh = false,
  refreshInterval = 5000,
}: CausalityTimelineProps) {
  const [timeline, setTimeline] = useState<TimelineResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<TimelineFilter>({});

  // Fetch timeline events
  const fetchTimeline = async () => {
    try {
      setLoading(true);
      setError(null);
      const response = await apiClient.get<TimelineResponse>(`/timeline/${taskId}`);
      setTimeline(response.data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch timeline');
    } finally {
      setLoading(false);
    }
  };

  // Initial fetch and auto-refresh
  useEffect(() => {
    fetchTimeline();

    if (autoRefresh) {
      const interval = setInterval(fetchTimeline, refreshInterval);
      return () => clearInterval(interval);
    }
  }, [taskId, autoRefresh, refreshInterval]);

  // Apply filters
  const filteredEvents = timeline?.events.filter((event) => {
    if (filter.phase && event.phase !== filter.phase) return false;
    if (filter.agent_id && event.agent_id !== filter.agent_id) return false;
    if (filter.result && event.result !== filter.result) return false;
    if (filter.min_cost && (!event.cost || event.cost < filter.min_cost)) return false;
    if (filter.max_latency && (!event.latency_ms || event.latency_ms > filter.max_latency)) return false;
    return true;
  }) || [];

  if (loading && !timeline) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-gray-500">Loading timeline...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-red-50 border border-red-200 rounded p-4 text-red-700">
        <strong>Error:</strong> {error}
      </div>
    );
  }

  if (!timeline || timeline.events.length === 0) {
    return (
      <div className="text-center text-gray-500 py-8">
        No timeline events found for task {taskId}
      </div>
    );
  }

  return (
    <div className="causality-timeline">
      {/* Header with summary */}
      <div className="bg-gradient-to-r from-blue-50 to-indigo-50 border border-blue-200 rounded-lg p-4 mb-6">
        <h2 className="text-xl font-bold text-gray-800 mb-3">
          Causality Timeline - Task {taskId}
        </h2>
        <div className="grid grid-cols-4 gap-4 text-sm">
          <div>
            <div className="text-gray-500 mb-1">Total Events</div>
            <div className="text-2xl font-bold text-gray-800">{timeline.events.length}</div>
          </div>
          <div>
            <div className="text-gray-500 mb-1">Total Cost</div>
            <div className="text-2xl font-bold text-green-600">${timeline.total_cost.toFixed(4)}</div>
          </div>
          <div>
            <div className="text-gray-500 mb-1">Total Tokens</div>
            <div className="text-2xl font-bold text-blue-600">
              {(timeline.total_tokens.input + timeline.total_tokens.output).toLocaleString()}
            </div>
          </div>
          <div>
            <div className="text-gray-500 mb-1">Duration</div>
            <div className="text-2xl font-bold text-purple-600">
              {(timeline.duration_ms / 1000).toFixed(1)}s
            </div>
          </div>
        </div>
      </div>

      {/* Filters */}
      <div className="mb-4 flex gap-2 flex-wrap">
        <select
          className="px-3 py-1 border border-gray-300 rounded text-sm"
          value={filter.result || ''}
          onChange={(e) => setFilter({ ...filter, result: e.target.value as any || undefined })}
        >
          <option value="">All Results</option>
          <option value="success">Success</option>
          <option value="failure">Failure</option>
          <option value="rollback">Rollback</option>
        </select>

        <select
          className="px-3 py-1 border border-gray-300 rounded text-sm"
          value={filter.phase || ''}
          onChange={(e) => setFilter({ ...filter, phase: e.target.value as any || undefined })}
        >
          <option value="">All Phases</option>
          <option value="analysis">Analysis</option>
          <option value="debate">Debate</option>
          <option value="architecture">Architecture</option>
          <option value="execution">Execution</option>
          <option value="diagnosis">Diagnosis</option>
          <option value="retry">Retry</option>
          <option value="consolidation">Consolidation</option>
        </select>

        {Object.keys(filter).length > 0 && (
          <button
            className="px-3 py-1 bg-gray-200 hover:bg-gray-300 rounded text-sm"
            onClick={() => setFilter({})}
          >
            Clear Filters
          </button>
        )}

        <div className="ml-auto text-sm text-gray-500">
          Showing {filteredEvents.length} of {timeline.events.length} events
        </div>
      </div>

      {/* Timeline events */}
      <div className="timeline-events">
        {filteredEvents.map((event, idx) => (
          <TimelineEventCard
            key={`${event.timestamp}-${idx}`}
            event={event}
            showDiff={true}
            showCost={true}
          />
        ))}
      </div>
    </div>
  );
}
