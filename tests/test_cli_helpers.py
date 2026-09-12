"""CLI 文件兼容辅助函数的离线测试。"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch


CLI_PATH = Path(__file__).resolve().parents[1] / "cli.py"


def import_cli():
    fake_requests = types.ModuleType("requests")

    class RequestException(Exception):
        pass

    fake_requests.RequestException = RequestException
    fake_requests.Timeout = RequestException
    fake_requests.exceptions = types.SimpleNamespace(SSLError=RequestException)
    fake_requests.Session = lambda: None
    for name in list(sys.modules):
        if name == "sustech_tools" or name.startswith("sustech_tools."):
            sys.modules.pop(name)
    with patch.dict(sys.modules, {"requests": fake_requests}):
        spec = importlib.util.spec_from_file_location("cli_under_test", CLI_PATH)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
    return module


class CliHelperTests(unittest.TestCase):
    def test_class_file_reader_removes_bom_and_blank_lines(self):
        cli = import_cli()
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "class.txt"
            path.write_text("\ufeff\n课程一\n\n课程二\n", encoding="utf-8")
            self.assertEqual(cli.load_target_names(path), ["课程一", "课程二"])


if __name__ == "__main__":
    unittest.main()
