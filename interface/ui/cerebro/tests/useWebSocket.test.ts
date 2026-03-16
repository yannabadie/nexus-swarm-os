/**
 * useWebSocket Hook Tests
 * V11.6.2 IRONCLAD: WebSocket authentication and reconnection
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, waitFor, act } from '@testing-library/react';
import { useWebSocket } from '../src/hooks/useWebSocket';
import { useAuth } from '../src/context/AuthContext';
import { useEventStore } from '../src/stores/eventStore';

// Mock the auth context
vi.mock('../src/context/AuthContext', () => ({
  useAuth: vi.fn(),
}));

// Mock the event store
vi.mock('../src/stores/eventStore', () => ({
  useEventStore: vi.fn(),
}));

describe('useWebSocket', () => {
  const mockAddEvent = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();

    // Default: authenticated
    vi.mocked(useAuth).mockReturnValue({
      token: 'test-jwt-token',
      isAuthenticated: true,
      user: { user_id: 'admin', tenant_id: 'default', workspace_id: 'default', authenticated: true },
      expiresAt: Date.now() + 86400000,
      login: vi.fn(),
      logout: vi.fn(),
      isExpiringSoon: false,
      getToken: () => 'test-jwt-token',
    });

    vi.mocked(useEventStore).mockReturnValue(mockAddEvent);
  });

  it('connects when authenticated', async () => {
    const { result } = renderHook(() => useWebSocket());

    // WebSocket should be created
    await waitFor(() => {
      expect(result.current.status).toBe('connected');
    });
  });

  it('does not connect when not authenticated', () => {
    vi.mocked(useAuth).mockReturnValue({
      token: null,
      isAuthenticated: false,
      user: null,
      expiresAt: null,
      login: vi.fn(),
      logout: vi.fn(),
      isExpiringSoon: false,
      getToken: () => null,
    });

    const { result } = renderHook(() => useWebSocket());

    expect(result.current.status).toBe('disconnected');
  });

  it('IRONCLAD: includes token in WebSocket URL', async () => {
    let capturedUrl = '';

    // Capture the WebSocket URL
    const OriginalWebSocket = global.WebSocket;
    global.WebSocket = class extends OriginalWebSocket {
      constructor(url: string) {
        capturedUrl = url;
        super(url);
      }
    } as typeof WebSocket;

    renderHook(() => useWebSocket({ workspace: 'test-workspace' }));

    await waitFor(() => {
      expect(capturedUrl).toContain('token=test-jwt-token');
      expect(capturedUrl).toContain('workspace_id=test-workspace');
    });
  });

  it('calls onConnect callback when connected', async () => {
    const onConnect = vi.fn();

    renderHook(() => useWebSocket({ onConnect }));

    await waitFor(() => {
      expect(onConnect).toHaveBeenCalled();
    });
  });

  it('disconnect function closes WebSocket', async () => {
    const { result } = renderHook(() => useWebSocket());

    await waitFor(() => {
      expect(result.current.status).toBe('connected');
    });

    act(() => {
      result.current.disconnect();
    });

    expect(result.current.status).toBe('disconnected');
  });

  it('handles status correctly', async () => {
    const { result } = renderHook(() => useWebSocket());

    // Should start connecting
    expect(['connecting', 'connected']).toContain(result.current.status);

    // Should become connected
    await waitFor(() => {
      expect(result.current.status).toBe('connected');
      expect(result.current.isConnected).toBe(true);
    });
  });
});
