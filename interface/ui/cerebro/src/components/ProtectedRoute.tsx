/**
 * Protected Route Component
 * Redirects to login if not authenticated
 */
import { Navigate, useLocation } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import type { ReactNode } from 'react';

interface Props {
  children: ReactNode;
}

export function ProtectedRoute({ children }: Props) {
  const { isAuthenticated, isExpiringSoon } = useAuth();
  const location = useLocation();

  // Redirect to login if not authenticated
  if (!isAuthenticated) {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }

  // Warn user if token expiring soon (still allow access)
  if (isExpiringSoon) {
    console.warn('[ProtectedRoute] Session expiring soon - user should re-login');
  }

  return <>{children}</>;
}
