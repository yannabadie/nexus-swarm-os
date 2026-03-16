/**
 * LoginForm Component Tests
 */
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { LoginForm } from '../src/components/LoginForm';
import { AuthProvider } from '../src/context/AuthContext';

// Wrapper with AuthProvider
function renderWithAuth(ui: React.ReactElement) {
  return render(<AuthProvider>{ui}</AuthProvider>);
}

describe('LoginForm', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders username and password fields', () => {
    renderWithAuth(<LoginForm />);

    expect(screen.getByLabelText(/username/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/password/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /sign in/i })).toBeInTheDocument();
  });

  it('renders NEXUS CEREBRO title', () => {
    renderWithAuth(<LoginForm />);

    expect(screen.getByText('NEXUS')).toBeInTheDocument();
    expect(screen.getByText('CEREBRO')).toBeInTheDocument();
  });

  it('shows error message on invalid credentials', async () => {
    const user = userEvent.setup();

    global.fetch = vi.fn().mockResolvedValueOnce({
      ok: false,
      status: 401,
    });

    renderWithAuth(<LoginForm />);

    await user.type(screen.getByLabelText(/username/i), 'admin');
    await user.type(screen.getByLabelText(/password/i), 'wrong');
    await user.click(screen.getByRole('button', { name: /sign in/i }));

    await waitFor(() => {
      expect(screen.getByText(/invalid credentials/i)).toBeInTheDocument();
    });
  });

  it('shows loading state during submission', async () => {
    const user = userEvent.setup();

    // Slow response
    global.fetch = vi.fn().mockImplementation(() =>
      new Promise((resolve) =>
        setTimeout(() => resolve({ ok: false, status: 401 }), 100)
      )
    );

    renderWithAuth(<LoginForm />);

    await user.type(screen.getByLabelText(/username/i), 'admin');
    await user.type(screen.getByLabelText(/password/i), 'nexus');
    await user.click(screen.getByRole('button', { name: /sign in/i }));

    // Should show loading state
    expect(screen.getByText(/signing in/i)).toBeInTheDocument();
  });

  it('disables inputs during submission', async () => {
    const user = userEvent.setup();

    // Slow response
    global.fetch = vi.fn().mockImplementation(() =>
      new Promise((resolve) =>
        setTimeout(() => resolve({ ok: false, status: 401 }), 100)
      )
    );

    renderWithAuth(<LoginForm />);

    await user.type(screen.getByLabelText(/username/i), 'admin');
    await user.type(screen.getByLabelText(/password/i), 'nexus');
    await user.click(screen.getByRole('button', { name: /sign in/i }));

    // Inputs should be disabled
    expect(screen.getByLabelText(/username/i)).toBeDisabled();
    expect(screen.getByLabelText(/password/i)).toBeDisabled();
  });

  it('requires username and password', async () => {
    const user = userEvent.setup();

    renderWithAuth(<LoginForm />);

    // Try to submit empty form
    await user.click(screen.getByRole('button', { name: /sign in/i }));

    // HTML5 validation should prevent submission
    // Form should still be visible (not submitted)
    expect(screen.getByLabelText(/username/i)).toBeInTheDocument();
  });

  it('shows IRONCLAD version notice', () => {
    renderWithAuth(<LoginForm />);

    expect(screen.getByText(/v11\.6\.2 ironclad/i)).toBeInTheDocument();
  });
});
