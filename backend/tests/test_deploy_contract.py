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
        self.assertIn("PROD_SSH_KEY", workflow)
        self.assertIn("concurrency:", workflow)


if __name__ == "__main__":
    unittest.main()
