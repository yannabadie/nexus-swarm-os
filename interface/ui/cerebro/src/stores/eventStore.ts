/**
 * NEXUS CEREBRO Event Store
 * Zustand store for WebSocket events with memory limit
 */
import { create } from 'zustand';
import type { CerebroEvent } from '../types/events';

interface EventStore {
  events: CerebroEvent[];
  maxEvents: number;
  addEvent: (event: CerebroEvent) => void;
  clearEvents: () => void;
  getEventsByType: (typePrefix: string) => CerebroEvent[];
  getLatestEvent: (typePrefix: string) => CerebroEvent | undefined;
}

export const useEventStore = create<EventStore>((set, get) => ({
  events: [],
  maxEvents: 500, // Memory limit

  addEvent: (event: CerebroEvent) => {
    set((state) => ({
      // Prepend new event and trim to max
      events: [event, ...state.events].slice(0, state.maxEvents),
    }));
  },

  clearEvents: () => {
    set({ events: [] });
  },

  getEventsByType: (typePrefix: string) => {
    return get().events.filter((e) => e.event_type.startsWith(typePrefix));
  },

  getLatestEvent: (typePrefix: string) => {
    return get().events.find((e) => e.event_type.startsWith(typePrefix));
  },
}));
