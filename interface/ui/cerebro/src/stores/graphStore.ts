/**
 * NEXUS CEREBRO Graph Store
 * V12.1 RETINA: Dedicated state for HiveMap visualization
 *
 * Handles graph.* WebSocket events and maintains node/edge state
 * for the custom SVG graph renderer.
 *
 * V12.1 Improvements (Conseiller 2 feedback):
 * - Performance monitoring (nodeCount, shouldUseSimpleRenderer)
 * - Threshold at 50 nodes for simplified rendering
 */
import { create } from 'zustand';

// =============================================================================
// Types
// =============================================================================

export type NodeType = 'agent' | 'tool' | 'task';
export type NodeStatus = 'idle' | 'working' | 'done' | 'error';

export interface GraphNodeData {
  name: string;
  status: NodeStatus;
  role?: string;
  lastMessage?: string;
}

export interface GraphNode {
  id: string;
  type: NodeType;
  data: GraphNodeData;
  position: { x: number; y: number };
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  label?: string;
  animated?: boolean;
  timestamp?: number;
}

interface GraphStore {
  // State
  nodes: GraphNode[];
  edges: GraphEdge[];

  // V12.1 RETINA: Performance monitoring (Conseiller 2)
  // When > 50 nodes, UI should simplify rendering
  nodeCount: number;
  shouldUseSimpleRenderer: boolean;
  readonly NODE_THRESHOLD: number;

  // Node actions
  addNode: (node: GraphNode) => void;
  updateNode: (id: string, data: Partial<GraphNodeData>) => void;
  removeNode: (id: string) => void;

  // Edge actions
  addEdge: (edge: GraphEdge) => void;
  removeEdge: (id: string) => void;

  // Bulk actions
  setNodes: (nodes: GraphNode[]) => void;
  setEdges: (edges: GraphEdge[]) => void;
  clear: () => void;

  // Layout
  autoLayout: () => void;

  // Helpers
  getNodeById: (id: string) => GraphNode | undefined;
}

// =============================================================================
// Layout Constants
// =============================================================================

const LAYOUT = {
  // Y positions by node type (top-down hierarchy)
  ROW_Y: {
    agent: 50,
    task: 200,
    tool: 350,
  },
  // Node dimensions
  NODE_WIDTH: 140,
  NODE_HEIGHT: 70,
  // Spacing
  HORIZONTAL_GAP: 180,
  CANVAS_PADDING: 60,
} as const;

// =============================================================================
// Store
// =============================================================================

// V12.1 RETINA: Performance threshold (Conseiller 2 feedback)
const NODE_PERFORMANCE_THRESHOLD = 50;

export const useGraphStore = create<GraphStore>((set, get) => ({
  nodes: [],
  edges: [],

  // V12.1 RETINA: Performance monitoring
  NODE_THRESHOLD: NODE_PERFORMANCE_THRESHOLD,
  get nodeCount() {
    return get().nodes.length;
  },
  get shouldUseSimpleRenderer() {
    return get().nodes.length > NODE_PERFORMANCE_THRESHOLD;
  },

  // ---------------------------------------------------------------------------
  // Node Actions
  // ---------------------------------------------------------------------------

  addNode: (node: GraphNode) => {
    set((state) => {
      // Replace if exists, otherwise add
      const exists = state.nodes.find((n) => n.id === node.id);
      if (exists) {
        return {
          nodes: state.nodes.map((n) => (n.id === node.id ? node : n)),
        };
      }
      return {
        nodes: [...state.nodes, node],
      };
    });
    // Auto-layout after adding
    get().autoLayout();
  },

  updateNode: (id: string, data: Partial<GraphNodeData>) => {
    set((state) => ({
      nodes: state.nodes.map((n) =>
        n.id === id ? { ...n, data: { ...n.data, ...data } } : n
      ),
    }));
  },

  removeNode: (id: string) => {
    set((state) => ({
      nodes: state.nodes.filter((n) => n.id !== id),
      // Also remove connected edges
      edges: state.edges.filter((e) => e.source !== id && e.target !== id),
    }));
  },

  // ---------------------------------------------------------------------------
  // Edge Actions
  // ---------------------------------------------------------------------------

  addEdge: (edge: GraphEdge) => {
    set((state) => {
      // Add timestamp if not provided
      const edgeWithTimestamp = {
        ...edge,
        timestamp: edge.timestamp ?? Date.now(),
      };

      // Replace if same source-target pair exists, otherwise add
      const existingIdx = state.edges.findIndex(
        (e) => e.source === edge.source && e.target === edge.target
      );

      if (existingIdx >= 0) {
        const newEdges = [...state.edges];
        newEdges[existingIdx] = edgeWithTimestamp;
        return { edges: newEdges };
      }

      return {
        edges: [...state.edges, edgeWithTimestamp],
      };
    });
  },

  removeEdge: (id: string) => {
    set((state) => ({
      edges: state.edges.filter((e) => e.id !== id),
    }));
  },

  // ---------------------------------------------------------------------------
  // Bulk Actions
  // ---------------------------------------------------------------------------

  setNodes: (nodes: GraphNode[]) => set({ nodes }),
  setEdges: (edges: GraphEdge[]) => set({ edges }),

  clear: () => set({ nodes: [], edges: [] }),

  // ---------------------------------------------------------------------------
  // Layout Algorithm (Top-Down by Type)
  // ---------------------------------------------------------------------------

  autoLayout: () => {
    set((state) => {
      // Group nodes by type
      const byType: Record<NodeType, GraphNode[]> = {
        agent: [],
        task: [],
        tool: [],
      };

      state.nodes.forEach((node) => {
        byType[node.type]?.push(node);
      });

      // Calculate positions
      const layoutedNodes = state.nodes.map((node) => {
        const typeNodes = byType[node.type];
        const indexInType = typeNodes.findIndex((n) => n.id === node.id);
        const totalInType = typeNodes.length;

        // Center nodes horizontally
        const totalWidth = totalInType * LAYOUT.HORIZONTAL_GAP;
        const startX = LAYOUT.CANVAS_PADDING + (800 - totalWidth) / 2;

        return {
          ...node,
          position: {
            x: startX + indexInType * LAYOUT.HORIZONTAL_GAP,
            y: LAYOUT.ROW_Y[node.type],
          },
        };
      });

      return { nodes: layoutedNodes };
    });
  },

  // ---------------------------------------------------------------------------
  // Helpers
  // ---------------------------------------------------------------------------

  getNodeById: (id: string) => {
    return get().nodes.find((n) => n.id === id);
  },
}));

// =============================================================================
// Event Handlers (for WebSocket integration)
// =============================================================================

/**
 * Process a graph.* event and update the store accordingly.
 * Call this from Dashboard when receiving graph events via WebSocket.
 */
export function processGraphEvent(
  event: { event_type: string; payload: Record<string, unknown> },
  store: GraphStore
): void {
  const { event_type, payload } = event;

  switch (event_type) {
    case 'graph.node_spawn': {
      const p = payload as {
        node_id: string;
        type: NodeType;
        data: { name: string; status: string; role?: string };
        position?: { x: number; y: number };
      };

      store.addNode({
        id: p.node_id,
        type: p.type,
        data: {
          name: p.data.name,
          status: (p.data.status as NodeStatus) || 'idle',
          role: p.data.role,
        },
        position: p.position || { x: 0, y: 0 },
      });
      break;
    }

    case 'graph.node_update': {
      const p = payload as {
        node_id: string;
        data: Partial<GraphNodeData>;
      };

      store.updateNode(p.node_id, p.data);
      break;
    }

    case 'graph.edge_message': {
      const p = payload as {
        from: string;
        to: string;
        message: string;
        timestamp?: string;
      };

      store.addEdge({
        id: `${p.from}-${p.to}-${Date.now()}`,
        source: p.from,
        target: p.to,
        label: p.message.length > 30 ? p.message.slice(0, 30) + '...' : p.message,
        animated: true,
      });
      break;
    }
  }
}
