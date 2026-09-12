"""核心领域数据模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .exceptions import InvalidResponseError


@dataclass(frozen=True)
class Semester:
    academic_year: str
    term: str
    academic_year_term: str

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "Semester":
        try:
            return cls(
                academic_year=str(payload["p_xn"]),
                term=str(payload["p_xq"]),
                academic_year_term=str(payload["p_xnxq"]),
            )
        except (KeyError, TypeError) as error:
            raise InvalidResponseError("当前学期响应缺少必要字段") from error


@dataclass(frozen=True)
class Course:
    task_id: str
    category: str
    name: str
    raw: dict[str, Any] = field(repr=False)

    def as_legacy_value(self) -> tuple[str, str]:
        """用于与现有 class.txt 匹配流程兼容的 (id, category) 形式。"""

        return self.task_id, self.category
