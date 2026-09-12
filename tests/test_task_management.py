"""限流器、Dry Run 与任务状态机的完全离线测试。"""

from __future__ import annotations

import importlib
import sys
import types
import unittest
from unittest.mock import patch


def import_task_modules():
    fake_requests = types.ModuleType("requests")

    class RequestException(Exception):
        pass

    class Timeout(RequestException):
        pass

    class SSLError(RequestException):
        pass

    fake_requests.RequestException = RequestException
    fake_requests.Timeout = Timeout
    fake_requests.exceptions = types.SimpleNamespace(SSLError=SSLError)
    fake_requests.Session = lambda: None
    for name in list(sys.modules):
        if name == "sustech_tools" or name.startswith("sustech_tools."):
            sys.modules.pop(name)
    with patch.dict(sys.modules, {"requests": fake_requests}):
        return (
            importlib.import_module("sustech_tools.enrollment_service"),
            importlib.import_module("sustech_tools.models"),
            importlib.import_module("sustech_tools.rate_limiter"),
            importlib.import_module("sustech_tools.task_manager"),
        )


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


class TaskManagementTests(unittest.TestCase):
    def setUp(self):
        (
            self.enrollment_module,
            self.models_module,
            self.rate_limiter_module,
            self.task_module,
        ) = import_task_modules()
        self.semester = self.models_module.Semester("2026", "1", "2026-2027-1")
        self.course_a = self.models_module.Course("id-a", "kzyxk", "课程 A", {})
        self.course_b = self.models_module.Course("id-b", "xxxk", "课程 B", {})

    def test_rate_limiter_serializes_requests_and_backs_off_after_error(self):
        clock = FakeClock()
        limiter = self.rate_limiter_module.RateLimiter(
            1.2, clock=clock, sleep=clock.sleep
        )

        self.assertEqual(limiter.acquire(), 0.0)
        self.assertEqual(limiter.acquire(), 1.2)
        limiter.record_error()
        self.assertEqual(limiter.current_interval, 2.4)
        self.assertEqual(limiter.acquire(), 2.4)
        limiter.record_success()
        self.assertEqual(limiter.current_interval, 1.2)
        self.assertEqual(clock.sleeps, [1.2, 2.4])

    def test_dry_run_never_calls_submission_endpoint(self):
        class Client:
            def __init__(self):
                self.calls = []

            def post_tis_json(self, path, data):
                self.calls.append((path, data))
                return {"message": "不应被调用"}

        client = Client()
        service = self.enrollment_module.EnrollmentService(client)

        result = service.attempt(self.semester, self.course_a, dry_run=True)

        self.assertFalse(result.submitted)
        self.assertEqual(result.status, "skipped")
        self.assertEqual(client.calls, [])

    def test_enrollment_service_preserves_legacy_submission_fields(self):
        class Client:
            def post_tis_json(self, path, data):
                self.path = path
                self.data = data
                return {"message": "选课成功"}

        client = Client()
        result = self.enrollment_module.EnrollmentService(client).attempt(
            self.semester, self.course_a
        )

        self.assertTrue(result.submitted)
        self.assertEqual(result.status, "success")
        self.assertEqual(client.path, "/Xsxk/addGouwuche")
        self.assertEqual(
            client.data,
            {
                "p_pylx": 1,
                "p_xktjz": "rwtjzyx",
                "p_xn": "2026",
                "p_xq": "1",
                "p_xnxq": "2026-2027-1",
                "p_xkfsdm": "kzyxk",
                "p_id": "id-a",
                "p_sfxsgwckb": 1,
            },
        )

    def test_priority_strategy_only_attempts_first_waiting_course(self):
        enrollment_module = self.enrollment_module

        class Executor:
            def __init__(self):
                self.attempted = []

            def attempt(self, _semester, course, *, dry_run):
                self.attempted.append((course.name, dry_run))
                return enrollment_module.EnrollmentResult(
                    "success", "选课成功", True
                )

        executor = Executor()
        clock = FakeClock()
        manager = self.task_module.TaskManager(
            executor,
            self.rate_limiter_module.RateLimiter(clock=clock, sleep=clock.sleep),
            clock=clock,
        )
        manager.replace_queue([self.course_a, self.course_b])

        processed = manager.process_next(
            self.semester, self.task_module.PriorityStrategy(), dry_run=False
        )

        self.assertEqual(processed, 1)
        self.assertEqual(executor.attempted, [("课程 A", False)])
        states = [item.status for item in manager.snapshot()]
        self.assertEqual(states, ["success", "waiting"])

    def test_cycle_strategy_processes_each_course_once_per_round(self):
        enrollment_module = self.enrollment_module

        class Executor:
            def attempt(self, _semester, _course, *, dry_run):
                return enrollment_module.EnrollmentResult(
                    "skipped", "只读预演", False
                )

        clock = FakeClock()
        manager = self.task_module.TaskManager(
            Executor(),
            self.rate_limiter_module.RateLimiter(clock=clock, sleep=clock.sleep),
            clock=clock,
        )
        manager.replace_queue([self.course_a, self.course_b])

        processed = manager.process_next(
            self.semester, self.task_module.CycleStrategy(), dry_run=True
        )

        self.assertEqual(processed, 2)
        self.assertEqual([item.status for item in manager.snapshot()], ["skipped", "skipped"])


if __name__ == "__main__":
    unittest.main()
