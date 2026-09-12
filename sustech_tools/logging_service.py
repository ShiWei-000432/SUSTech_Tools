"""脱敏、轮转的应用日志配置。"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import re


class SensitiveDataFilter(logging.Filter):
    """不让密码、Cookie 或 Token 从格式化日志中泄露。"""

    _patterns = (
        re.compile(r"(?i)(password|pwd)=[^&\s,]+"),
        re.compile(r"(?i)(cookie|set-cookie)=[^\r\n]+"),
        re.compile(r"(?i)(authorization|token)=[^\s,]+"),
    )

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        for pattern in self._patterns:
            message = pattern.sub(lambda match: f"{match.group(1)}=[REDACTED]", message)
        record.msg = message
        record.args = ()
        return True


def configure_logging(
    log_path: Path,
    *,
    level: int = logging.INFO,
    max_bytes: int = 1_000_000,
    backup_count: int = 3,
) -> logging.Logger:
    """配置应用命名空间日志；不会改动根日志器。"""

    log_path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("sustech_tools")
    logger.setLevel(level)
    logger.propagate = False

    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    handler = RotatingFileHandler(
        log_path, encoding="utf-8", maxBytes=max_bytes, backupCount=backup_count
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S")
    )
    handler.addFilter(SensitiveDataFilter())
    logger.addHandler(handler)
    return logger
