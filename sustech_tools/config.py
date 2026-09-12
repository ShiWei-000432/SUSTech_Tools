"""不含认证信息的运行配置。"""

from dataclasses import dataclass


CAS_LOGIN_URL = (
    "https://cas.sustech.edu.cn/cas/login"
    "?service=https%3A%2F%2Ftis.sustech.edu.cn%2Fcas"
)
TIS_BASE_URL = "https://tis.sustech.edu.cn"
CURRENT_SEMESTER_PATH = "/Xsxk/queryXkdqXnxq"
COURSE_QUERY_PATH = "/Xsxk/queryKxrw"
ENROLLMENT_PATH = "/Xsxk/addGouwuche"

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "X-Requested-With": "XMLHttpRequest",
}


@dataclass(frozen=True)
class ClientConfig:
    """HTTP 安全默认值；密码、Cookie 与 Token 不可放入该配置。"""

    timeout_seconds: float = 8.0
    verify_tls: bool = True
