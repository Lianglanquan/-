# Production deployment

The production shape is deliberately small and reversible:

- Nginx serves the Vite `dist/` bundle from `/srv/qiuzheng/current` and proxies `/api/*` plus `/health` to Uvicorn.
- Uvicorn runs as the unprivileged `ubuntu` user under systemd on `127.0.0.1:8000`.
- Runtime secrets live only in `/etc/qiuzheng/qiuzheng.env`; never commit them.
- `/srv/qiuzheng/releases` contains code releases; `/srv/qiuzheng/current` is the atomically switched active release.
- `/srv/qiuzheng/shared/data/derived` contains the SQLite audit database and runtime exports. It is never replaced by a release.

Authentication must be configured before opening the service to participants:

```dotenv
ADMIN_EMAILS=first-admin@example.com,second-admin@example.com
RESEND_API_KEY=re_...
AUTH_FROM_EMAIL=auth@qiuzheng.xyz
AUTH_APP_URL=https://qiuzheng.xyz
AUTH_COOKIE_SECURE=true
```

`ADMIN_EMAILS` is the complete administrator allowlist. Every other verified
email is a participant and can only read its own assessment sessions. Keep the
Resend key only in the server environment file; rotate it if it has ever been
shared in chat, shell history, or screenshots.

## Automatic production deployment

The `deploy-production` workflow runs only after a push to `main`. Pull requests
run the reusable verification workflow but never touch the server. Configure
these repository Actions secrets once under **Settings -> Secrets and
variables -> Actions**:

| Secret | Value |
| --- | --- |
| `PROD_HOST` | `49.233.148.91` |
| `PROD_PORT` | `22` |
| `PROD_USER` | `ubuntu` |
| `PROD_SSH_KEY` | The private key whose public key is authorized for `ubuntu` |
| `PROD_APP_ROOT` | `/srv/qiuzheng` |

The deploy key is used only by Actions and is never committed to the
repository. The first server bootstrap can be run once with:

```bash
sudo bash deploy/scripts/prepare-server.sh /srv/qiuzheng /srv/qiuzheng/shared
```

The server also runs `qiuzheng-deploy-poller.timer` every two minutes. It pulls
the public `main` branch and invokes the same release script when a new commit
appears, so production deployment does not depend on a GitHub secret being
present. GitHub Actions remains available as a faster path when the optional
`PROD_*` secrets are configured.

Each release is health-checked before activation. If `/ready` does not become
healthy, the previous `current` release is restored automatically. To inspect
the active release and data location:

```bash
readlink -f /srv/qiuzheng/current
ls -l /srv/qiuzheng/shared/data/derived/audit.sqlite3
```

Before creating a release commit or a public demo image, clear local test
sessions with the guarded command below. It does not touch `data/raw/`:

```bash
./.venv/bin/python scripts/reset_runtime.py --confirm
```

The supplied `qiuzheng.xyz.conf` is the HTTP bootstrap configuration. After the
domain A record points to the server, issue a certificate with:

```bash
sudo certbot --nginx -d qiuzheng.xyz -d www.qiuzheng.xyz
```

Certbot will add the HTTPS listener and redirect HTTP. Renewals are handled by
the package's systemd timer; verify with `sudo certbot renew --dry-run`.
