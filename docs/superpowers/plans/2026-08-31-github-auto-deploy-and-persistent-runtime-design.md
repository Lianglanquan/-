# GitHub 自动部署与持久化运行时实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 让 `main` 分支推送后自动构建、发布到腾讯云生产服务器，同时保证多测试者、多管理员的回答、AI 分析、证据链和审计数据独立持久化，不因代码部署丢失。

**Architecture:** GitHub Actions 在 `main` 推送时运行前后端验证，然后通过 SSH 将源码发布包上传到服务器。服务器使用版本目录加 `current` 软链接进行原子切换：新版本先安装和健康检查，成功后切换软链接并重启 Uvicorn；失败时保留旧版本并自动回滚。运行时数据库和上传/导出数据放在 `/srv/qiuzheng/shared/data/derived`，密钥放在 `/etc/qiuzheng/qiuzheng.env`，代码版本目录不承载用户数据。

**Tech Stack:** GitHub Actions, Ubuntu systemd, Nginx, Uvicorn, Python `venv`, SQLite WAL, Bash/SSH/rsync, Vite.

**Spec:** `docs/superpowers/plans/2026-08-31-github-auto-deploy-and-persistent-runtime-design.md`

## Global Constraints

- `main` 是唯一自动生产部署分支；Pull Request 只运行验证，不部署。
- 生产数据库与运行时文件必须在代码版本目录之外，并由 systemd 明确授予写权限。
- 发布失败不得切换 `current`；健康检查失败必须回滚并返回非零退出码。
- 不上传 `data/raw/`、本地测试数据库、真实调研数据或任何 `.env` 文件。
- 后端仍监听 `127.0.0.1:8000`，公网只开放 Nginx 的 `80/443` 与 SSH `22`。
- 部署必须可重复执行；同一 commit 重复部署不会破坏数据。

### Task 1: Persistent runtime layout and service configuration

**Files:**
- Modify: `deploy/systemd/qiuzheng.service`
- Modify: `deploy/README.md`
- Create: `deploy/scripts/prepare-server.sh`
- Test: `backend/tests/test_runtime_paths.py`

**Interfaces:**
- `prepare-server.sh APP_ROOT SHARED_ROOT` creates `/releases`, `/shared/data/derived`, `/shared/logs`, and `current` without deleting existing data.
- The systemd service reads `QIUZHENG_ROOT` and `QIUZHENG_DATA_ROOT` from its environment file and writes only to the shared data path.

- [ ] Write a test that verifies the configured runtime database path resolves from `QIUZHENG_DATA_ROOT` and defaults safely for local development.
- [ ] Run the focused test and observe the expected failure before implementation.
- [ ] Update configuration/path helpers and systemd `WorkingDirectory`, `ReadWritePaths`, and environment variables.
- [ ] Implement the idempotent server preparation script with explicit directory checks and ownership.
- [ ] Run backend compilation and focused tests.
- [ ] Commit the persistent-layout changes.

### Task 2: Atomic remote release and rollback script

**Files:**
- Create: `deploy/scripts/deploy-release.sh`
- Create: `deploy/scripts/healthcheck.sh`
- Modify: `deploy/README.md`
- Test: `backend/tests/test_deploy_contract.py`

**Interfaces:**
- `deploy-release.sh RELEASE_ARCHIVE COMMIT_SHA` extracts to `/srv/qiuzheng/releases/<commit>`, installs dependencies, validates the build, runs health checks, switches `/srv/qiuzheng/current`, and restarts `qiuzheng.service`.
- On any failure after extraction, the previous `current` symlink remains active and the script exits non-zero.
- `healthcheck.sh BASE_URL` checks `/health`, `/ready`, and the frontend root.

- [ ] Write contract tests for path traversal rejection, required commit identifier, and rollback-preserving behavior using a temporary directory.
- [ ] Run the focused tests and observe failure.
- [ ] Implement safe archive extraction and an atomic symlink switch using `ln -sfn`/`mv -T` only after validation.
- [ ] Add release retention of the latest five versions; never remove the active or previous version.
- [ ] Run shell syntax checks and focused tests.
- [ ] Commit the release scripts.

### Task 3: GitHub Actions production workflow

**Files:**
- Create: `.github/workflows/deploy-production.yml`
- Modify: `.github/workflows/ci.yml`
- Modify: `deploy/README.md`

**Interfaces:**
- Pushes to `main` run backend tests, frontend build, package filtering, upload over SSH, and remote release deployment.
- Required repository secrets are `PROD_HOST`, `PROD_PORT`, `PROD_USER`, and `PROD_SSH_KEY`; optional `PROD_APP_ROOT` defaults to `/srv/qiuzheng`.
- Pull requests never call the deployment job.

- [ ] Add a workflow lint-level test by parsing YAML and asserting the branch/event and secret names.
- [ ] Implement a build artifact that contains only deployable source/build files and excludes raw/derived sensitive data.
- [ ] Add SSH known-host verification and fail-fast remote commands.
- [ ] Add deployment concurrency so only one production release runs at a time, with later pushes queued.
- [ ] Run local YAML/script checks.
- [ ] Commit the workflow and documentation.

### Task 4: Server bootstrap and first automated deployment

**Files:**
- Modify: `deploy/README.md`
- No raw data files changed.

- [ ] Install/verify server prerequisites, create the shared layout, and migrate the existing SQLite database into the shared path without deleting it.
- [ ] Install the service and Nginx configuration so `/srv/qiuzheng/current` is the only code path used by production.
- [ ] Configure GitHub repository secrets through the authenticated GitHub account or document the one remaining secret action if the connector cannot write secrets.
- [ ] Trigger one deployment from `main` and inspect the GitHub Actions result.
- [ ] Verify public HTTPS, API health, login, and an existing session after deployment.
- [ ] Verify the database inode/path remains in the shared directory after a second deployment.

### Task 5: Verification and operational handoff

**Files:**
- Modify: `deploy/README.md`

- [ ] Run `npm run build`.
- [ ] Run `python -m compileall backend/app`.
- [ ] Run `python -m unittest discover -s backend/tests -v`.
- [ ] Run remote health checks and inspect service logs.
- [ ] Verify automatic certificate renewal configuration remains intact.
- [ ] Record exact rollback and manual recovery commands in deployment docs.
