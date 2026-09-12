"""统一的 TIS HTTP 客户端。

整个登录周期复用一个 requests.Session。此阶段只抽离传输层，不改变旧脚本的
请求参数；重试、限流和会话失效恢复将在后续阶段集中加入。
"""

from __future__ import annotations

import json
from typing import Any

import requests

from .config import ClientConfig, DEFAULT_HEADERS, TIS_BASE_URL
from .exceptions import (
    InvalidResponseError,
    NetworkError,
    NetworkTimeoutError,
    RateLimitedError,
    SessionExpiredError,
    TisHttpError,
    TlsError,
)


class TISClient:
    def __init__(
        self,
        config: ClientConfig | None = None,
        *,
        session: requests.Session | None = None,
    ) -> None:
        self.config = config or ClientConfig()
        self.session = session or requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)

    def close(self) -> None:
        self.session.close()

    def __enter__(self) -> "TISClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def get(
        self, url: str, *, expected_statuses: set[int] | None = None, **kwargs: Any
    ) -> requests.Response:
        return self._request("GET", url, expected_statuses=expected_statuses, **kwargs)

    def post(
        self, url: str, *, expected_statuses: set[int] | None = None, **kwargs: Any
    ) -> requests.Response:
        return self._request("POST", url, expected_statuses=expected_statuses, **kwargs)

    def post_tis(self, path: str, data: dict[str, Any]) -> requests.Response:
        return self.post(f"{TIS_BASE_URL}{path}", data=data)

    def post_tis_json(self, path: str, data: dict[str, Any]) -> dict[str, Any]:
        return self.json(self.post_tis(path, data))

    def json(self, response: requests.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except (AttributeError, ValueError, json.JSONDecodeError) as error:
            raise InvalidResponseError("TIS 返回内容不是有效 JSON") from error
        if not isinstance(payload, dict):
            raise InvalidResponseError("TIS JSON 响应不是对象")
        return payload

    def _request(
        self,
        method: str,
        url: str,
        *,
        expected_statuses: set[int] | None,
        **kwargs: Any,
    ) -> requests.Response:
        kwargs.setdefault("timeout", self.config.timeout_seconds)
        kwargs.setdefault("verify", self.config.verify_tls)
        try:
            response = self.session.request(method, url, **kwargs)
        except requests.Timeout as error:
            raise NetworkTimeoutError("网络请求超时", cause=error) from error
        except requests.exceptions.SSLError as error:
            raise TlsError("TLS 证书验证失败", cause=error) from error
        except requests.RequestException as error:
            raise NetworkError("网络连接失败", cause=error) from error

        if response.status_code == 429:
            raise RateLimitedError(
                "TIS 请求过于频繁，请稍后再试",
                status_code=response.status_code,
            )
        if response.status_code in {401, 403}:
            raise SessionExpiredError("TIS 登录状态已失效，请重新登录")
        if expected_statuses is not None:
            if response.status_code in expected_statuses:
                return response
        elif 200 <= response.status_code < 300:
            return response
        if expected_statuses is not None or not 200 <= response.status_code < 300:
            raise TisHttpError(
                f"服务器返回 HTTP {response.status_code}",
                status_code=response.status_code,
            )
        return response
