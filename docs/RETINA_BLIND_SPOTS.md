# OPERATION RETINA - Blind Spots Analysis

**Analysé par:** Claude (NEXUS V11.6.1 IRONCLAD)
**Date:** 2025-12-16
**Contexte:** Analyse du prompt conseiller pour RETINA FOUNDATION

---

## BLIND SPOTS CRITIQUES

### 1. WebSocket IDOR (CRITICAL - SAME AS IRONCLAD)

**Fichier:** `core/api/cerebro/routes/stream.py:58-64`

```python
# VULNERABLE CODE - Same pattern fixed in REST endpoints
# Fall back to simple tenant_id
if tenant_id:
    return WebSocketContext(
        tenant_id=tenant_id,  # <-- IDOR: User-controlled!
        user_id="anonymous",
        workspace_id=workspace_id,
    )
```

**Impact:** N'importe qui peut s'abonner aux events de n'importe quel tenant via:
```
ws://localhost:8080/ws/stream?tenant_id=admin
```

**Action Requise:** IRONCLAD V11.6.2 - Rendre JWT OBLIGATOIRE pour WebSocket

---

### 2. Wrong WebSocket URL in Prompt

**Prompt du conseiller:**
```typescript
const ws = new WebSocket(`ws://localhost:8080/ws/stream/default?token=${token}`);
```

**Endpoint réel (stream.py:69):**
```python
@router.websocket("/stream")  # Note: PAS de path parameter!
async def websocket_stream(
    websocket: WebSocket,
    tenant_id: Optional[str] = Query(None),
    workspace_id: str = Query("default"),  # Query param, pas path param
    token: Optional[str] = Query(None),
)
```

**URL Correcte:**
```typescript
const ws = new WebSocket(`ws://localhost:8080/ws/stream?workspace_id=default&token=${token}`);
```

---

### 3. JWT Storage Security

**Prompt conseiller:** `sessionStorage.setItem('token', token)`

**Problème:** sessionStorage est vulnérable à XSS (tout script peut lire)

**Alternatives:**
| Méthode | Sécurité XSS | Complexité | Recommandé |
|---------|--------------|------------|------------|
| HttpOnly Cookie | Immune | CORS config | Production |
| In-memory + refresh | Immune | Refresh logic | MVP acceptable |
| sessionStorage | Vulnérable | Simple | Non recommandé |

**Décision pour MVP:** In-memory avec AuthContext React (acceptable si CSP strict)

---

### 4. Missing `/api/files/tree` Endpoint

**Référencé dans RETINA VISUALS prompt:**
```typescript
const { data } = await api.get('/api/files/tree');
```

**Endpoints réels (files.py):**
- `GET /api/files/content` - Lire fichier
- `POST /api/files/save` - Écrire fichier
- `GET /api/files/info` - Metadata fichier

**Manquant:** Endpoint pour lister l'arborescence

**Solution:** Ajouter `/api/files/tree` endpoint ou utiliser `GET /api/files/content?path=.` avec traitement côté client

---

### 5. No Token Refresh Mechanism

**auth.py configuration:**
```python
TOKEN_EXPIRE_HOURS = 24  # Ligne 42
```

**Problème:** Pas d'endpoint `/api/auth/refresh`
- User forcé de se re-login après 24h
- Pas de silent refresh

**Impact UX:** Perte de session pendant utilisation prolongée

**Solution MVP:**
- Stocker `token_expiry`
- Redirect vers login 5min avant expiry
- (Future: refresh token flow)

---

### 6. No WebSocket Reconnection Logic

**Prompt conseiller:** Aucune mention de reconnection

**Problème:** WebSocket peut se déconnecter pour:
- Réseau instable
- Server restart
- Timeout inactivité

**Solution (à ajouter au prompt):**
```typescript
// hooks/useWebSocket.ts
const connect = () => {
  ws.current = new WebSocket(url);
  ws.current.onclose = () => {
    // Exponential backoff reconnect
    setTimeout(connect, Math.min(1000 * 2 ** retries, 30000));
  };
};
```

---

### 7. Workflow List Endpoint Exists!

**Prompt conseiller ne mentionne pas:**
```python
# workflow.py:231
@router.get("/")
async def list_workflows(user: AuthenticatedUser = Depends(require_auth)):
    """List workflows for the authenticated tenant."""
```

**Utile pour:** Dashboard affichant historique des workflows

---

## ENRICHED PROMPT - RETINA FOUNDATION V2

Corrections appliquées au prompt original:

```markdown
# OPERATION RETINA FOUNDATION V2 (ENRICHED)

## CORRECTIONS VS V1

| Element | V1 (Original) | V2 (Corrigé) |
|---------|---------------|--------------|
| WebSocket URL | `/ws/stream/default` | `/ws/stream?workspace_id=default` |
| Auth token | sessionStorage | In-memory AuthContext |
| Reconnection | Non mentionné | Exponential backoff |
| Token expiry | Non géré | Check + redirect |

## STRUCTURE CORRIGÉE

```
interface/
+-- ui/
    +-- cerebro/
        +-- src/
        |   +-- components/
        |   |   +-- LoginForm.tsx      # POST /api/auth/login
        |   |   +-- Dashboard.tsx       # Main layout
        |   +-- context/
        |   |   +-- AuthContext.tsx     # IN-MEMORY token storage
        |   +-- hooks/
        |   |   +-- useAuth.ts          # Login/logout + token expiry check
        |   |   +-- useWebSocket.ts     # WS + reconnection logic
        |   +-- stores/
        |   |   +-- eventStore.ts       # Zustand for events
        |   +-- App.tsx                 # Protected routes
        |   +-- main.tsx                # Entry point
        +-- vite.config.ts              # Proxy /api + /ws
        +-- package.json
        +-- tailwind.config.js
```

## AuthContext.tsx (CORRIGÉ - In-Memory)

```typescript
import { createContext, useContext, useState, useCallback, ReactNode } from 'react';

interface AuthState {
  token: string | null;
  user: { user_id: string; tenant_id: string } | null;
  expiresAt: number | null;
}

interface AuthContextType extends AuthState {
  login: (username: string, password: string) => Promise<boolean>;
  logout: () => void;
  isAuthenticated: boolean;
  isExpiringSoon: boolean;
}

const AuthContext = createContext<AuthContextType | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({
    token: null,
    user: null,
    expiresAt: null,
  });

  const login = useCallback(async (username: string, password: string) => {
    const res = await fetch('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    });

    if (!res.ok) return false;

    const data = await res.json();
    // Store in memory ONLY (not sessionStorage)
    setState({
      token: data.access_token,
      user: { user_id: data.user_id, tenant_id: data.tenant_id },
      expiresAt: Date.now() + (24 * 60 * 60 * 1000), // 24h
    });
    return true;
  }, []);

  const logout = useCallback(() => {
    setState({ token: null, user: null, expiresAt: null });
  }, []);

  // Check if token expires in less than 5 minutes
  const isExpiringSoon = state.expiresAt
    ? (state.expiresAt - Date.now()) < 5 * 60 * 1000
    : false;

  return (
    <AuthContext.Provider value={{
      ...state,
      login,
      logout,
      isAuthenticated: !!state.token,
      isExpiringSoon,
    }}>
      {children}
    </AuthContext.Provider>
  );
}

export const useAuth = () => {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
};
```

## useWebSocket.ts (CORRIGÉ - Reconnection)

```typescript
import { useEffect, useRef, useCallback, useState } from 'react';
import { useAuth } from '../context/AuthContext';

interface WebSocketOptions {
  workspace?: string;
  eventTypes?: string[];
  onEvent?: (event: any) => void;
  onConnect?: () => void;
  onDisconnect?: () => void;
}

export function useWebSocket(options: WebSocketOptions = {}) {
  const { token, isAuthenticated } = useAuth();
  const ws = useRef<WebSocket | null>(null);
  const retries = useRef(0);
  const [status, setStatus] = useState<'connecting' | 'connected' | 'disconnected'>('disconnected');

  const connect = useCallback(() => {
    if (!token || !isAuthenticated) return;

    const workspace = options.workspace || 'default';
    const eventFilter = options.eventTypes?.join(',') || '';

    // CORRECTED URL: Query params, not path params
    const params = new URLSearchParams({
      workspace_id: workspace,
      token: token,
      ...(eventFilter && { event_types: eventFilter }),
    });

    const wsUrl = `ws://${window.location.host}/ws/stream?${params}`;

    setStatus('connecting');
    ws.current = new WebSocket(wsUrl);

    ws.current.onopen = () => {
      retries.current = 0;
      setStatus('connected');
      options.onConnect?.();
    };

    ws.current.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        options.onEvent?.(data);
      } catch (e) {
        console.error('WebSocket parse error:', e);
      }
    };

    ws.current.onclose = () => {
      setStatus('disconnected');
      options.onDisconnect?.();

      // RECONNECTION with exponential backoff
      if (isAuthenticated) {
        const delay = Math.min(1000 * Math.pow(2, retries.current), 30000);
        retries.current++;
        setTimeout(connect, delay);
      }
    };

    ws.current.onerror = (error) => {
      console.error('WebSocket error:', error);
    };
  }, [token, isAuthenticated, options]);

  useEffect(() => {
    if (isAuthenticated) {
      connect();
    }

    return () => {
      ws.current?.close();
    };
  }, [isAuthenticated, connect]);

  const disconnect = useCallback(() => {
    retries.current = Infinity; // Prevent reconnection
    ws.current?.close();
  }, []);

  return { status, disconnect };
}
```

## vite.config.ts (INCHANGÉ - Correct)

```typescript
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    proxy: {
      '/api': {
        target: 'http://localhost:8080',
        changeOrigin: true,
      },
      '/ws': {
        target: 'ws://localhost:8080',
        ws: true,
      },
    },
  },
});
```
```

---

## RECOMMANDATION D'EXÉCUTION

```
+----------------------------------------------------------------+
| PHASE 0: IRONCLAD V11.6.2 (WebSocket Security)      [15 min]  |
| +- Fix stream.py IDOR - MANDATORY JWT for WebSocket           |
+----------------------------------------------------------------+
| PHASE 1: RETINA FOUNDATION                          [60 min]  |
| +- Create interface/ui/cerebro structure                      |
| +- Implement AuthContext (in-memory)                          |
| +- Implement useWebSocket (with reconnection)                 |
| +- Create LoginForm + Dashboard                               |
| +- Configure Vite proxy                                       |
+----------------------------------------------------------------+
| PHASE 2: RETINA VISUALS (FUTURE)                              |
| +- Add /api/files/tree endpoint                               |
| +- React Flow graph                                           |
| +- Monaco editor                                              |
+----------------------------------------------------------------+
```

---

## SOURCES

- [OWASP WebSocket Security](https://owasp.org/www-project-web-security-testing-guide/latest/4-Web_Application_Security_Testing/11-Client-side_Testing/10-Testing_WebSockets)
- [React 18 Security Best Practices](https://react.dev/reference/react-dom/client)
- [Vite Proxy Configuration](https://vitejs.dev/config/server-options.html#server-proxy)
