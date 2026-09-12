"""核心服务层的离线单元测试，不会访问任何真实网络。"""

from __future__ import annotations

import importlib
import sys
import types
import unittest
from unittest.mock import patch


def import_core_modules():
    """在没有 requests 依赖的测试环境中导入核心包。"""

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
        client_module = importlib.import_module("sustech_tools.tis_client")
        auth_module = importlib.import_module("sustech_tools.auth")
        course_module = importlib.import_module("sustech_tools.course_service")
        models_module = importlib.import_module("sustech_tools.models")
        exceptions_module = importlib.import_module("sustech_tools.exceptions")
        cache_module = importlib.import_module("sustech_tools.course_cache")
    return (
        client_module,
        auth_module,
        course_module,
        models_module,
        exceptions_module,
        cache_module,
    )


class FakeResponse:
    def __init__(self, payload=None, *, status_code=200, text="", headers=None):
        self._payload = payload
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class FakeSession:
    def __init__(self, responses):
        self.headers = {}
        self.responses = list(responses)
        self.calls = []
        self.closed = False

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.responses.pop(0)

    def close(self):
        self.closed = True


class CoreServiceTests(unittest.TestCase):
    def setUp(self):
        (
            self.client_module,
            self.auth_module,
            self.course_module,
            self.models_module,
            self.exceptions_module,
            self.cache_module,
        ) = import_core_modules()

    def test_tis_client_applies_safe_tls_and_timeout_defaults(self):
        session = FakeSession([FakeResponse({"ok": True})])
        client = self.client_module.TISClient(session=session)

        payload = client.post_tis_json("/test", {"value": 1})

        self.assertEqual(payload, {"ok": True})
        method, url, kwargs = session.calls[0]
        self.assertEqual((method, url), ("POST", "https://tis.sustech.edu.cn/test"))
        self.assertEqual(kwargs["timeout"], 8.0)
        self.assertTrue(kwargs["verify"])
        self.assertEqual(kwargs["data"], {"value": 1})

    def test_tis_client_rejects_non_success_http_status(self):
        session = FakeSession([FakeResponse(status_code=429)])
        client = self.client_module.TISClient(session=session)

        with self.assertRaises(self.exceptions_module.TisHttpError) as raised:
            client.post_tis("/test", {})

        self.assertEqual(raised.exception.status_code, 429)

    def test_tis_client_accepts_explicit_cas_redirect_status(self):
        session = FakeSession([FakeResponse(status_code=302)])
        client = self.client_module.TISClient(session=session)

        response = client.post(
            "https://cas.sustech.edu.cn/cas/login",
            allow_redirects=False,
            expected_statuses={200, 302, 303},
        )

        self.assertEqual(response.status_code, 302)

    def test_tis_client_marks_unauthorized_response_as_session_expired(self):
        session = FakeSession([FakeResponse(status_code=401)])
        client = self.client_module.TISClient(session=session)

        with self.assertRaises(self.exceptions_module.SessionExpiredError):
            client.post_tis("/test", {})

    def test_auth_service_uses_one_client_for_cas_redirect(self):
        class Client:
            def __init__(self):
                self.get_calls = []
                self.post_calls = []

            def get(self, url):
                self.get_calls.append(url)
                if len(self.get_calls) == 1:
                    return FakeResponse(text='<input name="execution" value="token">')
                return FakeResponse()

            def post(self, url, **kwargs):
                self.post_calls.append((url, kwargs))
                return FakeResponse(headers={"Location": "https://tis.sustech.edu.cn/cas"})

        client = Client()
        self.auth_module.AuthService(client).login("12345678", "secret")

        self.assertEqual(len(client.get_calls), 2)
        self.assertEqual(client.get_calls[1], "https://tis.sustech.edu.cn/cas")
        self.assertEqual(client.post_calls[0][1]["data"]["execution"], "token")
        self.assertFalse(client.post_calls[0][1]["allow_redirects"])

    def test_course_service_preserves_query_parameters_and_categories(self):
        course_module = self.course_module

        class Client:
            def __init__(self):
                self.calls = []

            def post_tis_json(self, path, data):
                self.calls.append((path, data))
                if path == course_module.CURRENT_SEMESTER_PATH:
                    return {"p_xn": "2026", "p_xq": "1", "p_xnxq": "2026-2027-1"}
                category = data["p_xkfsdm"]
                return {"kxrwList": {"list": [{"id": category, "rwmc": f"课程-{category}"}]}}

        client = Client()
        sleeps = []
        service = self.course_module.CourseService(client, sleep=sleeps.append)

        semester = service.current_semester()
        courses = service.fetch_courses(semester)

        self.assertEqual(semester.academic_year_term, "2026-2027-1")
        self.assertEqual(len(courses), len(self.course_module.COURSE_TYPES))
        self.assertEqual(sleeps, [3.0] * len(self.course_module.COURSE_TYPES))
        category_calls = client.calls[1:]
        self.assertEqual(
            [data["p_xkfsdm"] for _path, data in category_calls],
            list(self.course_module.COURSE_TYPES),
        )
        self.assertTrue(all(path == self.course_module.COURSE_QUERY_PATH for path, _data in category_calls))
        self.assertEqual(
            self.course_module.CourseService.legacy_index(courses)["课程-bxxk"],
            ("bxxk", "bxxk"),
        )

    def test_invalid_course_payload_becomes_domain_error(self):
        with self.assertRaises(self.exceptions_module.InvalidResponseError):
            self.course_module.CourseService._courses_from_payload(
                {"kxrwList": {"list": "not-a-list"}}, "bxxk"
            )

    def test_course_cache_round_trip_and_invalidates_on_semester_change(self):
        import tempfile
        from pathlib import Path

        semester = self.models_module.Semester("2026", "1", "2026-2027-1")
        course = self.models_module.Course("id-1", "kzyxk", "课程", {"id": "id-1"})
        with tempfile.TemporaryDirectory() as temporary_directory:
            cache = self.cache_module.CourseCache(Path(temporary_directory) / "courses.json")
            cache.save(semester, [course])
            self.assertEqual(cache.load(semester), [course])
            self.assertIsNone(
                cache.load(self.models_module.Semester("2026", "2", "2026-2027-2"))
            )

    def test_legacy_course_cache_is_read_without_rewriting_it(self):
        import json
        import tempfile
        from pathlib import Path

        semester = self.models_module.Semester("2026", "1", "2026-2027-1")
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "course.txt"
            path.write_text(
                "2026-2027-1\n"
                + json.dumps({"课程": ["id-1", "kzyxk"]}, ensure_ascii=False),
                encoding="utf-8",
            )
            courses = self.cache_module.CourseCache.load_legacy(path, semester)

        self.assertEqual(courses[0].name, "课程")
        self.assertEqual(courses[0].as_legacy_value(), ("id-1", "kzyxk"))


if __name__ == "__main__":
    unittest.main()
