/**
 * NEXUS CEREBRO Header Component
 * Navigation bar with user info and logout
 */
import { useAuth } from '../context/AuthContext';

interface Props {
  wsStatus: 'connecting' | 'connected' | 'disconnected' | 'error';
}

export function Header({ wsStatus }: Props) {
  const { user, logout, isExpiringSoon } = useAuth();

  const handleLogout = async () => {
    await logout();
  };

  return (
    <header className="bg-nexus-dark border-b border-gray-700">
      <div className="max-w-7xl mx-auto px-4 py-3 flex items-center justify-between">
        {/* Logo */}
        <div className="flex items-center gap-4">
          <h1 className="text-xl font-bold text-white">
            NEXUS <span className="text-primary">CEREBRO</span>
          </h1>
          <span className="text-xs text-gray-500 hidden sm:inline">V13.0 MEMORIA</span>
        </div>

        {/* Status & User */}
        <div className="flex items-center gap-6">
          {/* WebSocket Status */}
          <div className="flex items-center gap-2">
            <span
              className={`w-2 h-2 rounded-full ${
                wsStatus === 'connected' ? 'bg-secondary' :
                wsStatus === 'connecting' ? 'bg-warning animate-pulse' :
                wsStatus === 'error' ? 'bg-danger' :
                'bg-gray-500'
              }`}
            />
            <span className="text-sm text-gray-400 hidden sm:inline">
              {wsStatus === 'connected' ? 'Live' :
               wsStatus === 'connecting' ? 'Connecting...' :
               wsStatus === 'error' ? 'Error' :
               'Offline'}
            </span>
          </div>

          {/* Session Warning */}
          {isExpiringSoon && (
            <span className="text-sm text-warning hidden sm:inline">
              Session expiring soon
            </span>
          )}

          {/* User Info */}
          {user && (
            <div className="flex items-center gap-4">
              <div className="text-right hidden sm:block">
                <p className="text-sm text-white">{user.user_id}</p>
                <p className="text-xs text-gray-400">{user.tenant_id}</p>
              </div>

              {/* Logout Button */}
              <button
                onClick={handleLogout}
                className="px-3 py-1.5 text-sm rounded-lg
                           text-gray-300 hover:text-white hover:bg-white/10
                           transition-colors"
              >
                Logout
              </button>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}
