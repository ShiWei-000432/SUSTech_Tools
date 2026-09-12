"""日志必须可轮转且不能写入认证数据。"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest


LOGGING_MODULE_PATH = (
    Path(__file__).resolve().parents[1] / "sustech_tools" / "logging_service.py"
)
spec = importlib.util.spec_from_file_location("logging_service_under_test", LOGGING_MODULE_PATH)
logging_service = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(logging_service)


class LoggingServiceTests(unittest.TestCase):
    def test_authentication_values_are_redacted_from_log_file(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "app.log"
            logger = logging_service.configure_logging(path)
            logger.info("password=super-secret Cookie=SESSION=very-secret token=abc")
            for handler in logger.handlers:
                handler.flush()
            content = path.read_text(encoding="utf-8")

        self.assertNotIn("super-secret", content)
        self.assertNotIn("very-secret", content)
        self.assertNotIn("token=abc", content)
        self.assertIn("[REDACTED]", content)


if __name__ == "__main__":
    unittest.main()
