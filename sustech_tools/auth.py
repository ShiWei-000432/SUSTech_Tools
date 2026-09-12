"""CAS 认证服务；密码只作为函数参数短暂存在于当前进程。"""

from __future__ import annotations

import re

from .config import CAS_LOGIN_URL
from .exceptions import AuthenticationError
from .tis_client import TISClient


_EXECUTION_PATTERN = re.compile(r'name="execution"\s+value="([^"]+)"')


class AuthService:
    def __init__(self, client: TISClient) -> None:
        self.client = client

    def login(self, username: str, password: str) -> None:
        page = self.client.get(CAS_LOGIN_URL)
        execution = self._execution_token(page.text)
        response = self.client.post(
            CAS_LOGIN_URL,
            data={
                "username": username,
                "password": password,
                "execution": execution,
                "_eventId": "submit",
                "geolocation": "",
            },
            allow_redirects=False,
            # CAS 成功登录应返回到 TIS 的 302/303；密码错误通常仍返回 200 登录页。
            expected_statuses={200, 302, 303},
        )
        location = response.headers.get("Location")
        if not location:
            raise AuthenticationError("CAS 登录失败，请检查学号或密码")
        self.client.get(location)

    @staticmethod
    def _execution_token(html: str) -> str:
        match = _EXECUTION_PATTERN.search(html)
        if not match:
            raise AuthenticationError("CAS 登录页面结构发生变化，未找到 execution 字段")
        return match.group(1)
