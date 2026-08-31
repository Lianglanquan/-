import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class DeploymentContractTests(unittest.TestCase):
    def test_release_script_keeps_runtime_outside_releases(self) -> None:
        script = (ROOT / "deploy/scripts/deploy-release.sh").read_text(encoding="utf-8")
        self.assertIn("SHARED_ROOT", script)
        self.assertIn("ln -sfn \"$SHARED_ROOT/data/derived\"", script)
        self.assertIn("previous release restored", script)
        self.assertIn("/etc/nginx/sites-available/qiuzheng.xyz.conf", script)

    def test_workflow_deploys_only_from_main(self) -> None:
        workflow = (ROOT / ".github/workflows/deploy-production.yml").read_text(encoding="utf-8")
        self.assertIn("branches: [main]", workflow)
        self.assertIn("PROD_HOST: 49.233.148.91", workflow)
        self.assertIn("PROD_SSH_KEY", workflow)
        self.assertIn("concurrency:", workflow)

    def test_release_script_bootstraps_http_when_certificate_is_not_ready(self) -> None:
        script = (ROOT / "deploy/scripts/deploy-release.sh").read_text(encoding="utf-8")
        fallback = (ROOT / "deploy/nginx/qiuzheng.xyz.http.conf").read_text(encoding="utf-8")
        self.assertIn("qiuzheng.xyz.http.conf", script)
        self.assertIn("/etc/letsencrypt/live/qiuzheng.xyz/fullchain.pem", script)
        self.assertIn("listen 80", fallback)
        self.assertNotIn("ssl_certificate", fallback)

    def test_poller_can_bootstrap_a_clean_checkout(self) -> None:
        script = (ROOT / "deploy/scripts/poll-and-deploy.sh").read_text(encoding="utf-8")
        unit = (ROOT / "deploy/systemd/qiuzheng-deploy-poller.service").read_text(encoding="utf-8")
        self.assertIn('git clone', script)
        self.assertIn('--depth 1', script)
        self.assertIn('REPOSITORY_URL', script)
        self.assertIn('/srv/qiuzheng/source', unit)
        self.assertIn('https://github.com/Lianglanquan/-.git', unit)


if __name__ == "__main__":
    unittest.main()
