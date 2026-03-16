/**
 * NEXUS CEREBRO WebSocket Event Types
 * Maps to core/events/types.py CerebroEventType
 */

export interface CerebroEvent {
  event_type: CerebroEventType;
  payload: Record<string, unknown>;
  timestamp: string;
  event_id: string;
  correlation_id?: string;
}

// Event type enum matching backend
export type CerebroEventType =
  // Interaction events (Human-in-the-Loop)
  | 'interaction.ask'
  | 'interaction.confirm'
  | 'interaction.choose'
  | 'interaction.announce'
  | 'interaction.progress'
  // Orchestration events
  | 'orchestration.state_change'
  | 'orchestration.phase_start'
  | 'orchestration.phase_end'
  // Agent events
  | 'agent.speak'
  | 'agent.tool_call'
  | 'agent.tool_result'
  // Swarm events
  | 'swarm.mode_selected'
  | 'swarm.negotiation'
  | 'swarm.phase_change'
  // HiveMind events
  | 'hive.state_change'
  | 'hive.phase_start'
  | 'hive.phase_end'
  // Graph events (for React Flow)
  | 'graph.node_spawn'
  | 'graph.node_update'
  | 'graph.edge_message'
  // System events
  | 'system.log'
  | 'system.error'
  | 'system.heartbeat'
  | 'system.connected'
  | 'system.warning';

// Event type colors for UI
export const EVENT_TYPE_COLORS: Record<string, string> = {
  interaction: 'text-yellow-400',
  orchestration: 'text-blue-400',
  agent: 'text-green-400',
  swarm: 'text-purple-400',
  hive: 'text-pink-400',
  graph: 'text-cyan-400',
  system: 'text-gray-400',
};

// Helper to get color for event type
export function getEventColor(eventType: string): string {
  const prefix = eventType.split('.')[0];
  return EVENT_TYPE_COLORS[prefix] || 'text-white';
}

// System message types
export interface SystemConnectedPayload {
  tenant_id: string;
  workspace_id: string;
  filter: string[] | 'all';
}

export interface SystemLogPayload {
  level: 'DEBUG' | 'INFO' | 'WARNING' | 'ERROR';
  message: string;
  logger?: string;
}

// Interaction payloads
export interface InteractionAskPayload {
  prompt: string;
  default?: string;
  request_id: string;
}

export interface InteractionChoosePayload {
  prompt: string;
  options: string[];
  request_id: string;
}

// Agent payloads
export interface AgentSpeakPayload {
  agent: 'claude' | 'gemini';
  message: string;
  correlation_id?: string;
}

export interface AgentToolCallPayload {
  agent: 'claude' | 'gemini';
  tool: string;
  input: Record<string, unknown>;
  correlation_id?: string;
}

// Graph payloads
export interface GraphNodeSpawnPayload {
  node_id: string;
  type: 'agent' | 'tool' | 'task';
  data: {
    name: string;
    status: string;
    role?: string;
  };
  position: { x: number; y: number };
}

export interface GraphEdgeMessagePayload {
  from: string;
  to: string;
  message: string;
  timestamp: string;
}
