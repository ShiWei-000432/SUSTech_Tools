"""课程缓存的版本化 JSON 格式。"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path

from .exceptions import InvalidResponseError
from .models import Course, Semester


CACHE_VERSION = 1


class CourseCache:
    def __init__(self, path: Path) -> None:
        self.path = path

    def save(self, semester: Semester, courses: list[Course]) -> None:
        payload = {
            "version": CACHE_VERSION,
            "semester": asdict(semester),
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "course_count": len(courses),
            "courses": [
                {
                    "task_id": course.task_id,
                    "category": course.category,
                    "name": course.name,
                    "raw": course.raw,
                }
                for course in courses
            ],
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary_path.write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )
        temporary_path.replace(self.path)

    def load(self, semester: Semester) -> list[Course] | None:
        if not self.path.is_file():
            return None
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if payload["version"] != CACHE_VERSION:
                return None
            cached_semester = Semester(**payload["semester"])
            if cached_semester != semester:
                return None
            courses = [
                Course(
                    task_id=str(row["task_id"]),
                    category=str(row["category"]),
                    name=str(row["name"]),
                    raw=dict(row["raw"]),
                )
                for row in payload["courses"]
            ]
            if payload["course_count"] != len(courses):
                raise ValueError("课程数量不一致")
            return courses
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
            raise InvalidResponseError("课程缓存损坏") from error

    @staticmethod
    def load_legacy(path: Path, semester: Semester) -> list[Course] | None:
        """读取旧两行 course.txt，作为一次性兼容入口而不重写原文件。"""

        if not path.is_file():
            return None
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
            if len(lines) < 2 or lines[0].strip() != semester.academic_year_term:
                return None
            index = json.loads(lines[1])
            if not isinstance(index, dict):
                raise ValueError("课程索引不是对象")
            return [
                Course(
                    task_id=str(value[0]),
                    category=str(value[1]),
                    name=str(name),
                    raw={"source": "legacy-course.txt"},
                )
                for name, value in index.items()
            ]
        except (OSError, ValueError, IndexError, TypeError, json.JSONDecodeError) as error:
            raise InvalidResponseError("旧 course.txt 缓存损坏") from error
