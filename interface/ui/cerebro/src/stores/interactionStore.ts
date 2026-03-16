/**
 * NEXUS CEREBRO Interaction Store
 * Zustand store for pending Human-in-the-Loop interactions
 */
import { create } from 'zustand';
import { api } from '../api/client';
import type { PendingInteraction, InteractionResult } from '../types/api';

interface InteractionStore {
  pending: PendingInteraction[];
  loading: boolean;
  error: string | null;

  // Actions
  fetchPending: () => Promise<void>;
  addInteraction: (interaction: PendingInteraction) => void;
  removeInteraction: (requestId: string) => void;
  reply: (requestId: string, response: string | boolean | number) => Promise<boolean>;
  clearError: () => void;
}

export const useInteractionStore = create<InteractionStore>((set, get) => ({
  pending: [],
  loading: false,
  error: null,

  fetchPending: async () => {
    set({ loading: true, error: null });
    try {
      const data = await api.get<{ pending: PendingInteraction[] }>('/api/interactions/pending');
      set({ pending: data.pending, loading: false });
    } catch (error) {
      console.error('[InteractionStore] Failed to fetch pending:', error);
      set({
        error: error instanceof Error ? error.message : 'Failed to fetch interactions',
        loading: false,
      });
    }
  },

  addInteraction: (interaction: PendingInteraction) => {
    set((state) => {
      // Avoid duplicates
      if (state.pending.some((i) => i.request_id === interaction.request_id)) {
        return state;
      }
      return { pending: [...state.pending, interaction] };
    });
  },

  removeInteraction: (requestId: string) => {
    set((state) => ({
      pending: state.pending.filter((i) => i.request_id !== requestId),
    }));
  },

  reply: async (requestId: string, response: string | boolean | number) => {
    set({ error: null });
    try {
      await api.post<InteractionResult>(`/api/interactions/${requestId}/reply`, { response });
      get().removeInteraction(requestId);
      return true;
    } catch (error) {
      console.error('[InteractionStore] Failed to reply:', error);
      set({
        error: error instanceof Error ? error.message : 'Failed to submit response',
      });
      return false;
    }
  },

  clearError: () => {
    set({ error: null });
  },
}));

// Helper to convert WebSocket event to PendingInteraction
export function eventToInteraction(
  event: { event_type: string; payload: Record<string, unknown>; timestamp: string }
): PendingInteraction | null {
  const payload = event.payload;

  // Only handle interaction events
  if (!event.event_type.startsWith('interaction.')) {
    return null;
  }

  // Skip non-interactive types
  if (event.event_type === 'interaction.announce' || event.event_type === 'interaction.progress') {
    return null;
  }

  const requestId = payload.request_id as string;
  if (!requestId) {
    return null;
  }

  const type = event.event_type.split('.')[1] as 'ask' | 'confirm' | 'choose';

  return {
    request_id: requestId,
    interaction_type: type,
    prompt: payload.prompt as string || '',
    choices: payload.options as string[] || payload.choices as string[],
    default: payload.default as string,
    timestamp: event.timestamp,
  };
}
