/**
 * NEXUS CEREBRO Login Form
 * React 19 useActionState for form handling
 */
import { useActionState } from 'react';
import { useAuth } from '../context/AuthContext';

interface FormState {
  error: string | null;
}

export function LoginForm() {
  const { login } = useAuth();

  const [state, submitAction, isPending] = useActionState(
    async (_prev: FormState, formData: FormData): Promise<FormState> => {
      const username = formData.get('username') as string;
      const password = formData.get('password') as string;

      if (!username || !password) {
        return { error: 'Username and password are required' };
      }

      const success = await login(username, password);
      if (!success) {
        return { error: 'Invalid credentials' };
      }

      return { error: null };
    },
    { error: null }
  );

  return (
    <form action={submitAction} className="space-y-6 w-full max-w-sm">
      {/* NEXUS Logo/Title */}
      <div className="text-center mb-8">
        <h1 className="text-3xl font-bold text-white tracking-tight">
          NEXUS <span className="text-primary">CEREBRO</span>
        </h1>
        <p className="text-gray-400 mt-2">Multi-Agent Orchestrator</p>
      </div>

      {/* Username */}
      <div>
        <label htmlFor="username" className="block text-sm font-medium text-gray-300 mb-1">
          Username
        </label>
        <input
          id="username"
          name="username"
          type="text"
          autoComplete="username"
          required
          disabled={isPending}
          className="w-full px-4 py-2 rounded-lg bg-nexus-dark border border-gray-600
                     text-white placeholder-gray-500
                     focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent
                     disabled:opacity-50 disabled:cursor-not-allowed"
          placeholder="admin"
        />
      </div>

      {/* Password */}
      <div>
        <label htmlFor="password" className="block text-sm font-medium text-gray-300 mb-1">
          Password
        </label>
        <input
          id="password"
          name="password"
          type="password"
          autoComplete="current-password"
          required
          disabled={isPending}
          className="w-full px-4 py-2 rounded-lg bg-nexus-dark border border-gray-600
                     text-white placeholder-gray-500
                     focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent
                     disabled:opacity-50 disabled:cursor-not-allowed"
          placeholder="Enter password"
        />
      </div>

      {/* Error Message */}
      {state.error && (
        <div className="p-3 rounded-lg bg-danger/20 border border-danger/50">
          <p className="text-danger text-sm">{state.error}</p>
        </div>
      )}

      {/* Submit Button */}
      <button
        type="submit"
        disabled={isPending}
        className="w-full py-3 px-4 rounded-lg font-medium text-white
                   bg-primary hover:bg-blue-600
                   focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-2 focus:ring-offset-nexus-darker
                   disabled:opacity-50 disabled:cursor-not-allowed
                   transition-colors duration-200"
      >
        {isPending ? (
          <span className="flex items-center justify-center gap-2">
            <svg className="animate-spin h-5 w-5" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
            Signing in...
          </span>
        ) : (
          'Sign In'
        )}
      </button>

      {/* IRONCLAD Notice */}
      <p className="text-xs text-gray-500 text-center mt-4">
        V11.6.2 IRONCLAD - Zero Trust Authentication
      </p>
    </form>
  );
}
