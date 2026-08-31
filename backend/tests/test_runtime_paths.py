import os
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.app.config import runtime_data_root


class RuntimePathTests(unittest.TestCase):
    def test_runtime_data_root_uses_explicit_shared_directory(self) -> None:
        with patch.dict(os.environ, {"QIUZHENG_DATA_ROOT": "/srv/qiuzheng/shared/data/derived"}, clear=False):
            self.assertEqual(runtime_data_root(), Path("/srv/qiuzheng/shared/data/derived"))

    def test_runtime_data_root_defaults_to_workspace_derived_directory(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(runtime_data_root(), Path(__file__).resolve().parents[2] / "data" / "derived")


if __name__ == "__main__":
    unittest.main()
