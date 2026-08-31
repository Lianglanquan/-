import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class PollerContractTests(unittest.TestCase):
    def test_poller_tracks_main_and_uses_release_deployer(self) -> None:
        script = (ROOT / "deploy/scripts/poll-and-deploy.sh").read_text(encoding="utf-8")
        self.assertIn('BRANCH="${BRANCH:-main}"', script)
        self.assertIn("safe.directory", script)
        self.assertIn("git -C \"$REPOSITORY\" fetch", script)
        self.assertIn("deploy-release.sh", script)
        self.assertIn(":(exclude)data/raw", script)
        self.assertIn(":(exclude)data/derived", script)

    def test_poller_timer_is_persistent(self) -> None:
        timer = (ROOT / "deploy/systemd/qiuzheng-deploy-poller.timer").read_text(encoding="utf-8")
        self.assertIn("Persistent=true", timer)
        self.assertIn("OnUnitActiveSec=2min", timer)


if __name__ == "__main__":
    unittest.main()
