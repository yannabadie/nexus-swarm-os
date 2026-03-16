/**
 * NEXUS CEREBRO - Causality Timeline Types
 * V12.4 P2.1 OBSERVABILITY
 */

export type PhaseType =
  | 'analysis'
  | 'debate'
  | 'architecture'
  | 'execution'
  | 'diagnosis'
  | 'retry'
  | 'consolidation';

export type ActionType =
  | 'llm_call'
  | 'tool_exec'
  | 'snapshot'
  | 'transition'
  | 'validation';

export type ResultType = 'success' | 'failure' | 'rollback' | 'pending';

export interface TokenMetrics {
  input: number;
  output: number;
  cache_creation?: number;
  cache_read?: number;
}

export interface TimelineEvent {
  timestamp: string;
  task_id: string;
  phase: PhaseType;
  agent_id: string;
  action: ActionType;
  model?: string;
  tokens?: TokenMetrics;
  cost?: number;
  latency_ms?: number;
  result: ResultType;
  diff?: Record<string, unknown>;  // State changes
  error?: string;
  metadata?: Record<string, unknown>;
}

export interface TimelineResponse {
  events: TimelineEvent[];
  total_cost: number;
  total_tokens: {
    input: number;
    output: number;
    cache_read: number;
  };
  duration_ms: number;
}

export interface TimelineFilter {
  phase?: PhaseType;
  agent_id?: string;
  result?: ResultType;
  min_cost?: number;
  max_latency?: number;
}
