"""线程安全的选课队列与任务状态机。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import threading
import time
from typing import Protocol

from .enrollment_service import EnrollmentResult
from .exceptions import SUSTechToolsError
from .models import Course, Semester
from .rate_limiter import RateLimiter


class TaskState(str, Enum):
    IDLE = "idle"
    WAITING = "waiting"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"
    COMPLETED = "completed"
    FAILED = "failed"


FINAL_COURSE_STATES = {
    "success",
    "skipped",
    "conflict",
    "already_selected",
    "full",
    "failed",
}


@dataclass
class QueueItem:
    course: Course
    priority: int
    status: str = "waiting"
    attempts: int = 0
    last_result: str = ""
    last_attempt_at: float | None = None


class EnrollmentStrategy(Protocol):
    def select(self, items: list[QueueItem]) -> list[QueueItem]:
        """返回下一轮的条目；调用方持有队列锁。"""


class PriorityStrategy:
    """只选择最高优先级仍等待的课程，与旧模式 1 的语义一致。"""

    def select(self, items: list[QueueItem]) -> list[QueueItem]:
        waiting = [item for item in items if item.status == "waiting"]
        return waiting[:1]


class CycleStrategy:
    """选择本轮所有等待课程，与旧模式 2 的单轮语义一致。"""

    def select(self, items: list[QueueItem]) -> list[QueueItem]:
        return [item for item in items if item.status == "waiting"]


class EnrollmentExecutor(Protocol):
    def attempt(
        self, semester: Semester, course: Course, *, dry_run: bool
    ) -> EnrollmentResult:
        ...


class TaskManager:
    """单一工作线程执行请求，队列读写均受 Lock 保护。"""

    def __init__(
        self,
        executor: EnrollmentExecutor,
        limiter: RateLimiter,
        *,
        clock=time.monotonic,
    ) -> None:
        self._executor = executor
        self._limiter = limiter
        self._clock = clock
        self._items: list[QueueItem] = []
        self._lock = threading.RLock()
        self._resume_event = threading.Event()
        self._resume_event.set()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self.state = TaskState.IDLE
        self.total_attempts = 0
        self.last_error = ""

    def replace_queue(self, courses: list[Course]) -> None:
        with self._lock:
            if self.state in {TaskState.RUNNING, TaskState.PAUSED}:
                raise RuntimeError("任务运行时不能替换队列")
            self._items = [
                QueueItem(course=course, priority=index) for index, course in enumerate(courses)
            ]

    def snapshot(self) -> list[QueueItem]:
        with self._lock:
            return [
                QueueItem(
                    course=item.course,
                    priority=item.priority,
                    status=item.status,
                    attempts=item.attempts,
                    last_result=item.last_result,
                    last_attempt_at=item.last_attempt_at,
                )
                for item in self._items
            ]

    def start(
        self,
        semester: Semester,
        strategy: EnrollmentStrategy,
        *,
        dry_run: bool = False,
    ) -> None:
        with self._lock:
            if self.state in {TaskState.RUNNING, TaskState.PAUSED}:
                raise RuntimeError("任务已在运行")
            if not any(item.status == "waiting" for item in self._items):
                self.state = TaskState.COMPLETED
                return
            self._stop_event.clear()
            self._resume_event.set()
            self.state = TaskState.WAITING
            self._thread = threading.Thread(
                target=self._run,
                args=(semester, strategy, dry_run),
                name="tis-enrollment-worker",
                daemon=False,
            )
            self._thread.start()

    def pause(self) -> None:
        with self._lock:
            if self.state == TaskState.RUNNING:
                self.state = TaskState.PAUSED
                self._resume_event.clear()

    def resume(self) -> None:
        with self._lock:
            if self.state == TaskState.PAUSED:
                self.state = TaskState.WAITING
                self._resume_event.set()

    def stop(self) -> None:
        with self._lock:
            self._stop_event.set()
            self._resume_event.set()
            if self.state in {TaskState.RUNNING, TaskState.PAUSED, TaskState.WAITING}:
                self.state = TaskState.STOPPED

    def join(self, timeout: float | None = None) -> None:
        thread = self._thread
        if thread is not None:
            thread.join(timeout)

    def process_next(
        self,
        semester: Semester,
        strategy: EnrollmentStrategy,
        *,
        dry_run: bool,
    ) -> int:
        """执行一轮，用于工作线程和完全确定性的单元测试。"""

        with self._lock:
            candidates = strategy.select(self._items)
        processed = 0
        for item in candidates:
            if self._stop_event.is_set():
                break
            self._resume_event.wait()
            if self._stop_event.is_set():
                break
            self._attempt_item(semester, item, dry_run=dry_run)
            processed += 1
        return processed

    def _run(
        self, semester: Semester, strategy: EnrollmentStrategy, dry_run: bool
    ) -> None:
        try:
            while not self._stop_event.is_set():
                with self._lock:
                    if not any(item.status == "waiting" for item in self._items):
                        self.state = TaskState.COMPLETED
                        return
                    self.state = TaskState.RUNNING
                if self.process_next(semester, strategy, dry_run=dry_run) == 0:
                    return
        except Exception as error:  # 线程边界：状态必须反馈给调用方
            with self._lock:
                self.last_error = str(error)
                self.state = TaskState.FAILED

    def _attempt_item(
        self, semester: Semester, item: QueueItem, *, dry_run: bool
    ) -> None:
        self._limiter.acquire()
        with self._lock:
            if item.status != "waiting":
                return
            item.status = "trying"
            item.attempts += 1
            self.total_attempts += 1
            item.last_attempt_at = self._clock()
        try:
            result = self._executor.attempt(semester, item.course, dry_run=dry_run)
        except SUSTechToolsError as error:
            self._limiter.record_error()
            with self._lock:
                item.status = "waiting"
                item.last_result = error.code
            raise
        except Exception:
            self._limiter.record_error()
            with self._lock:
                item.status = "waiting"
                item.last_result = "UNKNOWN_ERROR"
            raise
        else:
            self._limiter.record_success()
            with self._lock:
                item.status = result.status
                item.last_result = result.message
                if result.status not in FINAL_COURSE_STATES and result.status != "waiting":
                    item.status = "failed"
