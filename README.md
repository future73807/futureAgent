# futureAgent

futureAgent is a small, deployable team AI workspace. It has three separately deployable surfaces:

- **User workspace** — React + `@ant-design/x`, on port `5173` in development.
- **Model gateway** — LiteLLM, on port `4000` in Docker Compose.
- **Platform administration** — React + Ant Design, on port `5174` in development.

This repository is no longer a client-side role-selection demo. Identity, workspaces, conversations, plans, tasks, files, and audit events are persisted by the API and protected on the server.

## What is implemented

### Workspace product

- Email/password registration, sign-in, sign-out, access-token refresh, and `GET /api/v1/auth/me`.
- Short-lived access token in browser session storage; refresh token in an HttpOnly cookie.
- Multiple workspaces, member roles (`owner`, `admin`, `member`, `viewer`), ownership transfer, and server-side workspace boundaries via `X-Workspace-ID`.
- Persistent project board with projects, tasks, assignees, labels, priority, and workflow status.
- Task-board search and status filters for finding active work without losing its project context.
- Persistent AI conversations and workspace-scoped attachment uploads/downloads.
- Task-scoped input and deliverable files with authenticated downloads and bounded previews for text, Markdown, CSV, and JSON.
- Workspace audit events for sensitive and business actions.

### Work mode

Work mode is designed around a controlled delivery loop rather than a one-shot chat:

1. Draft a task-specific execution plan, either from scratch or from delivery, investigation, and incident-response templates.
2. Assign steps and record acceptance instructions.
3. Require a workspace owner or admin to approve the plan.
4. Move individual steps through `pending`, `running`, `blocked`, and `done`.
5. Record evidence, decisions, handoffs, or outcomes per step; all changes remain in the workspace audit trail.
6. Review a task-scoped activity timeline containing the task, plan, execution-step, and attached-file events.

The API controls who can approve and update each step. The UI only exposes the same permissions as the server; it does not trust a role sent from the browser.

## WorkBuddy reference boundary

The Work mode direction is informed by the publicly available Tencent WorkBuddy documentation, not by reverse engineering or undocumented claims. Those docs describe a task flow with natural-language tasks, contextual files, task states, continuing work, and a results area for artifacts, files, changes, and previews.

- [WorkBuddy overview](https://www.workbuddy.ai/docs/zh/workbuddy/Overview)
- [Create a task and add context](https://www.workbuddy.ai/docs/zh/workbuddy/Create-Task)
- [Task management](https://www.workbuddy.ai/docs/zh/workbuddy/Task-Management)
- [Result viewing](https://www.workbuddy.ai/docs/zh/workbuddy/Results)

futureAgent implements the web-team-workspace equivalents: persistent tasks and conversations, attached task inputs and deliverables, governed plans, approvals, execution evidence, search/filtering, and text-file previews. It deliberately does **not** claim the desktop-only ability to read arbitrary local folders or render every binary office format in the API process.

### Administration and model operations

- Separate administrator UI with real platform-admin authentication.
- Platform overview, user activation/admin controls, workspace overview, and global audit log.
- Platform-admin-only management APIs for skills, MCP configuration, Casbin policies, and runtime settings.
- LiteLLM model readiness preflight: in direct-provider mode, chat endpoints return a clear `503` before opening an SSE stream when LiteLLM or a usable provider credential is unavailable. A LiteLLM proxy route is deliberately displayed as “configured”, not as a verified model response.
- MCP server discovery and a local-tools service for controlled workspace operations.

## Architecture

```text
User workspace (5173) ─┐
                       ├── FastAPI API (8000) ── SQLite for local development
Admin workspace (5174) ┘                         └─ PostgreSQL in Compose
                                      │
                                      ├── LiteLLM gateway (4000)
                                      └── MCP local-tools service (8050)
```

The API owns authorization and data boundaries. Both frontend applications only call `/api` through their development proxy or the production Nginx route.

## Local development

### Prerequisites

- Python 3.11+
- Node.js 20+
- npm

### Start the API

```powershell
Copy-Item .env.example .env
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

### Start the two frontends

Use separate terminals:

```powershell
cd frontend
npm install
npm run dev
```

```powershell
cd admin-frontend
npm install
npm run dev
```

Open:

| Surface | Address |
| --- | --- |
| User workspace | http://localhost:5173 |
| Admin workspace | http://localhost:5174 |
| API health | http://127.0.0.1:8000/api/v1/health |
| API documentation | http://127.0.0.1:8000/docs |

Registration creates the first workspace and makes that user its owner. In development, the API can seed the configured bootstrap platform administrator; use it only for local verification and change all bootstrap credentials before deployment.

## API security contract

Protected calls require:

```http
Authorization: Bearer <access-token>
X-Workspace-ID: <workspace-id>
```

Roles are derived from the signed token and database membership. The API rejects the old `user_role` request field. Platform administration endpoints additionally require `is_platform_admin` on the authenticated user.

## Running with Docker Compose

```powershell
docker compose up --build
```

Compose provisions API, PostgreSQL, LiteLLM, MCP, user frontend, administrator frontend, and Nginx. Before exposing it publicly, create a production `.env` with a long random `JWT_SECRET_KEY`, a distinct LiteLLM master key, real model-provider credentials, and non-default PostgreSQL credentials.

## Verification

```powershell
python -m unittest discover -s tests -v

cd frontend
npm run build

cd ..\admin-frontend
npm run build

cd ..
docker compose config --quiet
```

The API tests cover authentication boundaries, workspace isolation, project/task creation, work-plan approval and step evidence, conversations, attachments, audit events, and model-unavailable preflight behavior.

## Production boundary

This is a commercial MVP foundation, not a claim of complete production certification. The following remain required before a public production launch:

- Configure and validate a real LiteLLM provider. A configured proxy route is not proof that an upstream model can answer; validate each intended model before public launch. Without a proxy, missing or placeholder provider credentials deliberately return `503`.
- Use PostgreSQL, a managed object store with malware scanning for uploads, TLS, backups, monitoring, alerting, and rate limits.
- Add a database migration process before evolving an existing production database; current startup table creation is suitable for a new local database, not schema migration management.
- Replace development bootstrap credentials, rotate secrets, restrict CORS to deployed domains, and run browser E2E tests against the target environment.

## License

MIT
