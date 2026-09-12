"""选课提交服务，以及不可绕过的 Dry Run 保护。"""

from __future__ import annotations

from dataclasses import dataclass

from .config import ENROLLMENT_PATH
from .models import Course, Semester
from .tis_client import TISClient


@dataclass(frozen=True)
class EnrollmentResult:
    status: str
    message: str
    submitted: bool


class EnrollmentService:
    def __init__(self, client: TISClient) -> None:
        self.client = client

    def attempt(
        self, semester: Semester, course: Course, *, dry_run: bool = False
    ) -> EnrollmentResult:
        if dry_run:
            return EnrollmentResult(
                status="skipped",
                message="只读预演：未发送选课提交请求",
                submitted=False,
            )

        payload = self.client.post_tis_json(
            ENROLLMENT_PATH,
            {
                "p_pylx": 1,
                "p_xktjz": "rwtjzyx",
                "p_xn": semester.academic_year,
                "p_xq": semester.term,
                "p_xnxq": semester.academic_year_term,
                "p_xkfsdm": course.category,
                "p_id": course.task_id,
                "p_sfxsgwckb": 1,
            },
        )
        message = str(payload.get("message", "TIS 未返回选课结果说明"))
        return EnrollmentResult(
            status=self._classify(message),
            message=message,
            submitted=True,
        )

    @staticmethod
    def _classify(message: str) -> str:
        if "成功" in message:
            return "success"
        if "冲突" in message:
            return "conflict"
        if "已选" in message:
            return "already_selected"
        if "已满" in message:
            return "full"
        return "failed"
