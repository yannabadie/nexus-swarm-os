/**
 * NEXUS CEREBRO WebSocket Hook
 * V11.6.2 IRONCLAD: JWT authentication + exponential backoff reconnection
 */
import { useEffect, useRef, useCallback, useState } from 'react';
import { useAuth } from '../context/AuthContext';
import { useEventStore } from '../stores/eventStore';
import type { CerebroEvent } from '../types/events';

interface WebSocketOptions {
  workspace?: string;
  eventTypes?: string[];
  onConnect?: () => void;
  onDisconnect?: () => void;
  onError?: (error: Event) => void;
}

type ConnectionStatus = 'connecting' | 'connected' | 'disconnected' | 'error';

const MAX_RETRIES = 10;
const MIN_RETRY_DELAY = 1000;  // 1 second
const MAX_RETRY_DELAY = 30000; // 30 seconds

export function useWebSocket(options: WebSocketOptions = {}) {
  const { token, isAuthenticated } = useAuth();
  const addEvent = useEventStore((s) => s.addEvent);

  const ws = useRef<WebSocket | null>(null);
  const retries = useRef(0);
  const reconnectTimeout = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [status, setStatus] = useState<ConnectionStatus>('disconnected');

  // Store options in ref to avoid infinite re-renders
  const optionsRef = useRef(options);
  optionsRef.current = options;

  const connect = useCallback(() => {
    // Don't connect if not authenticated
    if (!token || !isAuthenticated) {
      setStatus('disconnected');
      return;
    }

    // Clean up existing connection
    if (ws.current) {
      ws.current.close();
    }

    // V11.6.2 IRONCLAD: Correct WebSocket URL format
    // Token is MANDATORY, no tenant_id fallback
    const opts = optionsRef.current;
    const params = new URLSearchParams({
      workspace_id: opts.workspace || 'default',
      token: token,
    });

    if (opts.eventTypes?.length) {
      params.set('event_types', opts.eventTypes.join(','));
    }

    // Build WebSocket URL (Vite proxy handles /ws -> ws://localhost:8080)
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws/stream?${params}`;

    console.log('[WebSocket] Connecting...', { workspace: opts.workspace });
    setStatus('connecting');

    ws.current = new WebSocket(wsUrl);

    ws.current.onopen = () => {
      console.log('[WebSocket] Connected');
      retries.current = 0; // Reset retry counter on successful connection
      setStatus('connected');
      optionsRef.current.onConnect?.();
    };

    ws.current.onmessage = (event) => {
      try {
        const data: CerebroEvent = JSON.parse(event.data);
        addEvent(data);

        // Handle system.connected confirmation
        if (data.event_type === 'system.connected') {
          console.log('[WebSocket] Server confirmed connection:', data.payload);
        }
      } catch (e) {
        console.error('[WebSocket] Failed to parse message:', e);
      }
    };

    ws.current.onclose = (event) => {
      console.log('[WebSocket] Disconnected', { code: event.code, reason: event.reason });
      setStatus('disconnected');
      optionsRef.current.onDisconnect?.();

      // Code 4001 = IRONCLAD auth required - don't reconnect
      if (event.code === 4001) {
        console.error('[WebSocket] Authentication failed (4001) - not reconnecting');
        window.dispatchEvent(new CustomEvent('auth:expired'));
        return;
      }

      // Exponential backoff reconnection
      if (isAuthenticated && retries.current < MAX_RETRIES) {
        const delay = Math.min(
          MIN_RETRY_DELAY * Math.pow(2, retries.current),
          MAX_RETRY_DELAY
        );
        retries.current++;
        console.log(`[WebSocket] Reconnecting in ${delay}ms (attempt ${retries.current}/${MAX_RETRIES})`);

        reconnectTimeout.current = setTimeout(connect, delay);
      } else if (retries.current >= MAX_RETRIES) {
        console.error('[WebSocket] Max reconnection attempts reached');
        setStatus('error');
      }
    };

    ws.current.onerror = (error) => {
      console.error('[WebSocket] Error:', error);
      setStatus('error');
      optionsRef.current.onError?.(error);
    };
  }, [token, isAuthenticated, addEvent]);

  // Connect when authenticated
  useEffect(() => {
    if (isAuthenticated) {
      connect();
    }

    return () => {
      // Cleanup on unmount
      if (reconnectTimeout.current) {
        clearTimeout(reconnectTimeout.current);
      }
      retries.current = MAX_RETRIES; // Prevent reconnection during cleanup
      ws.current?.close(1000, 'Component unmounted');
    };
  }, [isAuthenticated, connect]);

  // Disconnect function (for manual disconnect)
  const disconnect = useCallback(() => {
    if (reconnectTimeout.current) {
      clearTimeout(reconnectTimeout.current);
    }
    retries.current = MAX_RETRIES; // Prevent reconnection
    ws.current?.close(1000, 'Manual disconnect');
    setStatus('disconnected');
  }, []);

  // Send message function
  const send = useCallback((data: unknown) => {
    if (ws.current?.readyState === WebSocket.OPEN) {
      ws.current.send(JSON.stringify(data));
    } else {
      console.warn('[WebSocket] Cannot send - not connected');
    }
  }, []);

  return {
    status,
    disconnect,
    send,
    isConnected: status === 'connected',
  };
}
