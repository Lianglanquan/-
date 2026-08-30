# Production deployment

The production shape is deliberately small and reversible:

- Nginx serves the Vite `dist/` bundle and proxies `/api/*` plus `/health` to Uvicorn.
- Uvicorn runs as the unprivileged `ubuntu` user under systemd on `127.0.0.1:8000`.
- Runtime secrets live only in `/etc/qiuzheng/qiuzheng.env`; never commit them.
- Runtime SQLite/audit files stay under `data/derived/` and are excluded from Git.

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
