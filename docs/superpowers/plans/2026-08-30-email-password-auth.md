# 邮箱密码身份认证 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为参与者和多个管理员建立安全的邮箱+密码登录、评估会话归属和管理员全量查看闭环。

**Architecture:** 在现有 SQLite AuditStore 中增加用户、认证挑战、服务端会话和管理员访问审计表；通过 FastAPI 依赖从 HttpOnly Cookie 解析当前用户，并把 user_id 注入 AssessmentStore 的 session。前端增加登录/注册/邮箱验证/恢复会话状态，保留现有小猫和 Evidence Map 业务；研究接口改为管理员会话保护并保留 legacy token 兼容开关。

**Tech Stack:** Python 3.12、FastAPI、SQLite、stdlib `hashlib.scrypt`、Resend HTTP API、React 18、Vite、TypeScript。

**Spec:** `docs/superpowers/specs/2026-08-30-email-password-auth-design.md`

## Global Constraints

- 所有人都必须登录后才能开始新的评估。
- 登录方式为邮箱+密码；密码不以明文保存。
- 管理员只有一个角色 `ADMIN`，但允许多个管理员邮箱。
- 管理员邮箱由后端白名单控制；非白名单邮箱只能成为参与者。
- 参与者只能读取自己的评估会话；管理员可以查看全部参与者数据和 AI 分析。
- Resend API key 只存在后端运行环境，不进入前端、Git 或日志。
- 现有小猫、逐题 Rubric、Session Orchestrator 和 Evidence Map 行为保持不变。
- 原始数据继续保留在 `data/raw/`，生成数据继续写入 `data/derived/`。

---

### Task 1: 认证数据层和密码工具

**Files:**
- Create: `backend/app/auth/__init__.py`
- Create: `backend/app/auth/service.py`
- Modify: `backend/app/audit/store.py`
- Modify: `backend/requirements.txt`
- Test: `backend/tests/test_auth.py`

**Interfaces:**
- `AuthService.register(email: str, password: str) -> dict[str, Any]`
- `AuthService.verify_email(email: str, code: str) -> dict[str, Any]`
- `AuthService.login(email: str, password: str) -> tuple[dict[str, Any], str]`
- `AuthService.logout(token: str) -> None`
- `AuthService.current_user(token: str | None) -> dict[str, Any] | None`
- `AuditStore.create_user(...)`, `find_user_by_email(...)`, `create_auth_challenge(...)`, `consume_auth_challenge(...)`, `create_auth_session(...)`, `get_auth_session_user(...)`

- [ ] **Step 1: Write failing tests**

Add tests that assert password hashing is salted and verifiable, registration normalizes email and assigns `ADMIN` only when the normalized email is in `ADMIN_EMAILS`, duplicate registration is rejected without revealing whether an account exists, expired/reused verification codes fail, login returns a session token, and logout invalidates it.

- [ ] **Step 2: Run the auth tests to verify the expected failure**

Run: `python3 -m unittest backend.tests.test_auth -v`

Expected: FAIL because the auth module and AuditStore methods do not exist yet.

- [ ] **Step 3: Implement the minimal data layer and password/session service**

Add SQLite tables with idempotent migrations. Use `hashlib.scrypt` with a random salt for passwords, SHA-256 hashes for lookup tokens/codes, normalized lowercase emails, a 10-minute single-use verification challenge, and a server-side random session token whose hash is stored in SQLite. Inject a mailer interface so tests can use an in-memory sender while production uses Resend.

- [ ] **Step 4: Run the focused tests to verify they pass**

Run: `python3 -m unittest backend.tests.test_auth -v`

Expected: all auth data-layer tests PASS.

- [ ] **Step 5: Commit the data layer**

```bash
git add backend/app/auth backend/app/audit/store.py backend/requirements.txt backend/tests/test_auth.py
git commit -m "feat: add password auth data layer"
```

### Task 2: FastAPI auth, ownership, and administrator boundaries

**Files:**
- Modify: `backend/app/security.py`
- Modify: `backend/app/api/routes.py`
- Modify: `backend/app/assessment/service.py`
- Modify: `backend/app/audit/store.py`
- Test: `backend/tests/test_auth.py`
- Test: `backend/tests/test_pipeline.py`

**Interfaces:**
- `POST /api/auth/register`
- `POST /api/auth/verify-email`
- `POST /api/auth/login`
- `POST /api/auth/logout`
- `GET /api/auth/me`
- `GET /api/assessment/sessions`
- `require_current_user(...) -> dict[str, Any]`
- `require_admin_access(...) -> dict[str, Any]`

- [ ] **Step 1: Write failing route and ownership tests**

Cover unauthenticated start/read/write rejection, participant session isolation, admin whitelist access to all sessions, non-admin rejection from research endpoints, and access log creation when an admin reads a participant session.

- [ ] **Step 2: Run the focused tests to verify failure**

Run: `python3 -m unittest backend.tests.test_auth backend.tests.test_pipeline -v`

Expected: FAIL because current assessment start has no user dependency and research access only accepts the static token.

- [ ] **Step 3: Implement route dependencies and session ownership**

Read the auth cookie, resolve the user server-side, require verified active users for participant endpoints, and require `ADMIN` for research endpoints. Change `AssessmentStore.start(user_id=...)` and all session reads/writes to enforce ownership unless the caller is an admin. Preserve direct `require_research_access("unit-test-token")` compatibility for existing tests, but make browser requests use the authenticated admin cookie.

- [ ] **Step 4: Run focused and existing backend tests**

Run: `python3 -m unittest backend.tests.test_auth backend.tests.test_pipeline -v`

Expected: all auth, ownership, and pre-existing pipeline tests PASS.

- [ ] **Step 5: Commit the API boundary**

```bash
git add backend/app/security.py backend/app/api/routes.py backend/app/assessment/service.py backend/app/audit/store.py backend/tests/test_auth.py backend/tests/test_pipeline.py
git commit -m "feat: enforce authenticated assessment ownership"
```

### Task 3: Resend mail delivery and environment configuration

**Files:**
- Create: `backend/app/auth/mailer.py`
- Modify: `backend/app/config.py`
- Modify: `backend/requirements.txt`
- Modify: `.gitignore`
- Create: `.env.example`
- Test: `backend/tests/test_auth.py`

**Interfaces:**
- `ResendMailer.send_verification_code(email: str, code: str) -> None`
- `ResendMailer.send_password_reset_code(email: str, code: str) -> None`

- [ ] **Step 1: Write failing mailer tests**

Assert the mailer refuses to send when `RESEND_API_KEY` or `AUTH_FROM_EMAIL` is absent, sends only non-sensitive verification content to the configured Resend endpoint, and never includes responses, scores, AI analysis, or risk labels.

- [ ] **Step 2: Run the focused mailer tests to verify failure**

Run: `python3 -m unittest backend.tests.test_auth -v`

Expected: FAIL because the mailer and environment keys do not exist.

- [ ] **Step 3: Implement the Resend adapter and safe config loading**

Use `urllib.request` with a Bearer token from `RESEND_API_KEY`, `AUTH_FROM_EMAIL`, and `AUTH_APP_URL`. Keep the API key server-only, redact it from exceptions/logs, and add `.env.example` with placeholders only.

- [ ] **Step 4: Run tests and compile the backend**

Run: `python3 -m unittest backend.tests.test_auth -v && python3 -m compileall backend/app`

Expected: all focused tests PASS and compileall exits 0.

- [ ] **Step 5: Commit the mailer**

```bash
git add backend/app/auth/mailer.py backend/app/config.py backend/requirements.txt .gitignore .env.example backend/tests/test_auth.py
git commit -m "feat: add resend authentication mailer"
```

### Task 4: Participant login, verification, and session recovery UI

**Files:**
- Create: `src/components/auth/AuthFlow.tsx`
- Modify: `src/App.tsx`
- Modify: `src/index.css`
- Test: `npm run build`

**Interfaces:**
- `AuthFlow` owns email/password, verification-code, login/register states and emits `onAuthenticated(user)`.
- `App` owns `GET /api/auth/me`, auth cookie lifecycle, target route, and assessment start/resume.

- [ ] **Step 1: Add a UI contract test or compile guard for the auth states**

The test/build contract must cover login, registration, email verification, invalid credentials, and the disabled “开始评估” state while unauthenticated.

- [ ] **Step 2: Run the frontend build to observe the missing implementation**

Run: `npm run build`

Expected: FAIL until the new component and App integration are implemented.

- [ ] **Step 3: Implement the minimal participant auth flow**

Add a warm, compact login gate that asks for email and password, shows verification-code entry after registration, calls `/api/auth/me` on load, and resumes the participant’s latest session. Keep all existing assessment and cat copy intact after authentication.

- [ ] **Step 4: Run the frontend build**

Run: `npm run build`

Expected: PASS with no TypeScript errors.

- [ ] **Step 5: Commit the participant auth UI**

```bash
git add src/components/auth/AuthFlow.tsx src/App.tsx src/index.css
git commit -m "feat: add participant email password login"
```

### Task 5: Administrator dashboard authentication and all-session view

**Files:**
- Modify: `src/App.tsx`
- Modify: `src/index.css`
- Modify: `backend/app/api/routes.py`
- Test: `backend/tests/test_auth.py`

**Interfaces:**
- `GET /api/admin/sessions`
- `GET /api/admin/sessions/{session_id}`
- Existing research/review/export endpoints accept the authenticated admin cookie.

- [ ] **Step 1: Write failing admin-view tests**

Assert that an authenticated admin can list a participant’s sessions and inspect the complete response/AI decision chain, while a participant receives 403 and each admin read creates an access-log row.

- [ ] **Step 2: Run the focused tests to verify failure**

Run: `python3 -m unittest backend.tests.test_auth -v`

Expected: FAIL because admin session list/detail endpoints and UI are not implemented.

- [ ] **Step 3: Implement admin session list/detail and UI**

Add a protected admin view with participant email masked by default, session status/timestamps, seed/probe counts, unresolved nodes, AI session intelligence, and a chronological event/decision trace. Keep the existing research/review pages available only after admin authentication.

- [ ] **Step 4: Run focused tests and frontend build**

Run: `python3 -m unittest backend.tests.test_auth -v && npm run build`

Expected: all focused tests and the build PASS.

- [ ] **Step 5: Commit the administrator surface**

```bash
git add src/App.tsx src/index.css backend/app/api/routes.py backend/tests/test_auth.py
git commit -m "feat: add authenticated administrator session view"
```

### Task 6: End-to-end verification, secret hygiene, and delivery

**Files:**
- Modify: `docs/PRODUCT.md`
- Modify: `docs/superpowers/specs/2026-08-30-email-password-auth-design.md`
- Modify: `.env.example`
- Test: `backend/tests/test_auth.py`
- Test: `backend/tests/test_pipeline.py`

- [ ] **Step 1: Run the complete verification suite**

Run: `npm run build && python3 -m unittest discover -s backend/tests -v && python3 -m compileall backend/app && git diff --check`

Expected: frontend build exits 0, all backend tests pass, compileall exits 0, and diff check is clean.

- [ ] **Step 2: Exercise the real local HTTP flow**

Start the backend with a test Resend mailer and run: register participant → verify code → login → start session → submit response → logout → reject session read → login as allowlisted admin → inspect the participant session → verify access log. Do not print passwords, codes, cookies, or API keys.

- [ ] **Step 3: Review secret hygiene and deployment variables**

Confirm `RESEND_API_KEY`, `AUTH_SECRET`, `AUTH_FROM_EMAIL`, `AUTH_APP_URL`, `ADMIN_EMAILS`, and `CORS_ORIGINS` are absent from Git and documented only as placeholders in `.env.example`. Rotate the user-provided Resend key after configuration.

- [ ] **Step 4: Request code review and resolve findings**

Review the complete diff against the spec, fix Critical/Important issues, and rerun the full verification suite.

- [ ] **Step 5: Commit and push the final implementation**

```bash
git add docs docs/PRODUCT.md .env.example backend src
git commit -m "feat: complete authenticated assessment workflow"
git push origin main
```
