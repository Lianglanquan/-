# Evidence-First 管理员评审工作台实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把管理员端改造成证据优先、可复核、无感刷新的评估工作台，并让完成页采用成熟测评报告的渐进式阅读结构。

**Architecture:** 后端从现有会话事件、全局证据状态和专家仲裁记录生成稳定的 overview/report 聚合契约；前端新增轻量总览，并把单场会话页拆成报告导航、证据地图、20题矩阵和路径时间线。自动同步保留上一份成功数据，只在资源版本变化时替换局部状态。

**Tech Stack:** FastAPI、SQLite、Python unittest/pytest、React 18、TypeScript、Vite、现有 CSS 设计系统

**Spec:** `docs/superpowers/specs/2026-08-31-evidence-first-admin-workspace-design.md`

## Global Constraints

- 不改变参与者答题、小猫陪伴、安全流程和单题 Rubric 评分逻辑。
- 跨题信息只用于评估规划与管理员阅读，不得改写单题 0/1/2 评分。
- 管理员界面保持简洁、留白、低饱和；不以总分作为主视觉。
- 研究分层必须明确为研究规则，不得写成临床诊断或自动干预结论。
- 自动同步默认 30 秒；失败时保留旧数据；页面隐藏时暂停。
- 不提交 `data/derived/` 中的敏感或用户生成资料。

---

### Task 1: 会话级证据报告聚合

**Files:**
- Modify: `backend/app/assessment/reporting.py`
- Test: `backend/tests/test_session_reporting.py`

**Interfaces:**
- Consumes: `session.items`、`session.global_evidence`、`session.decision_history`、`session.adjudications`、Rubric 映射。
- Produces: `build_session_evidence_report(session, rubrics) -> dict`，字段固定为 `session_id`、`overview`、`constructs`、`item_matrix`、`timeline`、`probe_summary`、`uncertainty`、`ai_decisions`、`review_queue`、`versions`。

- [ ] **Step 1: 写失败测试**

  覆盖：20题矩阵不因跨题链接改分；构念同时暴露表现方向和证据质量；探针事件进入时间线；专家仲裁与原始分并存；版本信息完整。

- [ ] **Step 2: 运行报告测试并确认因缺少聚合函数而失败**

  Run: `python -m pytest backend/tests/test_session_reporting.py -q`

- [ ] **Step 3: 实现最小报告聚合函数**

  只读取现有证据，不写回事件；以最新题目事件形成矩阵，以 append-only 决策形成时间线。

- [ ] **Step 4: 运行报告测试并确认通过**

  Run: `python -m pytest backend/tests/test_session_reporting.py -q`

### Task 2: 管理员总览与报告 API

**Files:**
- Modify: `backend/app/api/routes.py`
- Test: `backend/tests/test_admin_api.py`

**Interfaces:**
- Produces: `GET /api/admin/overview` 与 `GET /api/admin/sessions/{session_id}/report`。
- 保留: 现有 `/api/admin/sessions` 与 `/api/admin/sessions/{session_id}` 兼容接口。

- [ ] **Step 1: 写失败 API 测试**

  验证普通参与者被拒绝；管理员总览返回会话、待复核、安全流程和优先节点；报告接口返回完整证据契约并记录审计访问。

- [ ] **Step 2: 运行 API 测试并确认 404/缺字段失败**

  Run: `python -m pytest backend/tests/test_admin_api.py -q`

- [ ] **Step 3: 实现路由与聚合调用**

  总览只输出管理员决策需要的摘要；报告失败返回可识别错误，不泄露内部信息。

- [ ] **Step 4: 运行 API 测试并确认通过**

  Run: `python -m pytest backend/tests/test_admin_api.py -q`

### Task 3: 管理员总览、单场报告与无感同步

**Files:**
- Create: `src/components/admin/AdminOverviewView.tsx`
- Replace: `src/components/admin/AdminSessionsView.tsx`
- Modify: `src/App.tsx`
- Modify: `src/index.css`
- Test: `backend/tests/test_admin_workspace_contract.py`

**Interfaces:**
- `AdminOverviewView` consumes `/api/admin/overview` payload and navigation callbacks.
- `AdminSessionsView` consumes session list、selected report、selected id、sync state、last-success timestamp。
- `App` defaults admins to `#overview` and polls only while visible.

- [ ] **Step 1: 写失败的静态契约测试**

  验证默认管理员路由、30秒轮询、visibility pause、报告五个核心区块、同步时不清空旧详情，以及用语中不出现“干预建议”。

- [ ] **Step 2: 运行契约测试并确认失败**

  Run: `python -m pytest backend/tests/test_admin_workspace_contract.py -q`

- [ ] **Step 3: 实现总览与报告组件**

  页面顺序采用成熟测评报告的“结论先行 → 证据解释 → 逐题展开 → 路径回放”，但不输出人格标签或诊断结论。

- [ ] **Step 4: 实现无感同步协议**

  首次加载才显示占位；背景刷新保留旧数据；失败保留旧数据；防止并发；隐藏页面暂停；恢复可见立即同步。

- [ ] **Step 5: 收敛完成页文案层级**

  保留现有小猫和安全分流，只把会话交付呈现为“本次轮廓、仍待理解、可以带走、下一步选择”的成熟报告结构。

- [ ] **Step 6: 运行契约测试与前端构建**

  Run: `python -m pytest backend/tests/test_admin_workspace_contract.py -q`

  Run: `npm run build`

### Task 4: 全量验证、提交与部署

**Files:**
- Modify only if verification exposes an in-scope defect.

- [ ] **Step 1: 运行后端完整测试**

  Run: `python -m pytest backend/tests -q`

- [ ] **Step 2: 运行后端编译与前端构建**

  Run: `python -m compileall backend/app`

  Run: `npm run build`

- [ ] **Step 3: 检查差异与敏感数据边界**

  Run: `git status --short && git diff --check && git diff --stat`

- [ ] **Step 4: 提交并推送 main**

  只添加本计划、规格和本次代码；不得添加 `data/derived/` 或无关脚本。

- [ ] **Step 5: 等待自动部署并核验线上**

  检查 `/api/health`、管理员登录、`#overview`、单场报告和背景同步行为。
