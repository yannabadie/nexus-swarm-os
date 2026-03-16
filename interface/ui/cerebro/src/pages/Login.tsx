/**
 * NEXUS CEREBRO Login Page
 */
import { LoginForm } from '../components/LoginForm';

export function Login() {
  return (
    <div className="min-h-screen bg-nexus-darker flex items-center justify-center p-4">
      {/* Background gradient */}
      <div className="absolute inset-0 bg-gradient-to-br from-primary/10 via-transparent to-secondary/10 pointer-events-none" />

      {/* Login Card */}
      <div className="relative bg-nexus-dark rounded-2xl border border-gray-700 shadow-2xl p-8">
        <LoginForm />
      </div>
    </div>
  );
}
