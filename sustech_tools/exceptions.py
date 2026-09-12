"""服务层向 CLI/Web 暴露的可诊断异常。"""

from __future__ import annotations


class SUSTechToolsError(Exception):
    code = "UNKNOWN_ERROR"

    def __init__(self, message: str, *, cause: Exception | None = None):
        super().__init__(message)
        self.cause = cause


class NetworkError(SUSTechToolsError):
    code = "NETWORK_CONNECTION_ERROR"


class NetworkTimeoutError(NetworkError):
    code = "NETWORK_TIMEOUT"


class TlsError(NetworkError):
    code = "TLS_ERROR"


class TisHttpError(SUSTechToolsError):
    code = "TIS_SERVER_ERROR"

    def __init__(self, message: str, *, status_code: int, cause: Exception | None = None):
        super().__init__(message, cause=cause)
        self.status_code = status_code


class RateLimitedError(TisHttpError):
    code = "TIS_RATE_LIMITED"


class InvalidResponseError(SUSTechToolsError):
    code = "TIS_INVALID_RESPONSE"


class AuthenticationError(SUSTechToolsError):
    code = "CAS_USERNAME_PASSWORD_ERROR"


class SessionExpiredError(SUSTechToolsError):
    code = "SESSION_EXPIRED"


class CredentialStoreError(SUSTechToolsError):
    code = "CREDENTIAL_STORE_ERROR"
