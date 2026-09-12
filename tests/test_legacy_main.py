"""完全离线的 main.py 回归测试。

这些测试在导入 main.py 前注入 requests、colorama 与 urllib3 的轻量替身，
因此即使测试机没有安装项目依赖，也不会执行任何真实网络请求。
它们锁定当前的请求端点、表单字段和队列语义，供后续服务层抽离比对。
"""

from __future__ import annotations

import builtins
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MAIN_PATH = PROJECT_ROOT / "main.py"


class FakeResponse:
    def __init__(self, text="", status_code=200, headers=None):
        self.text = text
        self.status_code = status_code
        self.headers = headers or {}


class FakeSession:
    def __init__(self, requests_module):
        self._requests_module = requests_module
        self.cookies = object()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def get(self, url, **kwargs):
        self._requests_module.session_get_calls.append((url, kwargs))
        return FakeResponse()


class FakeRequests(types.ModuleType):
    """记录请求而不发送网络流量的 requests 替身。"""

    def __init__(self):
        super().__init__("requests")
        self.get_responses = []
        self.post_responses = []
        self.get_calls = []
        self.post_calls = []
        self.session_get_calls = []
        self.cookie_header = "SESSION=mock-session"
        self.cookies = types.SimpleNamespace(
            get_cookie_header=lambda _jar, _request: self.cookie_header
        )
        self.Request = lambda method, url: types.SimpleNamespace(
            prepare=lambda: (method, url)
        )
        self.Session = lambda: FakeSession(self)

    def get(self, url, **kwargs):
        self.get_calls.append((url, kwargs))
        return self.get_responses.pop(0)

    def post(self, url, **kwargs):
        self.post_calls.append((url, kwargs))
        return self.post_responses.pop(0)


def import_legacy_main(fake_requests):
    """用隔离模块名导入 main.py，避免污染测试进程中的真实依赖。"""

    colorama = types.ModuleType("colorama")
    colorama.init = lambda **_kwargs: None

    urllib3 = types.ModuleType("urllib3")
    urllib3_exceptions = types.ModuleType("urllib3.exceptions")

    class InsecureRequestWarning(Warning):
        pass

    urllib3_exceptions.InsecureRequestWarning = InsecureRequestWarning
    urllib3.exceptions = urllib3_exceptions

    injected_modules = {
        "requests": fake_requests,
        "colorama": colorama,
        "urllib3": urllib3,
        "urllib3.exceptions": urllib3_exceptions,
    }
    with patch.dict(sys.modules, injected_modules):
        spec = importlib.util.spec_from_file_location("legacy_main_under_test", MAIN_PATH)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        assert spec.loader is not None
        spec.loader.exec_module(module)
    return module


class LegacyMainRegressionTests(unittest.TestCase):
    def setUp(self):
        self.requests = FakeRequests()
        self.main = import_legacy_main(self.requests)
        self.main.course_list.clear()

    def tearDown(self):
        sys.modules.pop("legacy_main_under_test", None)

    def test_cas_login_collects_cookie_after_redirect(self):
        self.requests.get_responses = [
            FakeResponse('<input name="execution" value="execution-token">')
        ]
        self.requests.post_responses = [
            FakeResponse(status_code=302, headers={"Location": "https://tis.example/cas"})
        ]

        cookie = self.main.cas_login("12345678", "password-not-persisted")

        self.assertEqual(cookie, "SESSION=mock-session")
        self.assertEqual(self.requests.get_calls[0][0], self.main.CAS_LOGIN_URL if hasattr(self.main, "CAS_LOGIN_URL") else "https://cas.sustech.edu.cn/cas/login?service=https%3A%2F%2Ftis.sustech.edu.cn%2Fcas")
        self.assertEqual(self.requests.post_calls[0][0], self.requests.get_calls[0][0])
        self.assertEqual(
            self.requests.post_calls[0][1]["data"],
            {
                "username": "12345678",
                "password": "password-not-persisted",
                "execution": "execution-token",
                "_eventId": "submit",
                "geolocation": "",
            },
        )
        self.assertFalse(self.requests.post_calls[0][1]["allow_redirects"])
        self.assertEqual(
            self.requests.session_get_calls,
            [("https://tis.example/cas", {"headers": self.main.head, "verify": False})],
        )

    def test_cas_login_rejects_response_without_redirect(self):
        self.requests.get_responses = [
            FakeResponse('<input name="execution" value="execution-token">')
        ]
        self.requests.post_responses = [FakeResponse(status_code=200)]

        self.assertEqual(self.main.cas_login("12345678", "wrong-password"), "")
        self.assertEqual(len(self.requests.session_get_calls), 0)

    def test_getinfo_uses_same_semester_cache_without_network(self):
        cached_courses = {"课程 A": ["course-id-a", "kzyxk"]}
        with tempfile.TemporaryDirectory() as temporary_directory:
            with patch.object(self.main, "COURSE_INFO_PATH", os.path.join(temporary_directory, "course.txt")):
                Path(self.main.COURSE_INFO_PATH).write_text(
                    "2026-2027-1\n" + json.dumps(cached_courses, ensure_ascii=False),
                    encoding="utf8",
                )
                result = self.main.getinfo({"p_xnxq": "2026-2027-1"})

        self.assertEqual(result, cached_courses)
        self.assertEqual(self.requests.post_calls, [])

    def test_getinfo_refreshes_expired_cache_with_all_course_categories(self):
        course_payloads = [
            {"kxrwList": {"list": [{"rwmc": f"课程 {index}", "id": f"id-{index}"}]}}
            for index in range(len(self.main.COURSE_TYPE))
        ]
        self.requests.post_responses = [
            FakeResponse(json.dumps(payload, ensure_ascii=False)) for payload in course_payloads
        ]
        semester = {"p_xn": "2026", "p_xq": "1", "p_xnxq": "2026-2027-1"}

        with tempfile.TemporaryDirectory() as temporary_directory:
            with (
                patch.object(
                    self.main,
                    "COURSE_INFO_PATH",
                    os.path.join(temporary_directory, "course.txt"),
                ),
                patch.object(self.main.time, "sleep"),
                patch.object(builtins, "input", return_value="n"),
            ):
                Path(self.main.COURSE_INFO_PATH).write_text(
                    "old-semester\n{}", encoding="utf8"
                )
                result = self.main.getinfo(semester)

        self.assertEqual(len(self.requests.post_calls), len(self.main.COURSE_TYPE))
        self.assertEqual(
            [call[1]["data"]["p_xkfsdm"] for call in self.requests.post_calls],
            list(self.main.COURSE_TYPE),
        )
        self.assertEqual(result["课程 0"], ("id-0", "bxxk"))
        self.assertEqual(result["课程 5"], ("id-5", "jhnxk"))
        for _url, request_kwargs in self.requests.post_calls:
            self.assertEqual(request_kwargs["data"]["p_xn"], "2026")
            self.assertEqual(request_kwargs["data"]["p_xq"], "1")
            self.assertEqual(request_kwargs["data"]["p_xnxq"], "2026-2027-1")
            self.assertEqual(request_kwargs["data"]["pageSize"], 1000)

    def test_priority_submit_uses_head_course_and_removes_it_on_success(self):
        semester = {"p_xn": "2026", "p_xq": "1", "p_xnxq": "2026-2027-1"}
        self.main.course_list.append(["task-1", "kzyxk", "目标课程"])
        self.requests.post_responses = [
            FakeResponse(json.dumps({"message": "选课成功"}, ensure_ascii=False))
        ]

        with patch.object(self.main.time, "sleep"):
            self.main.submit(semester, loop=1)

        self.assertEqual(self.main.course_list, [])
        request_url, request_kwargs = self.requests.post_calls[0]
        self.assertEqual(request_url, "https://tis.sustech.edu.cn/Xsxk/addGouwuche")
        self.assertEqual(
            request_kwargs["data"],
            {
                "p_pylx": 1,
                "p_xktjz": "rwtjzyx",
                "p_xn": "2026",
                "p_xq": "1",
                "p_xnxq": "2026-2027-1",
                "p_xkfsdm": "kzyxk",
                "p_id": "task-1",
                "p_sfxsgwckb": 1,
            },
        )

    def test_sequential_submit_attempts_each_remaining_course_once(self):
        semester = {"p_xn": "2026", "p_xq": "1", "p_xnxq": "2026-2027-1"}
        self.main.course_list.extend(
            [
                ["task-1", "kzyxk", "课程一"],
                ["task-2", "xxxk", "课程二"],
            ]
        )
        self.requests.post_responses = [
            FakeResponse(json.dumps({"message": "课程已满"}, ensure_ascii=False)),
            FakeResponse(json.dumps({"message": "选课成功"}, ensure_ascii=False)),
        ]

        with patch.object(self.main.time, "sleep"):
            self.main.submit_sequential(semester)

        self.assertEqual(self.main.course_list, [])
        self.assertEqual(
            [call[1]["data"]["p_id"] for call in self.requests.post_calls],
            ["task-1", "task-2"],
        )

    def test_source_declares_all_known_tis_endpoints_and_categories(self):
        source = MAIN_PATH.read_text(encoding="utf8")
        self.assertIn("/Xsxk/queryXkdqXnxq", source)
        self.assertIn("/Xsxk/queryKxrw", source)
        self.assertIn("/Xsxk/addGouwuche", source)
        self.assertEqual(
            set(self.main.COURSE_TYPE),
            {"bxxk", "xxxk", "kzyxk", "zynknjxk", "cxxk", "jhnxk"},
        )


if __name__ == "__main__":
    unittest.main()
