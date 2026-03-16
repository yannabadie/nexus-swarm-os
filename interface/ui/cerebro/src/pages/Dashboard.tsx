/**
 * NEXUS CEREBRO Dashboard Page
 * V12.1 RETINA: Mission Cockpit with HiveMap, FileCommander, MissionControl
 *
 * V12.1 Improvements (Conseiller 2 feedback):
 * - Mobile responsive layout with Events as tab
 *
 * Desktop Layout (md+):
 * +-----------------------------------------------------------+
 * | Header                                                     |
 * +-----------------------------------+-----------------------+
 * | Tabs: [Hive Map] [Files]          | MissionControl        |
 * +-----------------------------------+                       |
 * | Tab Content                       +-----------------------+
 * |                                   | EventStream           |
 * +-----------------------------------+-----------------------+
 *
 * Mobile Layout:
 * +-----------------------------------------------------------+
 * | Header                                                     |
 * +-----------------------------------------------------------+
 * | MissionControl (collapsible)                               |
 * +-----------------------------------------------------------+
 * | Tabs: [Hive] [Files] [Events]                              |
 * +-----------------------------------------------------------+
 * | Tab Content                                                |
 * +-----------------------------------------------------------+
 */
import { useEffect, useState, useMemo } from 'react';
import { Map, FolderTree, Activity, ChevronDown, ChevronUp, Brain } from 'lucide-react';
import { useWebSocket } from '../hooks/useWebSocket';
import { useAuth } from '../context/AuthContext';
import { useEventStore } from '../stores/eventStore';
import { useGraphStore, processGraphEvent } from '../stores/graphStore';
import { useInteractionStore, eventToInteraction } from '../stores/interactionStore';
import { api } from '../api/client';
import { Header } from '../components/Header';
import { EventStream } from '../components/EventStream';
import { InteractionModal } from '../components/InteractionModal';
import { HiveMap } from '../components/views/HiveMap';
import { FileCommander } from '../components/views/FileCommander';
import { MissionControl } from '../components/controls/MissionControl';
import { MemoryPanel } from '../components/MemoryPanel';
import type { StateSnapshot, PendingInteraction } from '../types/api';

// =============================================================================
// Types
// =============================================================================

// V12.1: Added 'events' tab for mobile layout
// V13.0: Added 'memory' tab for MEMORIA UNIVERSALIS
type TabId = 'hive' | 'files' | 'memory' | 'events';

interface Tab {
  id: TabId;
  label: string;
  shortLabel: string;  // V12.1: For mobile
  icon: React.ReactNode;
  mobileOnly?: boolean;  // V12.1: Show only on mobile
}

// =============================================================================
// Constants
// =============================================================================

const TABS: Tab[] = [
  { id: 'hive', label: 'Hive Map', shortLabel: 'Hive', icon: <Map size={16} /> },
  { id: 'files', label: 'Files', shortLabel: 'Files', icon: <FolderTree size={16} /> },
  { id: 'memory', label: 'Memory', shortLabel: 'Memory', icon: <Brain size={16} /> },
  { id: 'events', label: 'Events', shortLabel: 'Events', icon: <Activity size={16} />, mobileOnly: true },
];

// =============================================================================
// Component
// =============================================================================

export function Dashboard() {
  const { user } = useAuth();

  // Tab state
  const [activeTab, setActiveTab] = useState<TabId>('hive');

  // WebSocket
  const { status: wsStatus } = useWebSocket({
    onConnect: () => console.log('[Dashboard] WebSocket connected'),
    onDisconnect: () => console.log('[Dashboard] WebSocket disconnected'),
  });

  // Stores
  const events = useEventStore((s) => s.events);
  const addInteraction = useInteractionStore((s) => s.addInteraction);
  const pending = useInteractionStore((s) => s.pending);
  const fetchPending = useInteractionStore((s) => s.fetchPending);

  // Graph store
  const graphStore = useGraphStore();

  // Local state
  const [activeInteraction, setActiveInteraction] = useState<PendingInteraction | null>(null);
  const [snapshot, setSnapshot] = useState<StateSnapshot | null>(null);
  const [snapshotLoading, setSnapshotLoading] = useState(true);
  const [snapshotError, setSnapshotError] = useState<string | null>(null);

  // V12.1: Mobile MissionControl collapse state
  const [missionControlCollapsed, setMissionControlCollapsed] = useState(true);

  // ---------------------------------------------------------------------------
  // Load State Snapshot (F5 Recovery)
  // ---------------------------------------------------------------------------

  useEffect(() => {
    const loadSnapshot = async () => {
      setSnapshotLoading(true);
      setSnapshotError(null);

      try {
        const data = await api.get<StateSnapshot>('/api/state/snapshot');
        setSnapshot(data);

        // Load pending interactions from snapshot
        data.pending_interactions.forEach((i) => addInteraction(i));

        // Load graph nodes from snapshot if present
        if (data.nodes && typeof data.nodes === 'object') {
          const nodeArray = Object.values(data.nodes);
          if (nodeArray.length > 0) {
            graphStore.setNodes(nodeArray as any);
          }
        }
      } catch (error) {
        console.error('[Dashboard] Failed to load snapshot:', error);
        setSnapshotError(error instanceof Error ? error.message : 'Failed to load state');
      } finally {
        setSnapshotLoading(false);
      }
    };

    loadSnapshot();
    fetchPending();
  }, [fetchPending, addInteraction, graphStore]);

  // ---------------------------------------------------------------------------
  // Process WebSocket Events
  // ---------------------------------------------------------------------------

  // Track processed event IDs to avoid duplicates
  const processedEvents = useMemo(() => new Set<string>(), []);

  useEffect(() => {
    // Process new events
    events.forEach((event) => {
      // Skip if already processed
      if (processedEvents.has(event.event_id)) return;
      processedEvents.add(event.event_id);

      // Handle interaction events
      if (
        event.event_type.startsWith('interaction.') &&
        event.event_type !== 'interaction.progress' &&
        event.event_type !== 'interaction.announce'
      ) {
        const interaction = eventToInteraction(event);
        if (interaction && !pending.find((p) => p.request_id === interaction.request_id)) {
          addInteraction(interaction);
        }
      }

      // Handle graph events
      if (event.event_type.startsWith('graph.')) {
        processGraphEvent(event, graphStore);
      }
    });
  }, [events, pending, addInteraction, graphStore, processedEvents]);

  // ---------------------------------------------------------------------------
  // Auto-show First Pending Interaction
  // ---------------------------------------------------------------------------

  useEffect(() => {
    if (pending.length > 0 && !activeInteraction) {
      setActiveInteraction(pending[0]);
    }
  }, [pending, activeInteraction]);

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div className="min-h-screen bg-nexus-darker flex flex-col">
      <Header wsStatus={wsStatus} />

      <main className="flex-1 p-4 overflow-hidden">
        {/* Snapshot Loading/Error */}
        {snapshotLoading && (
          <div className="bg-nexus-dark rounded-lg border border-gray-700 p-4 mb-4">
            <div className="flex items-center gap-2 text-gray-400">
              <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24">
                <circle
                  className="opacity-25"
                  cx="12"
                  cy="12"
                  r="10"
                  stroke="currentColor"
                  strokeWidth="4"
                  fill="none"
                />
                <path
                  className="opacity-75"
                  fill="currentColor"
                  d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
                />
              </svg>
              Loading state...
            </div>
          </div>
        )}

        {snapshotError && (
          <div className="bg-danger/20 border border-danger/50 rounded-lg p-4 mb-4">
            <p className="text-danger">{snapshotError}</p>
            <p className="text-sm text-gray-400 mt-1">
              The system will still receive live events via WebSocket.
            </p>
          </div>
        )}

        {/* V12.1: Mobile MissionControl (collapsible) */}
        <div className="md:hidden mb-4">
          <button
            onClick={() => setMissionControlCollapsed(!missionControlCollapsed)}
            className="w-full flex items-center justify-between px-4 py-2 bg-gray-800 rounded-lg border border-gray-700"
          >
            <span className="text-sm font-medium text-gray-300">Mission Control</span>
            {missionControlCollapsed ? (
              <ChevronDown size={16} className="text-gray-400" />
            ) : (
              <ChevronUp size={16} className="text-gray-400" />
            )}
          </button>
          {!missionControlCollapsed && (
            <div className="mt-2">
              <MissionControl />
            </div>
          )}
        </div>

        {/* Main Grid Layout - V12.1: Responsive (single column mobile, two columns desktop) */}
        <div className="grid grid-cols-1 md:grid-cols-[1fr_340px] gap-4 h-[calc(100vh-120px)] md:h-[calc(100vh-120px)]">
          {/* Left: Tabs + Content */}
          <div className="flex flex-col min-h-0">
            {/* Tab Bar */}
            <div className="flex items-center gap-1 mb-2 overflow-x-auto">
              {TABS.map((tab) => (
                <button
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id)}
                  className={`
                    flex items-center gap-1.5 md:gap-2 px-2 md:px-4 py-2 rounded-t-lg text-xs md:text-sm font-medium
                    transition-colors border-b-2 whitespace-nowrap
                    ${tab.mobileOnly ? 'md:hidden' : ''}
                    ${
                      activeTab === tab.id
                        ? 'bg-gray-800 text-white border-cyan-500'
                        : 'bg-gray-800/50 text-gray-400 border-transparent hover:text-gray-300 hover:bg-gray-800/70'
                    }
                  `}
                >
                  {tab.icon}
                  <span className="hidden md:inline">{tab.label}</span>
                  <span className="md:hidden">{tab.shortLabel}</span>
                </button>
              ))}

              {/* Status indicators - hidden on mobile */}
              <div className="ml-auto hidden md:flex items-center gap-3 text-xs text-gray-500">
                {user && (
                  <span>
                    Tenant: <span className="text-gray-300">{user.tenant_id}</span>
                  </span>
                )}
                {snapshot?.phase && (
                  <span>
                    Phase: <span className="text-cyan-400">{String(snapshot.phase.current_phase || 'IDLE')}</span>
                  </span>
                )}
                {pending.length > 0 && (
                  <span className="px-2 py-0.5 rounded bg-yellow-600/20 text-yellow-400">
                    {pending.length} pending
                  </span>
                )}
              </div>
            </div>

            {/* Tab Content */}
            <div className="flex-1 min-h-0">
              {activeTab === 'hive' && <HiveMap />}
              {activeTab === 'files' && <FileCommander />}
              {/* V13.0: Memory tab for MEMORIA UNIVERSALIS */}
              {activeTab === 'memory' && (
                <div className="h-full overflow-auto">
                  <MemoryPanel />
                </div>
              )}
              {/* V12.1: Events tab for mobile - EventStream has own header */}
              {activeTab === 'events' && (
                <div className="h-full overflow-hidden">
                  <EventStream />
                </div>
              )}
            </div>
          </div>

          {/* Right: Sidebar - Desktop only */}
          <div className="hidden md:flex flex-col gap-4 min-h-0">
            {/* Mission Control */}
            <MissionControl />

            {/* Event Stream - uses its own header */}
            <div className="flex-1 min-h-0 overflow-hidden">
              <EventStream />
            </div>
          </div>
        </div>
      </main>

      {/* Interaction Modal (Global Overlay) */}
      {activeInteraction && (
        <InteractionModal
          interaction={activeInteraction}
          onClose={() => setActiveInteraction(null)}
        />
      )}
    </div>
  );
}
