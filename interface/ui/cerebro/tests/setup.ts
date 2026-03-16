/**
 * Vitest + React Testing Library Setup
 * NEXUS CEREBRO UI Tests
 */
import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterEach, vi } from 'vitest';

// Cleanup after each test
afterEach(() => {
  cleanup();
});

// Mock WebSocket for testing
class MockWebSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;

  readyState = MockWebSocket.OPEN;
  url: string;
  onopen: ((ev: Event) => void) | null = null;
  onclose: ((ev: CloseEvent) => void) | null = null;
  onmessage: ((ev: MessageEvent) => void) | null = null;
  onerror: ((ev: Event) => void) | null = null;

  constructor(url: string) {
    this.url = url;
    // Simulate async connection
    setTimeout(() => {
      if (this.onopen) {
        this.onopen(new Event('open'));
      }
    }, 0);
  }

  send = vi.fn();

  close = vi.fn((code?: number, reason?: string) => {
    this.readyState = MockWebSocket.CLOSED;
    if (this.onclose) {
      const event = new CloseEvent('close', { code: code || 1000, reason: reason || '' });
      this.onclose(event);
    }
  });

  // Helper to simulate receiving a message (for tests)
  simulateMessage(data: unknown) {
    if (this.onmessage) {
      this.onmessage(new MessageEvent('message', { data: JSON.stringify(data) }));
    }
  }

  // Helper to simulate error (for tests)
  simulateError() {
    if (this.onerror) {
      this.onerror(new Event('error'));
    }
  }
}

vi.stubGlobal('WebSocket', MockWebSocket);

// Mock fetch for API tests
global.fetch = vi.fn();

// Reset mocks between tests
afterEach(() => {
  vi.clearAllMocks();
});
