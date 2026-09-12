# SUSTech_Tools 代码审计（Phase 0–1）

审计日期：2026-09-12
审计范围：本地工作区 /Users/mac/Doubao/chats/2026-09-12/new-chat/SUSTech_Tools。本报告仅基于静态审阅和语法检查，没有使用真实 CAS 凭据或向 TIS 发出请求。

## 实施进度（更新于 2026-09-12）

Phase 2 已完成：新增 7 项旧程序回归测试和 5 项核心服务层测试，全部通过；测试用本地 requests 替身运行，不产生网络请求或真实选课提交。

Phase 3 已开始：已新增 TISClient、AuthService、CourseService、领域模型和异常类型。TISClient 默认启用 TLS 验证并设置 8 秒 timeout，认证后在同一 requests.Session 内继续访问 TIS。为避免在同一改动中改变已部署 CLI 的行为，main.py 当前仍是原实现；cli.py 暂作为兼容入口转发至 main.py。下一小步应让 CLI 的只读登录、学期与课程查询逐步切换到服务层，然后再迁移选课调度。

Phase 4 已完成核心实现：EnrollmentService 保留旧选课表单字段，并在服务端阻止 Dry Run 提交；TaskManager 使用单一可 join 工作线程、Lock、Event 和状态机管理队列；RateLimiter 用单调时钟全局串行化请求，并在连续错误时指数退避。20 项完全 mock 的测试覆盖旧行为、新客户端、缓存、任务状态机、Dry Run、限流、HTTP 429/401 和脱敏日志。

Phase 5 已完成基础设施：TISClient 识别 429 与 401/403；日志使用 RotatingFileHandler 并在写入前脱敏 password、Cookie、token；课程缓存使用带版本、学期、抓取时间与课程数量的 JSON，并使用临时文件原子替换。旧 main.py 仍保留作为兼容基线，尚未使用这些安全默认值；后续 CLI 迁移完成后将移除旧明文密码和 verify=False 路径。

CLI 迁移已完成第一版：python3 cli.py 使用 TISClient、AuthService、CourseService、CourseCache、EnrollmentService、TaskManager 和 RateLimiter；密码仅经 getpass 输入并留在进程内存，默认 Dry Run，真实提交需要输入 RUN 二次确认。它以 utf-8-sig 读取 class.txt，并兼容只读导入旧两行 course.txt，随后使用 data/courses.json 保存结构化缓存。main.py 尚未删除，继续作为已部署旧版本的回退入口。

Phase 6–7 已完成第一版：Dry Run 在 EnrollmentService 内部阻止提交；新增 app.py、web_server.py 和 Jinja2 Dashboard，默认只绑定 127.0.0.1:8000 并在启动时打开浏览器。Web 路由仅调用 AuthService、CourseService 与 CourseCache，不包含 CAS 协议、Cookie 解析或 TIS 参数拼装。requirements.txt 已声明 FastAPI、Uvicorn、Jinja2、python-multipart 与 requests。当前开发环境没有安装这些依赖，因此已运行 Python 语法检查和 22 项离线测试，但尚未实际启动 Web 服务；安装依赖后必须进行本地页面 smoke test。

## 基线

开始时工作区干净，位于 master，HEAD 为 62fda9c（Fix TIS login cookies and initial course query pacing）。已创建 backup/pre-web-ui-20260912 保存原始基线，并创建 feature/web-ui。没有覆盖本地文件，也没有 fetch、merge 或 reset 远端仓库。

当前版本是单文件交互式 CLI：配置、认证、HTTP、缓存、课程匹配、选课循环和线程控制都集中于 main.py。已跟踪文件只有 main.py、README.md、class.txt、LICENSE 和两张图片。审计时没有 course.txt 或 user.txt；这两条路径按源代码分析，未以本地样本验证。python3 -m py_compile main.py 已通过，但不证明当前 CAS/TIS 接口可用。README 明示 2026 年 9 月 TIS 接口可能已变化。

## 当前架构与完整程序流程

main.py 集中实现常量、文件读取、CAS 登录、Cookie、当前学期查询、课程缓存与查询、选课提交、线程和终端交互。没有模块边界。

1. 初始化 colorama，读取 class.txt；没有文件时终端逐行录入。
2. 如果 user.txt 存在，取前两行作为学号和 CAS 密码自动登录；失败后循环提示输入。
3. 成功登录返回 Cookie 字符串，写入全局可变 head[cookie]。
4. POST /Xsxk/queryXkdqXnxq，提交 mxpylx=1，读取 p_xn、p_xq、p_xnxq。
5. 读取或下载本学期课程任务；以课程任务名精确匹配 class.txt，匹配成功项目加入全局 course_list。
6. 用户选择模式 1、模式 2 或退出。每次按回车都创建底层线程，线程向 /Xsxk/addGouwuche 提交，并按响应文本更新队列。

## CAS、Cookie 与 Session

cas_login 先 GET 固定 CAS service URL，用字符串分割 HTML 提取 execution；随后 POST username、password、execution、_eventId=submit、geolocation，并设置 allow_redirects=False。响应只要带 Location 就判定成功；否则一律报告用户名或密码错误。所谓重试循环在一次 POST 后立即 break，并不是真正重试。HTML 字段变化会造成 IndexError，且没有检查重定向目标、CAS 错误页或业务错误类型。

CAS POST 后，代码临时创建 requests.Session，GET Location 跟随重定向并收集 Cookie，然后为 TIS 请求生成 Cookie 头字符串。临时 Session 随即关闭；后续所有 TIS 请求使用模块级 requests.post，只手工携带静态 Cookie。这样无法连接复用、吸收后续 Set-Cookie 或集中管理会话状态。没有 Cookie 到期检测，也未处理登录页、302、401、403 或业务层 Session 失效，更不会安全暂停任务。

## 当前学期、课程、class.txt 与 course.txt

当前学期请求为 POST /Xsxk/queryXkdqXnxq，mxpylx=1。代码直接 loads(response.text) 后索引学期字段。

getinfo 优先读取 course.txt：第一行必须等于 p_xnxq，第二行必须为完整 JSON。未命中时按 bxxk、xxxk、kzyxk、zynknjxk、cxxk、jhnxk 依次 POST /Xsxk/queryKxrw。每类查询前固定等待 3 秒；请求保留学期字段、p_pylx=1、mxpylx=1、pageNum=1、pageSize=1000 和课程类别，只读取 kxrwList.list 中的 rwmc、id。

class.txt 按行保存待选课程名称，顺序即优先级。当前样本为 UTF-8 with BOM，首行只含 BOM；代码用 utf8 而非 utf-8-sig，这使 README 中首行留空成为脆弱的兼容约定。第一门真实课程若处于 BOM 行可能无法匹配。

course.txt 没有版本、抓取时间、TTL、课程数或原子写入，仅以学期判断，学期内课表变化不会自动失效；同名 rwmc 会静默覆盖。user.txt 的第一行是学号、第二行是明文 CAS 密码。虽本地不存在该文件，不安全分支仍存在。

## 选课请求与两种模式

两种模式都 POST /Xsxk/addGouwuche，提交 p_pylx=1、p_xktjz=rwtjzyx、当前学期字段、p_xkfsdm、p_id、p_sfxsgwckb=1。后续重构必须保持这些字段和值的当前形状，直到 mock 回归和只读诊断确认接口差异；不能猜测端点含义而改变提交语义。

模式 1 的 submit 每个线程最多尝试三次，始终取队首课程。模式 2 的 submit_sequential 先复制队列，再逐项尝试副本中仍存在的课程；它只运行一轮，循环来自用户反复按回车。两者均以响应包含成功判定成功；响应包含冲突、已选、已满时移除课程。非 JSON、缺少 message、并发修改队列都可能导致崩溃或错误结果。

## 线程、限流与异常处理

程序使用 _thread.start_new_thread，无 Thread 对象、join、停止事件、锁、任务状态、异常回传或并发上限。提示允许多按同时喵多次。多个线程同时读取并 pop/remove 全局 course_list，存在重复提交、IndexError、错误删除和违反服务端限流的竞争条件。

TIMEOUT=1.2 只是每条线程内部的 sleep，不是全局限流器。N 个线程可使总提交间隔缩短到约 1.2/N 秒，也可能同时发送请求。课程类别查询前的 3 秒不作用于 CAS、学期和选课。没有统一限流、429 识别、退避或连续错误熔断。

只有 CAS 初始 GET、用户文件读取、缓存读取和线程创建有宽泛异常捕获。没有默认 timeout、HTTP 状态检查、JSON/字段保护、DNS/连接/TLS 分类、有限重试或 Session 失效处理。所有 CAS/TIS 请求都使用 verify=False，并且抑制 InsecureRequestWarning。

## 风险清单

| 优先级 | 问题 | 影响 |
| --- | --- | --- |
| P0 | verify=False 与告警抑制 | TLS 错误和中间人攻击风险被掩盖。 |
| P0 | 明文 user.txt | CAS 密码落盘，权限、清理、泄露均未控制。 |
| P0 | 无 timeout | 半开连接可无限阻塞。 |
| P0 | _thread 与裸队列 | 无界并发和 course_list 数据竞争，可重复提交或超过限流。 |
| P0 | os._exit | 正常退出直接杀进程，不执行清理、日志刷新或资源释放。 |
| P0 | README 已提示接口过时 | 没有诊断或只读预演，接口变化容易直接崩溃。 |
| P1 | Session 被立即丢弃 | Cookie 不会更新，无法统一验证登录状态。 |
| P1 | HTTP/JSON 未校验 | 429、500、HTML、空响应可能被当 JSON 解析。 |
| P1 | CAS 判定脆弱 | execution 字符串切分和仅检查 Location 容易失效或误报。 |
| P1 | 缓存陈旧/损坏 | 两行缓存无 schema、TTL、原子写入。 |
| P1 | 课程匹配歧义 | 未匹配、同名和班次差异没有明确提示。 |
| P2 | 终端驱动体验 | 回车触发、任意字符跳过和退出不可审计。 |
| P2 | print 无持久化 | 无脱敏日志、实时日志、历史结果或错误码。 |
| P2 | 接口假设散落 | CAS HTML、JSON 路径和中文关键词全硬编码。 |

## 保留基线与重构边界

Phase 2 必须先用 mock 固定：CAS service URL 与表单字段；CAS 跳转后收集 TIS Cookie；当前学期的 mxpylx=1；六个课程类别及查询字段；选课端点与全部提交字段；class.txt 顺序优先级；模式 1 队首优先；模式 2 一轮逐项尝试。

保留指请求兼容性，不包括缺陷。必须重构：直接 HTTP 调用、临时 Session、全局可变请求头、裸 course_list、_thread、os._exit、明文密码、TLS 关闭、无 timeout、无结构化异常和 print 日志。最高风险是 CAS HTML/重定向、Cookie 域路径、TIS 表单字段、课程 JSON 与中文业务消息判断；先以测试包住，再迁移。真实验证应只在用户授权的 Dry Run 下进行。

## 推荐架构与 Web UI 方案

建议保留轻量分层：app.py 为仅绑定 127.0.0.1 的 FastAPI 入口；cli.py 为兼容入口；包内分为 config、models、exceptions、tis_client、auth、course_service、enrollment_service、task_manager、rate_limiter、logging_service；web 只存 Jinja2 模板和少量 HTMX/CSS/JavaScript；data、logs、tests、docs 独立。

TISClient 是唯一 HTTP 组件，在完整登录周期持有一个 requests.Session，默认 verify=True、明确 timeout、固定 headers、CookieJar 和统一响应处理。若学校证书链确有问题，应提供 CA bundle 或明确风险的用户显式选项，不能默认关闭 TLS。Web 路由只调用服务层，不实现 CAS、Cookie、参数拼装或课程提交。

使用 FastAPI + Jinja2 + HTMX + SSE 即可。顶部显示 CAS、TIS、学期、Dry Run；导航为主页、课程、待选队列、运行任务、历史记录、系统诊断、设置。密码仅在进程内存中存在；默认仅记住学号，后续记住密码应显式使用 macOS Keychain。只显示 API 实际返回的课程字段。

任务队列采用 waiting、trying、success、skipped、conflict、already_selected、full、failed。TaskManager 使用单一可 join 工作线程与 Lock/Event 实现开始、暂停、继续、停止；策略层保留模式语义。页面关闭不能让后台任务失控。所有提交经过全局 RateLimiter。

Dry Run 必须在 EnrollmentService 服务端硬性阻止 addGouwuche，不可只依赖前端开关。它可登录、查询、匹配和预演，页面必须明显显示当前为只读预演模式，不会提交选课请求。

## 阶段计划与验证门槛

1. Phase 0：已完成备份分支、状态和日志记录。
2. Phase 1：已完成本审计，不改变 main.py。
3. Phase 2：引入 pytest 与 requests mock，覆盖 CAS、Cookie、学期/课程解析、缓存、状态转换、TaskManager、RateLimiter、timeout、Session 失效、非 JSON；禁止真实提交。
4. Phase 3：抽离 TISClient、AuthService、CourseService，保留 CLI；运行 mock 回归与只读 smoke test。
5. Phase 4：实现 threading.Thread、Event、Lock、状态机和全局限流；验证并发、暂停、停止与 join。
6. Phase 5：处理 TLS、timeout、有限指数退避、异常分类、脱敏轮转日志、仅内存密码和可选 Keychain；验证日志没有密码和 Cookie。
7. Phase 6：实现服务端 Dry Run；测试断言该模式不调用提交端点。
8. Phase 7–8：FastAPI 后端、Dashboard、浅深色主题、HTMX 状态刷新，优先 Dry Run 集成测试。
9. Phase 9–10：课程搜索、旧文件导入、队列排序/跳过与任务控制；测试状态迁移与停止安全。
10. Phase 11：RotatingFileHandler 与 SSE 脱敏实时日志。
11. Phase 12：只读系统诊断，字段缺失显示接口可能变化而非崩溃。
12. Phase 13：可关闭 macOS 通知、非敏感 JSON 历史、可取消定时启动；继续共用限流器。
13. Phase 14：requirements.txt、start.sh、README，验证 start.sh、app.py、cli.py，并说明真实接口未验证项。

每一阶段都先运行与改动匹配的测试。UI 是最后一层；可靠性、请求兼容性、低流量和可诊断错误优先于界面复杂度。
