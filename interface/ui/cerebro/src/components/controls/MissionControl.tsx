/**
 * NEXUS CEREBRO MissionControl
 * V12.1 RETINA: Task Launch & Swarm Mode Selector
 *
 * Exposes all 6 NEXUS Swarm collaboration modes:
 * PARALLEL, SEQUENTIAL, LEAD_SUPPORT, PING_PONG, SPECIALIST, RED_BLUE
 *
 * V12.1 Improvements (Conseiller 2 feedback):
 * - Responsive grid: 3x2 on desktop, 2x3 on mobile
 * - Lucide icons for each mode
 */
import { useState, useCallback } from 'react';
import {
  Zap,
  Play,
  Square,
  Loader2,
  AlertTriangle,
  CheckCircle,
  Info,
  Eraser,
  // V12.1: Icons for Swarm modes
  Layers,
  ListOrdered,
  Users,
  RefreshCw,
  Target,
  Swords,
  type LucideIcon,
} from 'lucide-react';
import { api } from '../../api/client';
import { useEventStore } from '../../stores/eventStore';
import { useGraphStore } from '../../stores/graphStore';

// =============================================================================
// Types
// =============================================================================

type SwarmMode =
  | 'parallel'
  | 'sequential'
  | 'lead_support'
  | 'ping_pong'
  | 'specialist'
  | 'red_blue';

type WorkflowStatus = 'idle' | 'starting' | 'running' | 'stopping' | 'completed' | 'failed';

interface WorkflowStartResponse {
  workflow_id: string;
  status: string;
}

// =============================================================================
// Constants
// =============================================================================

// V12.1: Swarm modes with Lucide icons (Conseiller 2 feedback)
const SWARM_MODES: { value: SwarmMode; label: string; description: string; Icon: LucideIcon }[] = [
  {
    value: 'parallel',
    label: 'PARALLEL',
    description: 'Simultaneous work, merge results',
    Icon: Layers,
  },
  {
    value: 'sequential',
    label: 'SEQUENTIAL',
    description: 'Ordered execution (A then B)',
    Icon: ListOrdered,
  },
  {
    value: 'lead_support',
    label: 'LEAD_SUPPORT',
    description: 'Lead drives, support reviews',
    Icon: Users,
  },
  {
    value: 'ping_pong',
    label: 'PING_PONG',
    description: 'Rapid alternation until convergence',
    Icon: RefreshCw,
  },
  {
    value: 'specialist',
    label: 'SPECIALIST',
    description: 'Single expert handles all',
    Icon: Target,
  },
  {
    value: 'red_blue',
    label: 'RED_BLUE',
    description: 'Adversarial propose/attack/defend',
    Icon: Swords,
  },
];

// =============================================================================
// Component
// =============================================================================

export function MissionControl() {
  // Form state
  const [objective, setObjective] = useState('');
  const [mode, setMode] = useState<SwarmMode>('parallel');

  // Workflow state
  const [workflowId, setWorkflowId] = useState<string | null>(null);
  const [status, setStatus] = useState<WorkflowStatus>('idle');
  const [error, setError] = useState<string | null>(null);

  // Store access for clear board
  const clearEvents = useEventStore((s) => s.clearEvents);
  const clearGraph = useGraphStore((s) => s.clear);

  // Get latest phase from events
  const latestPhaseEvent = useEventStore((s) =>
    s.getLatestEvent('orchestration.phase') || s.getLatestEvent('hive.phase')
  );

  const currentPhase = latestPhaseEvent
    ? (latestPhaseEvent.payload as { phase?: string }).phase
    : null;

  // ---------------------------------------------------------------------------
  // Actions
  // ---------------------------------------------------------------------------

  const engage = useCallback(async () => {
    if (!objective.trim()) return;

    setStatus('starting');
    setError(null);

    try {
      const response = await api.post<WorkflowStartResponse>('/api/workflow/start', {
        task: objective,
        swarm_mode: mode.toUpperCase(),
        complexity: 'MODERATE',
      });

      setWorkflowId(response.workflow_id);
      setStatus('running');
    } catch (err) {
      console.error('[MissionControl] Failed to start workflow:', err);
      setError(err instanceof Error ? err.message : 'Failed to start workflow');
      setStatus('failed');
    }
  }, [objective]);

  const abort = useCallback(async () => {
    if (!workflowId) return;

    setStatus('stopping');
    setError(null);

    try {
      await api.post(`/api/workflow/${workflowId}/stop`, {});
      setStatus('idle');
      setWorkflowId(null);
    } catch (err) {
      console.error('[MissionControl] Failed to stop workflow:', err);
      setError(err instanceof Error ? err.message : 'Failed to stop workflow');
      setStatus('running'); // Revert to running
    }
  }, [workflowId]);

  const reset = useCallback(() => {
    setStatus('idle');
    setWorkflowId(null);
    setError(null);
    setObjective('');
  }, []);

  // V13.0: Clear entire board (reset + clear events + clear graph)
  const clearBoard = useCallback(() => {
    reset();
    clearEvents();
    clearGraph();
  }, [reset, clearEvents, clearGraph]);

  // ---------------------------------------------------------------------------
  // Render Helpers
  // ---------------------------------------------------------------------------

  const isInputDisabled = status !== 'idle' && status !== 'failed';
  const canEngage = objective.trim().length > 0 && (status === 'idle' || status === 'failed');
  const canAbort = status === 'running' || status === 'starting';

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div className="bg-gray-800/80 backdrop-blur rounded-lg border border-gray-700 overflow-hidden">
      {/* Header */}
      <div className="px-4 py-3 border-b border-gray-700 flex items-center gap-2">
        <Zap className="text-yellow-400" size={18} />
        <h2 className="text-sm font-bold uppercase tracking-wider text-white">
          Mission Control
        </h2>
        {currentPhase && (
          <span className="ml-auto text-xs px-2 py-1 rounded bg-cyan-900/50 text-cyan-300 border border-cyan-800">
            {currentPhase}
          </span>
        )}
        {/* V13.0: Clear Board button */}
        <button
          onClick={clearBoard}
          disabled={status === 'running' || status === 'starting'}
          title="Clear Board"
          className={`${currentPhase ? '' : 'ml-auto'} p-1.5 rounded transition-colors ${
            status === 'running' || status === 'starting'
              ? 'text-gray-600 cursor-not-allowed'
              : 'text-gray-400 hover:text-white hover:bg-gray-700'
          }`}
        >
          <Eraser size={16} />
        </button>
      </div>

      <div className="p-4 space-y-4">
        {/* Objective Input */}
        <div>
          <label className="block text-xs font-medium text-gray-400 mb-1.5">
            Mission Objective
          </label>
          <textarea
            value={objective}
            onChange={(e) => setObjective(e.target.value)}
            placeholder="Enter your task objective..."
            disabled={isInputDisabled}
            className={`
              w-full h-24 px-3 py-2 rounded-lg border text-sm resize-none
              bg-gray-900 transition-colors
              ${
                isInputDisabled
                  ? 'border-gray-700 text-gray-500 cursor-not-allowed'
                  : 'border-gray-600 text-white focus:border-cyan-500 focus:ring-1 focus:ring-cyan-500'
              }
              placeholder:text-gray-600
            `}
          />
        </div>

        {/* Mode Selector - V12.1: Responsive grid 2x3 mobile, 3x2 desktop */}
        <div>
          <label className="block text-xs font-medium text-gray-400 mb-1.5">
            Swarm Mode
          </label>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
            {SWARM_MODES.map((m) => {
              const IconComponent = m.Icon;
              return (
                <button
                  key={m.value}
                  onClick={() => setMode(m.value)}
                  disabled={isInputDisabled}
                  title={m.description}
                  data-testid={`mode-${m.value.toUpperCase()}`}
                  className={`
                    px-2 py-2 rounded border text-xs font-medium transition-all
                    flex items-center gap-2
                    ${
                      mode === m.value
                        ? 'bg-cyan-900/50 border-cyan-500 text-cyan-300'
                        : isInputDisabled
                        ? 'bg-gray-800 border-gray-700 text-gray-600 cursor-not-allowed'
                        : 'bg-gray-800 border-gray-600 text-gray-400 hover:border-gray-500 hover:text-gray-300'
                    }
                  `}
                >
                  <IconComponent size={14} className="flex-shrink-0 opacity-70" />
                  <span className="truncate hidden md:inline">{m.label}</span>
                  <span className="truncate md:hidden">{m.label.split('_')[0]}</span>
                </button>
              );
            })}
          </div>
          <p className="mt-1.5 text-xs text-gray-500 flex items-center gap-1">
            <Info size={10} />
            {SWARM_MODES.find((m) => m.value === mode)?.description}
          </p>
        </div>

        {/* Action Buttons */}
        <div className="flex gap-2">
          {/* Engage Button */}
          <button
            onClick={engage}
            disabled={!canEngage}
            className={`
              flex-1 flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg
              font-bold text-sm transition-all
              ${
                canEngage
                  ? 'bg-green-600 hover:bg-green-700 text-white shadow-lg shadow-green-900/30'
                  : 'bg-gray-700 text-gray-500 cursor-not-allowed'
              }
            `}
          >
            {status === 'starting' ? (
              <>
                <Loader2 size={16} className="animate-spin" />
                LAUNCHING...
              </>
            ) : (
              <>
                <Play size={16} />
                ENGAGE
              </>
            )}
          </button>

          {/* Abort Button */}
          <button
            onClick={abort}
            disabled={!canAbort}
            className={`
              px-4 py-2.5 rounded-lg font-bold text-sm transition-all
              ${
                canAbort
                  ? 'bg-red-600 hover:bg-red-700 text-white'
                  : 'bg-gray-700 text-gray-500 cursor-not-allowed'
              }
            `}
          >
            {status === 'stopping' ? (
              <Loader2 size={16} className="animate-spin" />
            ) : (
              <Square size={16} />
            )}
          </button>
        </div>

        {/* Status Display */}
        {workflowId && (
          <div className="pt-2 border-t border-gray-700">
            <div className="flex items-center gap-2 text-xs">
              {status === 'running' && (
                <span className="flex items-center gap-1.5 text-green-400">
                  <div className="w-2 h-2 rounded-full bg-green-400 animate-pulse" />
                  Running
                </span>
              )}
              {status === 'completed' && (
                <span className="flex items-center gap-1.5 text-blue-400">
                  <CheckCircle size={12} />
                  Completed
                </span>
              )}
              <span className="text-gray-500 ml-auto font-mono">
                {workflowId.slice(0, 8)}...
              </span>
            </div>
          </div>
        )}

        {/* Error Display */}
        {error && (
          <div className="flex items-start gap-2 p-3 rounded-lg bg-red-900/20 border border-red-800">
            <AlertTriangle size={14} className="text-red-400 flex-shrink-0 mt-0.5" />
            <div>
              <p className="text-sm text-red-300">{error}</p>
              <button
                onClick={reset}
                className="text-xs text-red-400 hover:text-red-300 mt-1 underline"
              >
                Reset
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
