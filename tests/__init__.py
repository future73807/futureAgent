# 测试套件默认关闭认证限流，避免跨测试类共享进程级计数器造成误伤；
# 限流行为由 tests.test_rate_limit 单独覆盖。
from config import settings

settings.auth_rate_limit_per_minute = 0
