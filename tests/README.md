# 回归测试

当前测试完全使用标准库 unittest 和本地 requests 替身，不会发出 CAS、TIS 或选课网络请求。

运行：

    python3 -m unittest discover -s tests -v

测试锁定当前 main.py 的 CAS 表单、Cookie 收集、课程缓存、六类课程查询、两种选课策略及提交参数。后续抽离服务层时，应先保持这些测试通过；对于现有已识别缺陷，应新增预期更安全的测试后再改变行为。
