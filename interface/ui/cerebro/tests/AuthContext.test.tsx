/**
 * AuthContext Tests
 * V11.6.2 IRONCLAD: Verify token stored in memory only
 */
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AuthProvider, useAuth } from '../src/context/AuthContext';

// Test component to access auth context
function TestComponent() {
  const { isAuthenticated, login, logout, user, getToken } = useAuth();
  return (
    <div>
      <span data-testid="auth-status">{isAuthenticated ? 'authenticated' : 'anonymous'}</span>
      <span data-testid="user-id">{user?.user_id || 'none'}</span>
      <span data-testid="token">{getToken() || 'no-token'}</span>
      <button onClick={() => login('admin', 'nexus')}>Login</button>
      <button onClick={() => logout()}>Logout</button>
    </div>
  );
}

describe('AuthContext', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Clear any storage (should be empty anyway)
    localStorage.clear();
    sessionStorage.clear();
  });

  it('starts unauthenticated', () => {
    render(
      <AuthProvider>
        <TestComponent />
      </AuthProvider>
    );

    expect(screen.getByTestId('auth-status')).toHaveTextContent('anonymous');
    expect(screen.getByTestId('user-id')).toHaveTextContent('none');
  });

  it('authenticates successfully with valid credentials', async () => {
    const user = userEvent.setup();

    global.fetch = vi.fn().mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({
        access_token: 'test-jwt-token',
        token_type: 'bearer',
        expires_in: 86400,
        user_id: 'admin',
        tenant_id: 'default',
      }),
    });

    render(
      <AuthProvider>
        <TestComponent />
      </AuthProvider>
    );

    await user.click(screen.getByText('Login'));

    await waitFor(() => {
      expect(screen.getByTestId('auth-status')).toHaveTextContent('authenticated');
      expect(screen.getByTestId('user-id')).toHaveTextContent('admin');
    });
  });

  it('handles invalid credentials', async () => {
    const user = userEvent.setup();

    global.fetch = vi.fn().mockResolvedValueOnce({
      ok: false,
      status: 401,
    });

    render(
      <AuthProvider>
        <TestComponent />
      </AuthProvider>
    );

    await user.click(screen.getByText('Login'));

    await waitFor(() => {
      expect(screen.getByTestId('auth-status')).toHaveTextContent('anonymous');
    });
  });

  it('IRONCLAD: token stored in memory only, NOT in storage', async () => {
    const user = userEvent.setup();

    global.fetch = vi.fn().mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({
        access_token: 'secret-jwt-token',
        token_type: 'bearer',
        expires_in: 86400,
        user_id: 'admin',
        tenant_id: 'default',
      }),
    });

    render(
      <AuthProvider>
        <TestComponent />
      </AuthProvider>
    );

    await user.click(screen.getByText('Login'));

    await waitFor(() => {
      expect(screen.getByTestId('auth-status')).toHaveTextContent('authenticated');
    });

    // IRONCLAD: Verify token is NOT in localStorage or sessionStorage
    expect(localStorage.getItem('token')).toBeNull();
    expect(localStorage.getItem('access_token')).toBeNull();
    expect(sessionStorage.getItem('token')).toBeNull();
    expect(sessionStorage.getItem('access_token')).toBeNull();

    // But token should be accessible via getToken()
    expect(screen.getByTestId('token')).toHaveTextContent('secret-jwt-token');
  });

  it('logout clears authentication state', async () => {
    const user = userEvent.setup();

    // Login first
    global.fetch = vi.fn()
      .mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({
          access_token: 'test-token',
          token_type: 'bearer',
          expires_in: 86400,
          user_id: 'admin',
          tenant_id: 'default',
        }),
      })
      // Logout request
      .mockResolvedValueOnce({ ok: true });

    render(
      <AuthProvider>
        <TestComponent />
      </AuthProvider>
    );

    // Login
    await user.click(screen.getByText('Login'));
    await waitFor(() => {
      expect(screen.getByTestId('auth-status')).toHaveTextContent('authenticated');
    });

    // Logout
    await user.click(screen.getByText('Logout'));
    await waitFor(() => {
      expect(screen.getByTestId('auth-status')).toHaveTextContent('anonymous');
      expect(screen.getByTestId('token')).toHaveTextContent('no-token');
    });
  });

  it('handles login network error gracefully', async () => {
    const user = userEvent.setup();

    global.fetch = vi.fn().mockRejectedValueOnce(new Error('Network error'));

    render(
      <AuthProvider>
        <TestComponent />
      </AuthProvider>
    );

    await user.click(screen.getByText('Login'));

    await waitFor(() => {
      // Should remain unauthenticated
      expect(screen.getByTestId('auth-status')).toHaveTextContent('anonymous');
    });
  });
});
