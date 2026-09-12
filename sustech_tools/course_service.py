"""当前学期与课程任务查询服务。"""

from __future__ import annotations

from collections.abc import Callable
import time
from typing import Any

from .config import COURSE_QUERY_PATH, CURRENT_SEMESTER_PATH
from .exceptions import InvalidResponseError
from .models import Course, Semester
from .tis_client import TISClient


COURSE_TYPES = {
    "bxxk": "通识必修选课",
    "xxxk": "通识选修选课",
    "kzyxk": "培养方案内课程",
    "zynknjxk": "非培养方案内课程",
    "cxxk": "重修选课",
    "jhnxk": "计划内选课新生",
}


class CourseService:
    def __init__(
        self,
        client: TISClient,
        *,
        category_query_interval: float = 3.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.client = client
        self.category_query_interval = category_query_interval
        self._sleep = sleep

    def current_semester(self) -> Semester:
        payload = self.client.post_tis_json(CURRENT_SEMESTER_PATH, {"mxpylx": 1})
        return Semester.from_payload(payload)

    def fetch_courses(self, semester: Semester) -> list[Course]:
        courses: list[Course] = []
        for category in COURSE_TYPES:
            self._sleep(self.category_query_interval)
            payload = self.client.post_tis_json(
                COURSE_QUERY_PATH,
                {
                    "p_xn": semester.academic_year,
                    "p_xq": semester.term,
                    "p_xnxq": semester.academic_year_term,
                    "p_pylx": 1,
                    "mxpylx": 1,
                    "p_xkfsdm": category,
                    "pageNum": 1,
                    "pageSize": 1000,
                },
            )
            courses.extend(self._courses_from_payload(payload, category))
        return courses

    @staticmethod
    def _courses_from_payload(payload: dict[str, Any], category: str) -> list[Course]:
        try:
            rows = payload.get("kxrwList", {}).get("list", [])
            if not isinstance(rows, list):
                raise TypeError("list is not a list")
            return [
                Course(
                    task_id=str(row["id"]),
                    category=category,
                    name=str(row["rwmc"]),
                    raw=dict(row),
                )
                for row in rows
            ]
        except (AttributeError, KeyError, TypeError) as error:
            raise InvalidResponseError("课程查询响应缺少必要字段") from error

    @staticmethod
    def legacy_index(courses: list[Course]) -> dict[str, tuple[str, str]]:
        """供旧 class.txt 精确名称匹配使用；同名行为与旧实现一致，后者覆盖前者。"""

        return {course.name: course.as_legacy_value() for course in courses}
