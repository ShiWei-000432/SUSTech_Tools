"""FastAPI 本地 Web 后端。所有 TIS 请求仍只经核心服务层发出。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from sustech_tools.auth import AuthService
from sustech_tools.course_cache import CourseCache
from sustech_tools.course_service import CourseService
from sustech_tools.exceptions import SUSTechToolsError
from sustech_tools.tis_client import TISClient
from sustech_tools.enrollment_service import EnrollmentService
from sustech_tools.rate_limiter import RateLimiter
from sustech_tools.task_manager import CycleStrategy, PriorityStrategy, TaskManager
from sustech_tools.models import Course, Semester
from sustech_tools.credential_store import KeychainCredentialStore


ROOT = Path(__file__).resolve().parent
TEMPLATES = Jinja2Templates(directory=str(ROOT / "web" / "templates"))


@dataclass
class DashboardState:
    client: TISClient | None = None
    username: str | None = None
    semester: str | None = None
    semester_model: Semester | None = None
    course_count: int = 0
    courses: list[Course] = None
    queue: list[Course] = None
    task_manager: TaskManager | None = None
    dry_run: bool = True
    message: str = ""

    @property
    def cas_status(self) -> str:
        return "已登录" if self.client else "未登录"

    def __post_init__(self) -> None:
        self.courses = self.courses or []
        self.queue = self.queue or []


def create_app() -> FastAPI:
    app = FastAPI(title="TIS 选课助手", docs_url=None, redoc_url=None)
    app.mount("/static", StaticFiles(directory=str(ROOT / "web" / "static")), name="static")
    app.state.dashboard = DashboardState()

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request, q: str = ""):
        state: DashboardState = app.state.dashboard
        query = q.strip().lower()
        visible_courses = [
            course for course in state.courses
            if not query or query in course.name.lower() or query in course.category.lower()
        ][:100]
        task_items = state.task_manager.snapshot() if state.task_manager else []
        return TEMPLATES.TemplateResponse(
            request,
            "index.html",
            {"state": state, "message": state.message, "courses": visible_courses,
             "task_items": task_items, "query": q},
        )

    @app.post("/login")
    def login(username: str = Form(...), password: str = Form(...), remember_password: str = Form("")):
        state: DashboardState = app.state.dashboard
        if state.client:
            state.client.close()
        client = TISClient()
        try:
            AuthService(client).login(username.strip(), password)
            if remember_password == "on":
                KeychainCredentialStore().save_password(username.strip(), password)
            state.client = client
            state.username = username.strip()
            state.message = "CAS 登录成功。密码不会被保存。"
        except SUSTechToolsError as error:
            client.close()
            state.client = None
            state.message = f"登录失败：{error.code}"
        return RedirectResponse("/", status_code=303)

    @app.post("/login/keychain")
    def login_with_keychain(username: str = Form(...)):
        state: DashboardState = app.state.dashboard
        client = TISClient()
        try:
            password = KeychainCredentialStore().get_password(username.strip())
            AuthService(client).login(username.strip(), password)
            state.client = client
            state.username = username.strip()
            state.message = "已使用 macOS Keychain 中保存的密码登录。"
        except SUSTechToolsError as error:
            client.close()
            state.message = f"登录失败：{error.code}"
        return RedirectResponse("/", status_code=303)

    @app.post("/logout")
    def logout():
        state: DashboardState = app.state.dashboard
        if state.client:
            state.client.close()
        app.state.dashboard = DashboardState(message="已退出登录。")
        return RedirectResponse("/", status_code=303)

    @app.post("/dry-run")
    def set_dry_run(enabled: str = Form(...)):
        state: DashboardState = app.state.dashboard
        state.dry_run = enabled == "on"
        state.message = "已启用只读预演。" if state.dry_run else "已关闭只读预演。"
        return RedirectResponse("/", status_code=303)

    @app.post("/courses/refresh")
    def refresh_courses():
        state: DashboardState = app.state.dashboard
        if not state.client:
            state.message = "请先登录 CAS。"
            return RedirectResponse("/", status_code=303)
        try:
            service = CourseService(state.client)
            semester = service.current_semester()
            courses = service.fetch_courses(semester)
            CourseCache(ROOT / "data" / "courses.json").save(semester, courses)
            state.semester = semester.academic_year_term
            state.semester_model = semester
            state.course_count = len(courses)
            state.courses = courses
            state.message = f"课程数据已刷新，共 {len(courses)} 条。"
        except SUSTechToolsError as error:
            state.message = f"课程刷新失败：{error.code}"
        return RedirectResponse("/", status_code=303)

    @app.post("/queue/add")
    def add_queue(task_id: str = Form(...)):
        state: DashboardState = app.state.dashboard
        course = next((item for item in state.courses if item.task_id == task_id), None)
        if not course:
            state.message = "未找到课程任务，请先刷新课程数据。"
        elif any(item.task_id == task_id for item in state.queue):
            state.message = "该课程已在待选队列中。"
        else:
            state.queue.append(course)
            state.message = f"已加入待选队列：{course.name}"
        return RedirectResponse("/", status_code=303)

    @app.post("/queue/remove")
    def remove_queue(task_id: str = Form(...)):
        state: DashboardState = app.state.dashboard
        state.queue = [item for item in state.queue if item.task_id != task_id]
        state.message = "已从待选队列移除。"
        return RedirectResponse("/", status_code=303)

    @app.post("/queue/move")
    def move_queue(task_id: str = Form(...), direction: str = Form(...)):
        state: DashboardState = app.state.dashboard
        position = next((i for i, item in enumerate(state.queue) if item.task_id == task_id), None)
        if position is not None:
            target = position - 1 if direction == "up" else position + 1
            if 0 <= target < len(state.queue):
                state.queue[position], state.queue[target] = state.queue[target], state.queue[position]
        return RedirectResponse("/", status_code=303)

    @app.post("/task/start")
    def start_task(mode: str = Form(...), confirm_live: str = Form("")):
        state: DashboardState = app.state.dashboard
        if not state.client or not state.semester_model:
            state.message = "请先登录并刷新课程数据。"
        elif not state.queue:
            state.message = "待选队列为空。"
        elif not state.dry_run and confirm_live != "RUN":
            state.message = "真实提交需要输入 RUN 确认。"
        else:
            manager = TaskManager(EnrollmentService(state.client), RateLimiter(1.2))
            manager.replace_queue(state.queue)
            manager.start(state.semester_model, PriorityStrategy() if mode == "priority" else CycleStrategy(), dry_run=state.dry_run)
            state.task_manager = manager
            state.message = "任务已启动。" if not state.dry_run else "只读预演任务已启动。"
        return RedirectResponse("/", status_code=303)

    @app.post("/task/control")
    def control_task(action: str = Form(...)):
        state: DashboardState = app.state.dashboard
        if state.task_manager:
            {"pause": state.task_manager.pause, "resume": state.task_manager.resume,
             "stop": state.task_manager.stop}.get(action, lambda: None)()
        return RedirectResponse("/", status_code=303)

    return app


app = create_app()
