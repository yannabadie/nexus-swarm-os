# NEXUS Frontend Workflows (CEREBRO)

**Version**: 12.4 | **Last Updated**: 2025-12-16

This document maps all frontend workflow paths in the CEREBRO dashboard.

---

## 1. Authentication Flow

IRONCLAD-compliant authentication with in-memory token storage.

```
+-----------------------------------------------------------------------------+
|                       AUTHENTICATION FLOW                                   |
+-----------------------------------------------------------------------------+
|                                                                             |
|  User opens app                                                             |
|        |                                                                    |
|        v                                                                    |
|  +-----------------+                                                       |
|  | AuthContext     |--> Check: token in state?                             |
|  | (React Context) |                                                       |
|  +-----------------+                                                       |
|        |                                                                    |
|        | No token                                                           |
|        v                                                                    |
|  +-----------------+                                                       |
|  | Redirect to     |                                                       |
|  | /login          |                                                       |
|  +-----------------+                                                       |
|        |                                                                    |
|        v                                                                    |
|  +-----------------+      POST /api/auth/login                             |
|  | LoginForm       |-----------------------------> Backend                 |
|  | (username/pass) |                                   |                   |
|  +-----------------+                                   |                   |
|        |                                               |                   |
|        |<---------------- JWT Response <--------------+                   |
|        |                                                                    |
|        v                                                                    |
|  +-----------------+                                                       |
|  | setToken(jwt)   |--> Store IN MEMORY ONLY                               |
|  | (AuthContext)   |    NEVER localStorage/sessionStorage                  |
|  +-----------------+                                                       |
|        |                                                                    |
|        v                                                                    |
|  +-----------------+                                                       |
|  | Redirect to     |                                                       |
|  | /dashboard      |                                                       |
|  +-----------------+                                                       |
|                                                                             |
+-----------------------------------------------------------------------------+
```

### Token Management

| Aspect | Implementation |
|--------|----------------|
| **Storage** | React state only (`useState`) |
| **Persistence** | None (refresh = re-login) |
| **Expiry** | 15 minutes (backend JWT_EXPIRY) |
| **Refresh** | POST /api/auth/refresh before expiry |
| **Auto-logout** | On 401 response or expiry |

---

## 2. WebSocket Connection Flow

Real-time event streaming with exponential backoff reconnection.

```
+-----------------------------------------------------------------------------+
|                       WEBSOCKET CONNECTION FLOW                             |
+-----------------------------------------------------------------------------+
|                                                                             |
|  Dashboard loads                                                            |
|        |                                                                    |
|        v                                                                    |
|  +-----------------+                                                       |
|  | useWebSocket    |--> Get token from AuthContext                         |
|  | hook            |                                                       |
|  +-----------------+                                                       |
|        |                                                                    |
|        v                                                                    |
|  +-----------------------------------------+                               |
|  | new WebSocket(ws://localhost:8765?token=<jwt>)                          |
|  +-----------------------------------------+                               |
|        |                                                                    |
|        | onopen                                                             |
|        v                                                                    |
|  +-----------------+                                                       |
|  | Reset reconnect |--> reconnectAttempts = 0                              |
|  | state           |                                                       |
|  +-----------------+                                                       |
|        |                                                                    |
|        | onmessage                                                          |
|        v                                                                    |
|  +-----------------+      +-----------------+                              |
|  | Parse event     |----->| eventStore      |--> Update events array       |
|  | JSON            |      | (Zustand)       |                              |
|  +-----------------+      +-----------------+                              |
|        |                                                                    |
|        | onclose/onerror                                                    |
|        v                                                                    |
|  +-----------------------------------------+                               |
|  | Exponential Backoff Reconnection         |                               |
|  | delay = min(30000, 1000 * 2^attempts)    |                               |
|  | Max attempts: 10                         |                               |
|  +-----------------------------------------+                               |
|                                                                             |
+-----------------------------------------------------------------------------+
```

### Event Handling

```typescript
// useWebSocket.ts
const handleMessage = (event: MessageEvent) => {
  const data = JSON.parse(event.data);

  // Route to appropriate store
  if (data.type === 'interaction.required') {
    interactionStore.addInteraction(data.payload);
  } else {
    eventStore.addEvent(data);
  }
};
```

---

## 3. Task Execution Flow (MissionControl)

User initiates task via MissionControl component.

```
+-----------------------------------------------------------------------------+
|                       TASK EXECUTION FLOW                                   |
+-----------------------------------------------------------------------------+
|                                                                             |
|  User input in MissionControl                                               |
|        |                                                                    |
|        v                                                                    |
|  +-----------------+                                                       |
|  | Select mode     |--> PARALLEL | SEQUENTIAL | LEAD_SUPPORT | etc.        |
|  | (6 options)     |                                                       |
|  +-----------------+                                                       |
|        |                                                                    |
|        | Click ENGAGE                                                       |
|        v                                                                    |
|  +-----------------+      POST /api/workflow/start                         |
|  | API Client      |-----------------------------> Backend                 |
|  | (auto-auth)     |    { task, mode, options }        |                   |
|  +-----------------+                                   |                   |
|        |                                               |                   |
|        |<---------------- { workflow_id } <-----------+                   |
|        |                                                                    |
|        v                                                                    |
|  +-----------------+                                                       |
|  | Store workflow  |--> Track in local state                               |
|  | ID              |                                                       |
|  +-----------------+                                                       |
|        |                                                                    |
|        | WebSocket events stream in                                         |
|        v                                                                    |
|  +-----------------+                                                       |
|  | EventStream     |--> Display real-time progress                         |
|  | component       |    fsm.*, swarm.*, tool.*, etc.                       |
|  +-----------------+                                                       |
|        |                                                                    |
|        | Task complete                                                      |
|        v                                                                    |
|  +-----------------+                                                       |
|  | Final result    |--> Display success/failure + output                   |
|  | in EventStream  |                                                       |
|  +-----------------+                                                       |
|                                                                             |
+-----------------------------------------------------------------------------+
```

### ABORT Flow

```
Click ABORT
     |
     v
POST /api/workflow/{id}/cancel
     |
     v
Backend cancels workflow
     |
     v
WebSocket: workflow.cancelled event
     |
     v
Update EventStream
```

---

## 4. Interaction Flow (HITL)

Backend requests human input during task execution.

```
+-----------------------------------------------------------------------------+
|                       INTERACTION FLOW (HITL)                               |
+-----------------------------------------------------------------------------+
|                                                                             |
|  Backend needs human input                                                  |
|        |                                                                    |
|        v                                                                    |
|  +-----------------------------------------+                               |
|  | WebSocket: interaction.required          |                               |
|  | { id, type, prompt, options? }           |                               |
|  +-----------------------------------------+                               |
|        |                                                                    |
|        v                                                                    |
|  +-----------------+                                                       |
|  | interactionStore|--> addInteraction(payload)                            |
|  | (Zustand)       |                                                       |
|  +-----------------+                                                       |
|        |                                                                    |
|        v                                                                    |
|  +-----------------+                                                       |
|  | InteractionModal|--> Render modal with prompt                           |
|  | component       |    Show options or free text input                    |
|  +-----------------+                                                       |
|        |                                                                    |
|        | User responds                                                      |
|        v                                                                    |
|  +-----------------+      POST /api/interaction/{id}/respond               |
|  | Send response   |-----------------------------> Backend                 |
|  |                 |    { response: "..." }            |                   |
|  +-----------------+                                   |                   |
|        |                                               |                   |
|        |<---------------- { success: true } <---------+                   |
|        |                                                                    |
|        v                                                                    |
|  +-----------------+                                                       |
|  | Remove from     |--> Close modal                                        |
|  | interactionStore|    Resume workflow                                    |
|  +-----------------+                                                       |
|                                                                             |
+-----------------------------------------------------------------------------+
```

### Interaction Types

| Type | UI Element | Example |
|------|------------|---------|
| `approval` | Yes/No buttons | "Execute this command?" |
| `choice` | Radio buttons | "Which file to edit?" |
| `input` | Text field | "Enter commit message" |

---

## 5. File Navigation Flow (FileCommander)

File tree browsing and code viewing.

```
+-----------------------------------------------------------------------------+
|                       FILE NAVIGATION FLOW                                  |
+-----------------------------------------------------------------------------+
|                                                                             |
|  Dashboard loads with Files tab                                             |
|        |                                                                    |
|        v                                                                    |
|  +-----------------+      GET /api/files/tree                              |
|  | FileCommander   |-----------------------------> Backend                 |
|  | (mount)         |                                   |                   |
|  +-----------------+                                   |                   |
|        |                                               |                   |
|        |<---------------- { tree: [...] } <-----------+                   |
|        |                                                                    |
|        v                                                                    |
|  +-----------------+                                                       |
|  | Render file     |--> Recursive tree component                           |
|  | tree sidebar    |    Folders collapsible                                |
|  +-----------------+                                                       |
|        |                                                                    |
|        | Click on file                                                      |
|        v                                                                    |
|  +-----------------+      GET /api/files/read?path=...                     |
|  | Fetch file      |-----------------------------> Backend                 |
|  | contents        |                                   |                   |
|  +-----------------+                                   |                   |
|        |                                               |                   |
|        |<---------------- { content: "..." } <--------+                   |
|        |                                                                    |
|        v                                                                    |
|  +-----------------+                                                       |
|  | Monaco Editor   |--> Display with syntax highlighting                   |
|  | (read-only)     |    Language auto-detected                             |
|  +-----------------+                                                       |
|                                                                             |
+-----------------------------------------------------------------------------+
```

### Security (PathGuard)

Backend validates all file paths:
- No path traversal (`../`)
- No sensitive directories (`.git`, `node_modules`, `__pycache__`)
- Workspace restriction enforced

---

## 6. State Management (Zustand)

Three Zustand stores manage application state.

```
+-----------------------------------------------------------------------------+
|                       ZUSTAND STORES                                        |
+-----------------------------------------------------------------------------+
|                                                                             |
|  +-----------------------------------------+                               |
|  |            eventStore                    |                               |
|  +-----------------------------------------+                               |
|  | events: NexusEvent[]                     |                               |
|  | addEvent(event)                          |                               |
|  | clearEvents()                            |                               |
|  | getEventsByType(type)                    |                               |
|  +-----------------------------------------+                               |
|                                                                             |
|  +-----------------------------------------+                               |
|  |          interactionStore                |                               |
|  +-----------------------------------------+                               |
|  | interactions: Interaction[]              |                               |
|  | currentInteraction: Interaction | null   |                               |
|  | addInteraction(interaction)              |                               |
|  | removeInteraction(id)                    |                               |
|  +-----------------------------------------+                               |
|                                                                             |
|  +-----------------------------------------+                               |
|  |            graphStore                    |                               |
|  +-----------------------------------------+                               |
|  | nodes: GraphNode[]                       |                               |
|  | edges: GraphEdge[]                       |                               |
|  | addNode(node)                            |                               |
|  | addEdge(edge)                            |                               |
|  | updateNodeStatus(id, status)             |                               |
|  +-----------------------------------------+                               |
|                                                                             |
+-----------------------------------------------------------------------------+
```

### Store Integration

```typescript
// In component
const events = useEventStore(state => state.events);
const addEvent = useEventStore(state => state.addEvent);

// In WebSocket hook
const { addEvent } = useEventStore.getState();
addEvent(parsedEvent);
```

---

*Frontend Workflows V12.4 - NEXUS CEREBRO Documentation*
