/**
 * NEXUS CEREBRO API Types
 * V11.6.2 IRONCLAD
 */

// Authentication
export interface LoginRequest {
  username: string;
  password: string;
}

export interface LoginResponse {
  access_token: string;
  token_type: 'bearer';
  expires_in: number;
  tenant_id: string;
  user_id: string;
}

export interface UserInfo {
  user_id: string;
  tenant_id: string;
  workspace_id: string;
  authenticated: boolean;
}

// State Snapshot
export interface StateSnapshot {
  phase: PhaseState | null;
  nodes: Record<string, GraphNode>;
  logs: LogEntry[];
  pending_interactions: PendingInteraction[];
  tenant_id: string;
  workspace_id: string;
}

export interface PhaseState {
  current_phase: string;
  status: 'pending' | 'in_progress' | 'completed' | 'failed';
  timestamp: string;
}

export interface GraphNode {
  id: string;
  type: 'agent' | 'tool' | 'task';
  data: {
    name: string;
    status: 'active' | 'idle' | 'error';
    role?: string;
  };
  position: { x: number; y: number };
}

export interface LogEntry {
  event_id: string;
  event_type: string;
  level: 'DEBUG' | 'INFO' | 'WARNING' | 'ERROR';
  message: string;
  timestamp: string;
}

// Interactions
export interface PendingInteraction {
  request_id: string;
  interaction_type: 'ask' | 'confirm' | 'choose';
  prompt: string;
  choices?: string[];
  default?: string;
  timestamp: string;
}

export interface InteractionReply {
  response: string | boolean | number;
}

export interface InteractionResult {
  status: 'resolved';
  request_id: string;
}

// Workflow
export interface WorkflowStartRequest {
  task: string;
  complexity?: 'TRIVIAL' | 'SIMPLE' | 'MODERATE' | 'COMPLEX' | 'EXPERT';
}

export interface WorkflowStatus {
  workflow_id: string;
  status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled';
  task: string;
  tenant_id: string;
  result?: unknown;
  error?: string;
}

// Files
export interface FileContent {
  path: string;
  content: string;
  size: number;
}

export interface FileInfo {
  path: string;
  exists: boolean;
  size: number;
  is_file: boolean;
  is_directory: boolean;
  can_read: boolean;
}

export interface FileSaveRequest {
  path: string;
  content: string;
}

// Timeline (V12.4 P2.1)
export * from './timeline';
