"""SUSTech TIS 选课助手的核心服务层。

该包不包含 Web 路由或终端交互；认证、网络与课程逻辑由此处统一提供。
"""

from .auth import AuthService
from .course_service import CourseService
from .tis_client import TISClient

__all__ = ["AuthService", "CourseService", "TISClient"]
