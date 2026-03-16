# NEXUS V12 Release Notes

**Release Series**: V12 "Production Ready"
**Release Date Range**: December 2025
**Branch**: NX

---

## V12.4 COGNITIVE BOOST (2025-12-16)

**Codename**: COGNITIVE BOOST
**Focus**: Proactive Intelligence & RAG Enhancement

### Features

| Feature | Description |
|---------|-------------|
| **StagnationPredictor** | Proactive detection of stuck states with calibrated thresholds (0.15/0.25/0.40) |
| **HybridBackend** | RRF fusion combining Dense + BM25S backends for +15% RAG recall |
| **MemoryCoordinator** | Adaptive domain weights with EMA learning for improved context retrieval |
| **OutputGuard DialogueAct** | Classification-based approach to reduce false positive prompt injection alerts |

### Technical Details

- 29 new tests for StagnationPredictor
- RRF (Reciprocal Rank Fusion) with k=60
- EMA (Exponential Moving Average) for weight adaptation

---

## V12.3 SCALE-OUT (2025-12-15)

**Codename**: SCALE-OUT
**Focus**: Multi-Instance Deployment

### Features

| Feature | Description |
|---------|-------------|
| **Redis Workflow Registry** | Replaces in-memory dict for workflow storage with graceful degradation |
| **Distributed Locks** | Redlock pattern implementation with 30s timeout and auto-release |
| **SuccessMemory Fix** | Added logging for recording failures (was silent pass) |
| **Hibernation Redis** | Optional write-through cache for multi-instance support |

### Configuration

```env
REDIS_URL=redis://localhost:6379
USE_REDIS_WORKFLOWS=true
USE_REDIS_HIBERNATION=false
WORKFLOW_TTL_HOURS=24
```

### Technical Details

- 47 new tests for workflow module
- Tenant isolation via `workflows:{tenant_id}` hash
- 24h TTL for completed/failed workflows

---

## V12.2 IRONCLAD COMPLETE (2025-12-14)

**Codename**: IRONCLAD COMPLETE
**Focus**: Enterprise Security

### Features

| Feature | Description |
|---------|-------------|
| **User Management** | CRUD endpoints for user administration, SQLite storage |
| **RBAC** | Role-based access control (admin, operator, viewer) |
| **JWT Hardening** | Refresh tokens, token revocation support |
| **Security Audit Fixes** | All critical and high severity issues resolved |

### Roles

| Role | Permissions |
|------|-------------|
| admin | Full access, user management |
| operator | Execute workflows, view all |
| viewer | Read-only access |

---

## V12.1 RETINA COMPLETE (2025-12-13)

**Codename**: RETINA COMPLETE
**Focus**: Production Dashboard

### Features

| Feature | Description |
|---------|-------------|
| **HTTP Rate Limiting** | 100 requests/minute default, configurable per endpoint |
| **Production Dashboard** | Metrics, health checks, system status |
| **WebSocket Stability** | Thread-safe event emission, session management fixes |

### Configuration

```env
RATE_LIMIT_REQUESTS=100
RATE_LIMIT_PERIOD=60
```

---

## V12.0 RETINA VISUALS (2025-12-12)

**Codename**: RETINA VISUALS
**Focus**: Mission Control UI

### Features

| Feature | Description |
|---------|-------------|
| **HiveMap** | Custom SVG graph visualization (React 19 compatible) |
| **FileCommander** | Monaco editor with recursive file tree browser |
| **MissionControl** | All 6 Swarm modes (PARALLEL, SEQUENTIAL, LEAD_SUPPORT, PING_PONG, SPECIALIST, RED_BLUE) |
| **File Tree API** | GET /api/files/tree with PathGuard validation |

### Frontend Stack

- React 19.0.0
- React Router 7.1.0
- Zustand 5.0.2
- Tailwind CSS 4.0.0
- Vite 6.0.5
- Monaco Editor 4.7.0

### Build Output

- JavaScript: ~292KB
- CSS: ~30KB

---

## Migration Notes

### From V11.x to V12.x

1. **Environment Variables**: New variables required:
   ```env
   NEXUS_VERSION=12.4.0
   NEXUS_CODENAME=COGNITIVE BOOST
   ```

2. **Redis (Optional)**: For V12.3 multi-instance support:
   ```env
   REDIS_URL=redis://localhost:6379
   USE_REDIS_WORKFLOWS=true
   ```

3. **Frontend**: Install Node.js 18+ and run:
   ```bash
   cd interface/ui/cerebro
   npm install
   npm run build
   ```

4. **Security**: IRONCLAD compliance is now enforced:
   - JWT tokens in memory only (no localStorage)
   - WebSocket requires token authentication
   - Rate limiting enabled by default

---

## Compatibility

| Requirement | Version |
|-------------|---------|
| Python | 3.11+ |
| Node.js | 18+ (for frontend) |
| Redis | 6+ (optional, for V12.3+) |
| Claude CLI | Latest |
| Gemini CLI | Latest |

---

*V12 Release Notes - NEXUS Documentation*
