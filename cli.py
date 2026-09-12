#!/usr/bin/env python3
"""基于新服务层的安全命令行入口。

原 main.py 保留为旧版本兼容基线；本入口不读取或写入 user.txt，密码只在
当前进程内传递给 CAS 登录函数。
"""

from __future__ import annotations

from getpass import getpass
import logging
from pathlib import Path
import time

from sustech_tools.auth import AuthService
from sustech_tools.course_cache import CourseCache
from sustech_tools.course_service import CourseService
from sustech_tools.enrollment_service import EnrollmentService
from sustech_tools.exceptions import SUSTechToolsError
from sustech_tools.logging_service import configure_logging
from sustech_tools.rate_limiter import RateLimiter
from sustech_tools.task_manager import CycleStrategy, PriorityStrategy, TaskManager, TaskState
from sustech_tools.tis_client import TISClient


PROJECT_ROOT = Path(__file__).resolve().parent
CLASS_PATH = PROJECT_ROOT / "class.txt"
LEGACY_COURSE_CACHE_PATH = PROJECT_ROOT / "course.txt"
COURSE_CACHE_PATH = PROJECT_ROOT / "data" / "courses.json"
LOG_PATH = PROJECT_ROOT / "logs" / "app.log"


def load_target_names(path: Path) -> list[str]:
    """读取旧 class.txt，并正确去除 UTF-8 BOM 和空白行。"""

    if not path.is_file():
        raise FileNotFoundError(f"未找到待选课程文件：{path}")
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8-sig").splitlines()
        if line.strip()
    ]


def choose_mode() -> object:
    mode = input("选课模式 [1] 优先级 [2] 循环（默认 1）：").strip() or "1"
    if mode == "1":
        return PriorityStrategy()
    if mode == "2":
        return CycleStrategy()
    raise ValueError("模式只能是 1 或 2")


def choose_dry_run() -> bool:
    choice = input("启用只读预演？不会提交选课请求 [Y/n]：").strip().lower()
    return choice not in {"n", "no"}


def wait_for_task(task_manager: TaskManager) -> None:
    while task_manager.state not in {
        TaskState.COMPLETED,
        TaskState.STOPPED,
        TaskState.FAILED,
    }:
        time.sleep(0.2)
    task_manager.join()


def run() -> int:
    logger = configure_logging(LOG_PATH, level=logging.INFO)
    try:
        target_names = load_target_names(CLASS_PATH)
        if not target_names:
            print("class.txt 中没有可匹配的课程名称。")
            return 1
        username = input("请输入学号：").strip()
        password = getpass("请输入 CAS 密码：")
        if not username or not password:
            print("学号和密码不能为空。")
            return 1

        with TISClient() as client:
            print("正在连接 CAS...")
            AuthService(client).login(username, password)
            print("CAS 登录成功。")
            logger.info("CAS 登录成功，学号=%s", username)

            course_service = CourseService(client)
            semester = course_service.current_semester()
            print(f"当前学期：{semester.academic_year_term}")

            cache = CourseCache(COURSE_CACHE_PATH)
            courses = cache.load(semester)
            if courses is None:
                courses = CourseCache.load_legacy(LEGACY_COURSE_CACHE_PATH, semester)
            if courses is None:
                print("正在从 TIS 获取课程数据...")
                courses = course_service.fetch_courses(semester)
                cache.save(semester, courses)
            print(f"已加载 {len(courses)} 条课程任务。")

            index = CourseService.legacy_index(courses)
            courses_by_name = {course.name: course for course in courses}
            selected_courses = [
                courses_by_name[name] for name in target_names if name in courses_by_name
            ]
            missing = [name for name in target_names if name not in index]
            if missing:
                print("以下课程未找到：" + "、".join(missing))
            if not selected_courses:
                print("没有可执行的目标课程，任务未启动。")
                return 1

            strategy = choose_mode()
            dry_run = choose_dry_run()
            if dry_run:
                print("当前为只读预演模式，不会提交选课请求。")
            else:
                confirmed = input("将提交真实选课请求。输入 RUN 确认：").strip()
                if confirmed != "RUN":
                    print("未确认，任务未启动。")
                    return 0

            manager = TaskManager(
                EnrollmentService(client),
                RateLimiter(min_interval=1.2),
            )
            manager.replace_queue(selected_courses)
            manager.start(semester, strategy, dry_run=dry_run)
            print("任务已启动；按 Ctrl-C 可安全停止。")
            try:
                wait_for_task(manager)
            except KeyboardInterrupt:
                print("\n正在停止任务...")
                manager.stop()
                manager.join()

            for item in manager.snapshot():
                print(
                    f"{item.course.name}: {item.status} "
                    f"(尝试 {item.attempts} 次，{item.last_result})"
                )
            return 0 if manager.state != TaskState.FAILED else 1
    except (SUSTechToolsError, OSError, ValueError) as error:
        logger.error("CLI 失败：%s", error)
        print(f"操作失败：{error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(run())
