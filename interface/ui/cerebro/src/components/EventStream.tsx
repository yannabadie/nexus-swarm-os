/**
 * NEXUS CEREBRO Event Stream Component
 * V13.0 OPERATION POLISH: Auto-scroll + pause on hover
 * Displays live WebSocket events with color coding
 */
import { useRef, useState, useEffect } from 'react';
import { useEventStore } from '../stores/eventStore';
import { getEventColor } from '../types/events';

export function EventStream() {
  const events = useEventStore((s) => s.events);
  const clearEvents = useEventStore((s) => s.clearEvents);

  // V13.0: Auto-scroll refs and state
  const scrollRef = useRef<HTMLDivElement>(null);
  const [isHovering, setIsHovering] = useState(false);

  // V13.0: Auto-scroll to bottom when new events arrive (unless hovering)
  useEffect(() => {
    if (!isHovering && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [events, isHovering]);

  return (
    <div className="bg-nexus-dark rounded-lg border border-gray-700 h-96 flex flex-col">
      {/* Header */}
      <div className="flex justify-between items-center px-4 py-3 border-b border-gray-700">
        <h2 className="text-lg font-semibold text-white flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-secondary animate-pulse" />
          Event Stream
        </h2>
        <div className="flex items-center gap-3">
          <span className="text-sm text-gray-400">{events.length} events</span>
          {/* V13.0: Auto-scroll indicator */}
          {isHovering && (
            <span className="text-xs text-yellow-500 bg-yellow-500/10 px-2 py-0.5 rounded">
              Paused
            </span>
          )}
          <button
            onClick={clearEvents}
            className="text-sm text-gray-400 hover:text-white transition-colors"
          >
            Clear
          </button>
        </div>
      </div>

      {/* Event List - V13.0: Auto-scroll with pause on hover */}
      <div
        ref={scrollRef}
        onMouseEnter={() => setIsHovering(true)}
        onMouseLeave={() => setIsHovering(false)}
        className="flex-1 overflow-y-auto p-4 font-mono text-sm space-y-1"
      >
        {events.length === 0 ? (
          <div className="flex items-center justify-center h-full text-gray-500 italic">
            Waiting for events...
          </div>
        ) : (
          events.map((event) => (
            <div
              key={event.event_id}
              className="flex items-start gap-3 py-1 hover:bg-white/5 rounded px-2 -mx-2"
            >
              {/* Timestamp */}
              <span className="text-gray-500 text-xs whitespace-nowrap pt-0.5">
                {new Date(event.timestamp).toLocaleTimeString()}
              </span>

              {/* Event Type */}
              <span className={`${getEventColor(event.event_type)} whitespace-nowrap font-medium`}>
                {event.event_type}
              </span>

              {/* Payload Preview */}
              <span className="text-gray-300 truncate flex-1">
                {formatPayload(event.payload)}
              </span>
            </div>
          ))
        )}
      </div>
    </div>
  );
}

/**
 * Format payload for display
 */
function formatPayload(payload: Record<string, unknown>): string {
  // Show meaningful content based on payload
  if (payload.message) {
    return String(payload.message).slice(0, 100);
  }
  if (payload.prompt) {
    return String(payload.prompt).slice(0, 100);
  }
  if (payload.agent) {
    return `[${payload.agent}] ${payload.message || payload.tool || ''}`;
  }
  if (payload.from_state && payload.to_state) {
    return `${payload.from_state} -> ${payload.to_state}`;
  }
  if (payload.phase) {
    return `Phase: ${payload.phase}`;
  }
  if (payload.mode) {
    return `Mode: ${payload.mode}`;
  }

  // Fallback to JSON
  const json = JSON.stringify(payload);
  return json.length > 100 ? json.slice(0, 97) + '...' : json;
}
