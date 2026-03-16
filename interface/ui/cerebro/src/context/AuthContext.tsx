/**
 * NEXUS CEREBRO Authentication Context
 * V11.6.2 IRONCLAD: JWT stored IN-MEMORY ONLY (not localStorage/sessionStorage)
 */
import {
  createContext,
  useContext,
  useState,
  useCallback,
  useEffect,
  type ReactNode,
} from 'react';
import type { LoginResponse, UserInfo } from '../types/api';

interface AuthState {
  token: string | null;
  user: UserInfo | null;
  expiresAt: number | null;
}

interface AuthContextType extends AuthState {
  login: (username: string, password: string) => Promise<boolean>;
  logout: () => Promise<void>;
  isAuthenticated: boolean;
  isExpiringSoon: boolean;
  getToken: () => string | null;
}

const AuthContext = createContext<AuthContextType | null>(null);

// Token expiry warning threshold (5 minutes)
const EXPIRY_WARNING_MS = 5 * 60 * 1000;

export function AuthProvider({ children }: { children: ReactNode }) {
  // IRONCLAD: Token stored in React state ONLY - never in localStorage/sessionStorage
  const [state, setState] = useState<AuthState>({
    token: null,
    user: null,
    expiresAt: null,
  });

  const login = useCallback(async (username: string, password: string): Promise<boolean> => {
    try {
      const res = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
      });

      if (!res.ok) {
        console.error('[IRONCLAD] Login failed:', res.status);
        return false;
      }

      const data: LoginResponse = await res.json();

      // IRONCLAD: Store IN-MEMORY ONLY
      setState({
        token: data.access_token,
        user: {
          user_id: data.user_id,
          tenant_id: data.tenant_id,
          workspace_id: 'default',
          authenticated: true,
        },
        expiresAt: Date.now() + (data.expires_in * 1000),
      });

      console.log('[IRONCLAD] Login successful, token stored in memory');
      return true;
    } catch (error) {
      console.error('[IRONCLAD] Login error:', error);
      return false;
    }
  }, []);

  const logout = useCallback(async () => {
    try {
      if (state.token) {
        await fetch('/api/auth/logout', {
          method: 'POST',
          headers: { Authorization: `Bearer ${state.token}` },
        });
      }
    } catch (error) {
      console.warn('[IRONCLAD] Logout request failed:', error);
    } finally {
      // Always clear state, even if server request fails
      setState({ token: null, user: null, expiresAt: null });
      console.log('[IRONCLAD] Session cleared from memory');
    }
  }, [state.token]);

  // Token expiry check - 5 minutes before expiry
  const isExpiringSoon = state.expiresAt
    ? (state.expiresAt - Date.now()) < EXPIRY_WARNING_MS
    : false;

  // Effect: Periodic expiry check and auto-logout
  useEffect(() => {
    if (!state.expiresAt) return;

    const checkExpiry = setInterval(() => {
      const now = Date.now();
      if (now >= state.expiresAt!) {
        console.warn('[IRONCLAD] Token expired, clearing session');
        setState({ token: null, user: null, expiresAt: null });
        window.dispatchEvent(new CustomEvent('auth:expired'));
      } else if (state.expiresAt! - now < EXPIRY_WARNING_MS) {
        console.warn('[IRONCLAD] Token expiring soon');
      }
    }, 60000); // Check every minute

    return () => clearInterval(checkExpiry);
  }, [state.expiresAt]);

  // Getter for token (used by API client)
  const getToken = useCallback(() => state.token, [state.token]);

  const value: AuthContextType = {
    ...state,
    login,
    logout,
    isAuthenticated: !!state.token,
    isExpiringSoon,
    getToken,
  };

  return (
    <AuthContext.Provider value={value}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextType {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error('useAuth must be used within AuthProvider');
  }
  return ctx;
}
