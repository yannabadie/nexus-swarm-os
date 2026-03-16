/**
 * NEXUS CEREBRO HiveMap
 * V12.1 RETINA: Sovereign SVG Graph Visualization
 *
 * Custom SVG implementation (no @xyflow/react) for React 19 compatibility.
 * Renders nodes and edges with glassmorphism styling.
 *
 * V12.1 Improvements (Conseiller 2 feedback):
 * - Role-based colors (Lead/Support/Specialist)
 * - Tooltips with last message
 * - Performance warning at 50+ nodes
 * - Mobile responsive design
 */
import { useEffect, useState } from 'react';
import { AlertTriangle } from 'lucide-react';
import { useGraphStore, type GraphNode, type GraphEdge, type NodeType } from '../../stores/graphStore';

// =============================================================================
// Constants
// =============================================================================

// V12.1: Colors by node TYPE (default)
const NODE_COLORS: Record<NodeType, { bg: string; border: string; text: string }> = {
  agent: { bg: '#1e3a5f', border: '#3b82f6', text: '#93c5fd' },   // Blue
  task: { bg: '#3b1f5f', border: '#8b5cf6', text: '#c4b5fd' },    // Purple
  tool: { bg: '#1f3d3f', border: '#10b981', text: '#6ee7b7' },    // Green
};

// V12.1 RETINA: Colors by ROLE (Conseiller 2 feedback)
const ROLE_COLORS: Record<string, { bg: string; border: string; text: string }> = {
  lead: { bg: '#312e81', border: '#6366f1', text: '#a5b4fc' },        // Indigo
  support: { bg: '#1e293b', border: '#94a3b8', text: '#cbd5e1' },     // Gray
  specialist: { bg: '#431407', border: '#f97316', text: '#fdba74' },  // Orange
  coordinator: { bg: '#164e63', border: '#06b6d4', text: '#67e8f9' }, // Cyan
  reviewer: { bg: '#3f1f45', border: '#c026d3', text: '#e879f9' },    // Fuchsia
};

const NODE_WIDTH = 140;
const NODE_HEIGHT = 70;
const NODE_RADIUS = 8;

// =============================================================================
// Sub-Components
// =============================================================================

// =============================================================================
// Helper Functions
// =============================================================================

/**
 * V12.1: Get colors based on role (if present) or fallback to type colors
 */
function getNodeColors(node: GraphNode): { bg: string; border: string; text: string } {
  // If node has a role, use role-based colors
  if (node.data.role) {
    const roleLower = node.data.role.toLowerCase();
    if (ROLE_COLORS[roleLower]) {
      return ROLE_COLORS[roleLower];
    }
  }
  // Fallback to type-based colors
  return NODE_COLORS[node.type];
}

// =============================================================================
// Sub-Components
// =============================================================================

interface NodeProps {
  node: GraphNode;
  onHover: (node: GraphNode | null) => void;
}

function GraphNodeComponent({ node, onHover }: NodeProps) {
  const colors = getNodeColors(node);
  const isWorking = node.data.status === 'working';
  const isError = node.data.status === 'error';

  return (
    <g
      transform={`translate(${node.position.x}, ${node.position.y})`}
      onMouseEnter={() => onHover(node)}
      onMouseLeave={() => onHover(null)}
      style={{ cursor: 'pointer' }}
    >
      {/* Glow effect for working nodes */}
      {isWorking && (
        <rect
          x="-4"
          y="-4"
          width={NODE_WIDTH + 8}
          height={NODE_HEIGHT + 8}
          rx={NODE_RADIUS + 2}
          fill="none"
          stroke={colors.border}
          strokeWidth="2"
          opacity="0.5"
          className="animate-pulse"
        />
      )}

      {/* Main node body (glassmorphism) */}
      <rect
        width={NODE_WIDTH}
        height={NODE_HEIGHT}
        rx={NODE_RADIUS}
        fill={colors.bg}
        stroke={isError ? '#ef4444' : colors.border}
        strokeWidth={isError ? 3 : 2}
        fillOpacity="0.9"
      />

      {/* Type badge */}
      <rect
        x="4"
        y="4"
        width="50"
        height="16"
        rx="4"
        fill={colors.border}
        fillOpacity="0.3"
      />
      <text
        x="29"
        y="14"
        fontSize="9"
        fontWeight="600"
        fill={colors.text}
        textAnchor="middle"
        dominantBaseline="middle"
      >
        {node.type.toUpperCase()}
      </text>

      {/* Node name */}
      <text
        x={NODE_WIDTH / 2}
        y="35"
        fontSize="13"
        fontWeight="bold"
        fill="white"
        textAnchor="middle"
        dominantBaseline="middle"
      >
        {node.data.name.length > 12
          ? node.data.name.slice(0, 12) + '...'
          : node.data.name}
      </text>

      {/* Role / Status */}
      <text
        x={NODE_WIDTH / 2}
        y="52"
        fontSize="10"
        fill="#9ca3af"
        textAnchor="middle"
        dominantBaseline="middle"
      >
        {node.data.role || node.data.status}
      </text>

      {/* Status indicator */}
      <circle
        cx={NODE_WIDTH - 12}
        cy="12"
        r="5"
        fill={
          node.data.status === 'working'
            ? '#22c55e'
            : node.data.status === 'error'
            ? '#ef4444'
            : node.data.status === 'done'
            ? '#3b82f6'
            : '#6b7280'
        }
        className={isWorking ? 'animate-ping' : ''}
      />
      {isWorking && (
        <circle
          cx={NODE_WIDTH - 12}
          cy="12"
          r="5"
          fill="#22c55e"
        />
      )}
    </g>
  );
}

interface EdgeProps {
  edge: GraphEdge;
  sourceNode: GraphNode | undefined;
  targetNode: GraphNode | undefined;
}

function GraphEdgeComponent({ edge, sourceNode, targetNode }: EdgeProps) {
  if (!sourceNode || !targetNode) return null;

  // Calculate connection points (center-bottom to center-top)
  const x1 = sourceNode.position.x + NODE_WIDTH / 2;
  const y1 = sourceNode.position.y + NODE_HEIGHT;
  const x2 = targetNode.position.x + NODE_WIDTH / 2;
  const y2 = targetNode.position.y;

  // Calculate midpoint for label
  const midX = (x1 + x2) / 2;
  const midY = (y1 + y2) / 2;

  // Calculate control points for curved line
  const controlY = (y1 + y2) / 2;

  return (
    <g className={edge.animated ? 'animate-pulse' : ''}>
      {/* Edge line */}
      <path
        d={`M ${x1} ${y1} Q ${x1} ${controlY}, ${midX} ${midY} Q ${x2} ${controlY}, ${x2} ${y2}`}
        fill="none"
        stroke="#4b5563"
        strokeWidth="2"
        markerEnd="url(#arrowhead)"
      />

      {/* Edge label */}
      {edge.label && (
        <>
          <rect
            x={midX - 40}
            y={midY - 8}
            width="80"
            height="16"
            rx="4"
            fill="#1f2937"
            fillOpacity="0.9"
          />
          <text
            x={midX}
            y={midY}
            fontSize="9"
            fill="#9ca3af"
            textAnchor="middle"
            dominantBaseline="middle"
          >
            {edge.label}
          </text>
        </>
      )}
    </g>
  );
}

// =============================================================================
// Main Component
// =============================================================================

export function HiveMap() {
  const { nodes, edges, autoLayout, shouldUseSimpleRenderer } = useGraphStore();

  // V12.1: Tooltip state
  const [hoveredNode, setHoveredNode] = useState<GraphNode | null>(null);

  // Auto-layout when nodes change
  useEffect(() => {
    if (nodes.length > 0) {
      autoLayout();
    }
  }, [nodes.length, autoLayout]);

  return (
    <div className="w-full h-full min-h-[300px] md:min-h-[400px] bg-gradient-to-br from-gray-900 via-gray-900 to-gray-800 rounded-lg border border-gray-700 overflow-hidden relative">
      {/* Title bar */}
      <div className="absolute top-0 left-0 right-0 px-4 py-2 bg-gray-800/50 backdrop-blur border-b border-gray-700 flex items-center gap-2 z-10">
        <div className="w-2 h-2 rounded-full bg-cyan-400 animate-pulse" />
        <span className="text-xs font-semibold text-gray-300 uppercase tracking-wider">
          Hive Map
        </span>

        {/* V12.1: Performance warning (Conseiller 2) */}
        {shouldUseSimpleRenderer && (
          <span className="flex items-center gap-1 px-2 py-0.5 rounded bg-yellow-600/20 text-yellow-400 text-xs">
            <AlertTriangle size={10} />
            {nodes.length} nodes (simplified)
          </span>
        )}

        <span className="text-xs text-gray-500 ml-auto">
          {nodes.length} node{nodes.length !== 1 ? 's' : ''} |{' '}
          {edges.length} edge{edges.length !== 1 ? 's' : ''}
        </span>
      </div>

      {/* SVG Canvas */}
      <svg
        className="w-full h-full pt-10"
        viewBox="0 0 800 500"
        preserveAspectRatio="xMidYMid meet"
      >
        {/* Definitions */}
        <defs>
          {/* Arrowhead marker */}
          <marker
            id="arrowhead"
            markerWidth="10"
            markerHeight="7"
            refX="9"
            refY="3.5"
            orient="auto"
          >
            <polygon points="0 0, 10 3.5, 0 7" fill="#4b5563" />
          </marker>

          {/* Grid pattern */}
          <pattern
            id="grid"
            width="40"
            height="40"
            patternUnits="userSpaceOnUse"
          >
            <path
              d="M 40 0 L 0 0 0 40"
              fill="none"
              stroke="#1f2937"
              strokeWidth="0.5"
            />
          </pattern>
        </defs>

        {/* Background grid */}
        <rect width="100%" height="100%" fill="url(#grid)" />

        {/* Row labels */}
        <text x="15" y="85" fontSize="10" fill="#4b5563" fontWeight="500">
          AGENTS
        </text>
        <text x="15" y="235" fontSize="10" fill="#4b5563" fontWeight="500">
          TASKS
        </text>
        <text x="15" y="385" fontSize="10" fill="#4b5563" fontWeight="500">
          TOOLS
        </text>

        {/* Edges (render first, behind nodes) */}
        <g className="edges">
          {edges.map((edge) => (
            <GraphEdgeComponent
              key={edge.id}
              edge={edge}
              sourceNode={nodes.find((n) => n.id === edge.source)}
              targetNode={nodes.find((n) => n.id === edge.target)}
            />
          ))}
        </g>

        {/* Nodes */}
        <g className="nodes">
          {nodes.map((node) => (
            <GraphNodeComponent key={node.id} node={node} onHover={setHoveredNode} />
          ))}
        </g>

        {/* Empty state */}
        {nodes.length === 0 && (
          <g>
            <text
              x="400"
              y="230"
              fontSize="16"
              fill="#4b5563"
              textAnchor="middle"
              fontWeight="500"
            >
              Awaiting Mission...
            </text>
            <text
              x="400"
              y="255"
              fontSize="12"
              fill="#374151"
              textAnchor="middle"
            >
              Launch a workflow to see the Hive in action
            </text>
          </g>
        )}
      </svg>

      {/* Legend */}
      <div className="absolute bottom-2 right-2 flex flex-wrap gap-3 text-xs text-gray-500">
        <div className="flex items-center gap-1">
          <div className="w-3 h-3 rounded bg-blue-500/50 border border-blue-500" />
          <span>Agent</span>
        </div>
        <div className="flex items-center gap-1">
          <div className="w-3 h-3 rounded bg-purple-500/50 border border-purple-500" />
          <span>Task</span>
        </div>
        <div className="flex items-center gap-1">
          <div className="w-3 h-3 rounded bg-green-500/50 border border-green-500" />
          <span>Tool</span>
        </div>
        {/* V12.1: Role colors legend */}
        <div className="hidden md:flex items-center gap-1 border-l border-gray-700 pl-3">
          <div className="w-3 h-3 rounded" style={{ backgroundColor: '#6366f1' }} />
          <span>Lead</span>
        </div>
        <div className="hidden md:flex items-center gap-1">
          <div className="w-3 h-3 rounded" style={{ backgroundColor: '#f97316' }} />
          <span>Specialist</span>
        </div>
      </div>

      {/* V12.1: Tooltip (Conseiller 2 feedback) */}
      {hoveredNode && (
        <div
          className="absolute z-20 px-3 py-2 rounded-lg bg-gray-800/95 border border-gray-600 shadow-xl max-w-xs"
          style={{
            left: Math.min(hoveredNode.position.x + NODE_WIDTH + 10, 600),
            top: hoveredNode.position.y + 40,
          }}
        >
          <div className="flex items-center gap-2 mb-1">
            <span className="font-semibold text-white text-sm">{hoveredNode.data.name}</span>
            <span
              className="px-1.5 py-0.5 rounded text-xs"
              style={{
                backgroundColor: getNodeColors(hoveredNode).bg,
                color: getNodeColors(hoveredNode).text,
              }}
            >
              {hoveredNode.data.role || hoveredNode.type}
            </span>
          </div>
          <div className="text-xs text-gray-400 mb-1">
            Status: <span className={
              hoveredNode.data.status === 'working' ? 'text-green-400' :
              hoveredNode.data.status === 'error' ? 'text-red-400' :
              hoveredNode.data.status === 'done' ? 'text-blue-400' : 'text-gray-300'
            }>{hoveredNode.data.status}</span>
          </div>
          {hoveredNode.data.lastMessage && (
            <div className="text-xs text-gray-500 italic border-t border-gray-700 pt-1 mt-1">
              "{hoveredNode.data.lastMessage.length > 80
                ? hoveredNode.data.lastMessage.slice(0, 80) + '...'
                : hoveredNode.data.lastMessage}"
            </div>
          )}
        </div>
      )}
    </div>
  );
}
