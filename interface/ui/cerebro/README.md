# NEXUS CEREBRO - Mission Control Dashboard

**Version**: 12.4 | **React**: 19.0 | **TypeScript**: 5.7

Web interface for NEXUS orchestration with real-time WebSocket events and multi-mode swarm control.

---

## Tech Stack

| Technology | Version | Purpose |
|------------|---------|---------|
| React | 19.0.0 | UI framework |
| React Router | 7.1.0 | Routing |
| Zustand | 5.0.2 | State management |
| Tailwind CSS | 4.0.0 | Styling |
| Monaco Editor | 4.7.0 | Code viewing |
| Vite | 6.0.5 | Build tool |
| Vitest | 2.1.8 | Unit tests |
| Playwright | 1.57.0 | E2E tests |

---

## Project Structure

```
src/
+-- api/
|   +-- client.ts           # API client (JWT singleton, auto-inject auth)
+-- components/
|   +-- controls/
|   |   +-- MissionControl.tsx    # Swarm mode selector + ENGAGE/ABORT
|   +-- views/
|   |   +-- FileCommander.tsx     # Monaco editor + file tree
|   |   +-- HiveMap.tsx           # SVG graph visualization
|   +-- EventStream.tsx           # Real-time event display
|   +-- Header.tsx                # Navigation bar
|   +-- InteractionModal.tsx      # User interaction prompts
|   +-- LoginForm.tsx             # Authentication form
|   +-- ProtectedRoute.tsx        # Auth guard
+-- context/
|   +-- AuthContext.tsx       # JWT auth (IN-MEMORY ONLY)
+-- hooks/
|   +-- useWebSocket.ts       # WebSocket with exponential backoff
+-- pages/
|   +-- Dashboard.tsx         # Main dashboard (tabs + sidebar)
|   +-- Login.tsx             # Login page
+-- stores/
|   +-- eventStore.ts         # Zustand store for events
|   +-- graphStore.ts         # Zustand store for graph nodes
|   +-- interactionStore.ts   # Zustand store for interactions
+-- types/
|   +-- api.ts                # API response types
|   +-- events.ts             # WebSocket event types
+-- App.tsx                   # Router setup
+-- main.tsx                  # Entry point
+-- index.css                 # Global styles
```

---

## Security (IRONCLAD Compliance)

**CRITICAL**: This frontend follows IRONCLAD V11.6.2 security requirements:

| Requirement | Implementation |
|-------------|----------------|
| **No localStorage** | JWT stored in React state only (AuthContext) |
| **No sessionStorage** | Never used |
| **WebSocket Auth** | Token via query param `?token=<jwt>` |
| **Auto-Logout** | On token expiry (15min default) |
| **API Auth** | Authorization header auto-injected |

```typescript
// AuthContext.tsx - Token stored in memory only
const [token, setToken] = useState<string | null>(null);
// NEVER: localStorage.setItem('token', ...)
```

---

## Development

```bash
# Install dependencies
npm install

# Start development server (http://localhost:3000)
npm run dev

# Type check + build
npm run build

# Preview production build
npm run preview
```

---

## Testing

```bash
# Unit tests (Vitest)
npm test

# Unit tests with UI
npm run test:ui

# E2E tests (Playwright)
npx playwright install    # First time only
npx playwright test
```

### E2E Test Files

```
e2e/
+-- mission-control.spec.ts     # MissionControl interactions
+-- file-commander.spec.ts      # FileCommander operations
+-- dashboard-responsive.spec.ts # Responsive layout tests
```

---

## Components Reference

### Dashboard Layout

```
+-------------------------------------------------------------+
| CEREBRO V12.0 - Mission Cockpit                             |
+-----------------------------------+-------------------------+
| Tabs: [Hive Map] [Files]          | Mission Control         |
|                                   | - Mode selector (6)     |
| - HiveMap: Real-time graph        | - ENGAGE / ABORT        |
| - FileCommander: Monaco editor    +-------------------------+
|                                   | Event Stream            |
|                                   | - WebSocket live feed   |
+-----------------------------------+-------------------------+
```

### Key Components

| Component | Description |
|-----------|-------------|
| **HiveMap** | Custom SVG graph (no external graph lib for React 19 compat) |
| **FileCommander** | Monaco editor + recursive file tree from `/api/files/tree` |
| **MissionControl** | 6 Swarm modes: PARALLEL, SEQUENTIAL, LEAD_SUPPORT, PING_PONG, SPECIALIST, RED_BLUE |
| **EventStream** | Scrollable event list from WebSocket |
| **InteractionModal** | Modal for backend questions (approval, input) |

---

## WebSocket Protocol

### Connection

```typescript
const ws = new WebSocket(`ws://localhost:8765?token=${token}`);
```

### Event Types (40+)

| Category | Events |
|----------|--------|
| FSM | `fsm.state_changed`, `fsm.transition` |
| Swarm | `swarm.negotiation`, `swarm.mode_selected` |
| HiveMind | `hivemind.phase_started`, `hivemind.phase_completed` |
| Tool | `tool.execution_started`, `tool.execution_completed` |
| Interaction | `interaction.required` |

### Event Structure

```typescript
interface NexusEvent {
  type: string;
  timestamp: string;
  payload: Record<string, unknown>;
}
```

---

## API Endpoints

Backend: `http://localhost:8000/api/`

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/auth/login` | POST | Get JWT token |
| `/auth/refresh` | POST | Refresh token |
| `/workflow/start` | POST | Start task execution |
| `/workflow/status/{id}` | GET | Get workflow status |
| `/files/tree` | GET | Get file tree |
| `/health` | GET | Health check |

---

## Environment Variables

```env
VITE_API_URL=http://localhost:8000
VITE_WS_URL=ws://localhost:8765
```

---

## Build Output

```
dist/
+-- index.html
+-- assets/
|   +-- index-[hash].js    (~292KB)
|   +-- index-[hash].css   (~30KB)
```

---

*CEREBRO V12.4 - NEXUS Mission Control Dashboard*
