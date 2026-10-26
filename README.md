# ShortLink Pro —— 可运行的全栈短链接服务（面试演示项目）

一个单文件夹、零外部依赖即可跑通的短链接全栈服务：**FastAPI(全异步) + SQLAlchemy 2.0 async + 可选 Redis + WebSocket 实时推送 + 手写 JWT/雪花ID/令牌桶 + 批量写 worker + pytest 全覆盖**。

它的定位不是"玩具 CRUD"，而是把系统设计题（短链接服务）真正落地成可讲解、可测试、可部署的工程代码——每个模块都对应一个高频面试考点。

## 快速开始

```bash
cd shortlink-pro
python -m venv .venv && .venv\Scripts\activate     # Windows；Linux/macOS 用 source .venv/bin/activate
pip install -r requirements.txt

python -m pytest                                    # 跑全部测试（无需任何外部服务）
python -m uvicorn app.main:app --port 8000          # 启动服务
# 浏览器打开 http://127.0.0.1:8000            前端控制台
#             http://127.0.0.1:8000/docs      自动生成的 OpenAPI 文档

python scripts/demo.py                              # 并发压测演示（另开终端）
```

Redis 不是必需品：`SL_REDIS_URL` 留空时，缓存/限流/分布式锁自动降级为内存实现；填上即切换 Redis 后端（`docker compose up` 一步拉起 app + Redis）。

## 架构

```
                     +--------------------------------- ASGI 事件循环（单线程协程）--------------------------------+
浏览器 ── HTTP ──>  RequestContext 中间件（request_id/访问日志/指标）                                             |
  |                  RateLimit 中间件（令牌桶，IP 维度）                                                          |
  |                        |                                                                                    |
  |                  FastAPI 路由  /api/auth/*   /api/links/*   /{code}(302)   /ws/links/{code}   /health /metrics |
  |                        |                        |                |                                           |
  +── WebSocket ─────>  ConnectionManager   LinkService（业务）     analytics.record()  put_nowait 入队          |
  |      (实时点击流)        ^  广播点击                |                                  |                          |
  |                        |                    cache-aside                   asyncio.Queue                       |
  |                  JWT 鉴权                 MemoryCache/Redis     _consume 消费者 <---- _flush_loop 定时器            |
  |                                          (策略模式切换)                | 批量 executemany + 计数 UPDATE               |
  |                        |                        |                SQLAlchemy async engine                     |
  +──────────────>  static/index.html 控制台   SQLite/aiosqlite（生产换 Postgres）                                  |
                     +---------------------------------------------------------------------------------------------+
```

## 功能清单（全部可现场演示）

| 功能 | 入口 | 一句话讲点 |
|---|---|---|
| 注册/登录/鉴权 | `/api/auth/*` | PBKDF2+盐+常数时间比较；手写 HS256 JWT（含 alg 混淆防御）；登录失败文案统一防用户名枚举 |
| 短链生成 | `POST /api/links` | 雪花 ID + Base62；自定义别名走分布式锁/唯一索引双保险 |
| 302 跳转 | `GET /{code}` | 热路径只有"查缓存+入队"两次内存操作；负缓存防穿透；302 而非 301 的原因 |
| 点击统计 | `GET /api/links/{code}/stats` | 生产者-消费者 + 批量落库；计数 = 落库 + 缓冲区实时值 |
| 实时推送 | `/ws/links/{code}` | 房间制 WebSocket，仅链接主人可订阅 |
| 限流 | 全局中间件 | 令牌桶；Redis Lua 原子版/内存版策略切换 |
| 可观测 | `/health` `/metrics` | Prometheus 文本格式 + X-Request-ID 全链路贯穿 |
| 前端 | `/` | 单文件控制台：登录、生成、复制、删除、实时监听 |
| 压测演示 | `scripts/demo.py` | asyncio.gather + Semaphore 并发创建/跳转 |

## 目录结构

```
shortlink-pro/
├── app/
│   ├── main.py            # 应用工厂 + lifespan（启动/优雅停机编排）
│   ├── config.py          # pydantic-settings 集中配置（SL_ 前缀环境变量）
│   ├── database.py        # async engine/session（按 Settings 构建，测试友好）
│   ├── models.py          # SQLAlchemy 2.0 Mapped 风格 ORM
│   ├── schemas.py         # Pydantic v2 请求/响应模型（校验即文档）
│   ├── middleware.py      # 手写纯 ASGI 中间件：请求上下文 + 令牌桶限流
│   ├── dependencies.py    # Depends 依赖注入（会话/当前用户）
│   ├── ws.py              # WebSocket 房间管理 + 订阅鉴权
│   ├── core/              # 可复用底层能力（与业务无关）
│   │   ├── security.py    #   PBKDF2 密码 + 手写 HS256 JWT
│   │   ├── snowflake.py   #   雪花 ID（时钟回拨处理）+ Base62
│   │   ├── cache.py       #   缓存：Redis / TTL-LRU 内存（策略模式+工厂+降级）
│   │   ├── ratelimit.py   #   令牌桶：内存 / Redis Lua 原子版
│   │   ├── lock.py        #   分布式锁：SET NX EX + Lua 释放 / asyncio 降级
│   │   ├── metrics.py     #   计数器 + Prometheus 文本渲染
│   │   └── logging_conf.py#   request_id ContextVar + JSON 结构化日志
│   ├── services/          # 业务层
│   │   ├── link_service.py#   创建/解析(cache-aside)/统计/删除
│   │   └── analytics.py   #   点击埋点：队列 + 消费者 + 定时批写
│   └── routers/           # auth / links / system 三组路由
├── static/index.html      # 前端控制台（原生 JS，零构建）
├── tests/                 # pytest + httpx ASGITransport（进程内全栈测试）
├── scripts/demo.py        # 并发压测演示
├── Dockerfile / docker-compose.yml
└── .env.example           # 全部可调参数说明
```

## 面试讲点映射（项目证据 -> 高频问题）

| 面试官问 | 你打开哪个文件讲 |
|---|---|
| asyncio 适合什么场景？事件循环原理？ | `main.py` lifespan + `scripts/demo.py` 压测输出 |
| 生产者消费者怎么写？ | `services/analytics.py`（队列+消费者+定时器+优雅停机） |
| 缓存穿透/击穿/雪崩怎么防？ | `services/link_service.py`（负缓存哨兵/TTL/删除失效） |
| 分布式锁要注意什么？ | `core/lock.py`（唯一 token/Lua 原子释放/TTL 兜底） |
| 限流算法选型？ | `core/ratelimit.py`（令牌桶 + Lua 原子化 + 临界突刺讨论） |
| JWT 结构？怎么防伪造？ | `core/security.py`（三段式/签名/alg 混淆/exp） |
| 密码怎么存？ | `core/security.py`（PBKDF2/盐/常数时间比较） |
| 分布式 ID 怎么生成？ | `core/snowflake.py`（位布局/时钟回拨/为什么不用 UUID） |
| 日志怎么做链路追踪？ | `core/logging_conf.py` + `middleware.py`（ContextVar） |
| 说说设计模式的使用 | 缓存/限流/锁三处策略模式 + 工厂 + Settings 单例 + FastAPI DI |
| 单测怎么不依赖外部服务？ | `tests/conftest.py`（ASGITransport + 独立 SQLite + lifespan） |
| 服务怎么优雅停机？ | `main.py`（停任务 -> flush 缓冲 -> 关连接池） |
| 中间件原理？ | `middleware.py`（纯 ASGI 实现，讲 scope/receive/send） |
| 接口被刷怎么办？ | 限流中间件 + `tests/test_ratelimit.py`（429+Retry-After） |
| 资源权限怎么设计？ | `link_service.get_owned`（他人资源 404 不泄露存在性） |

## 关键设计取舍（主动讲出来 = 加分）

1. **跳转热路径不做同步 DB 写**：点击先入内存队列，两个后台任务批量落库。代价是统计有"秒级"延迟，收益是重定向与 DB 写 QPS 彻底解耦——用 `click_queue_depth`、`clicks_flushed_total` 指标可观测。
2. **短码 = Base62(雪花 ID)，11~12 位**：全局唯一免查库、趋势递增对索引友好；代价是码位比 bit.ly 的 7 位长。更短方案（号段预取、7 位哈希+冲突重试）在面试时口头展开。
3. **Redis 全部"可选"**：三个后端接口（cache/limiter/lock）都有内存实现，启动时探测降级。这是"零依赖可演示"与"生产可扩展"的平衡；生产把 `SL_REDIS_URL` 指向 Redis 即可，代码零改动。
4. **SQLite 默认，Postgres 就绪**：连接串换 `postgresql+asyncpg://` 即可；demo 用 `create_all`，生产强调必须上 Alembic。
5. **他人资源返回 404 而不是 403**：不向探测者泄露资源存在性。
6. **限流按 IP 而非按用户**：网关层语义；`X-Forwarded-For` 只在可信代理后启用（代码中有注释说明信任边界）。

## 生产化路线（面试官追问"上生产还差什么"时答这套）

- 数据库：PostgreSQL + Alembic 迁移 + 读写分离；点击事件量大可先入 Kafka 再落 ClickHouse
- 多实例：gunicorn -k uvicorn.workers.UvicornWorker 多 worker + Nginx 反代 + Redis 强制启用（内存限流器/锁不跨进程）
- 缓存加固：热点短链逻辑过期 + 互斥重建，防击穿；淘汰策略 allkeys-lru
- 安全：HTTPS、rate limit 接 Redis 滑动窗口、JWT 缩短有效期 + refresh token、审计日志
- 可观测：prometheus-client 直方图（P99）、OpenTelemetry 分布式追踪、Sentry 告警
- CI/CD：ruff + mypy + pytest 门禁、多阶段 Docker 构建、金丝雀发布

## 运行测试

```bash
python -m pytest -v            # 40+ 用例：安全原语/鉴权/短链全流程/限流/WebSocket
```

覆盖要点：JWT 篡改与过期拒绝、alg=none 伪造拒绝、雪花 ID 四线程无重复、Base62 往返、
注册冲突 409、错误口令 401 文案一致、创建->跳转->计数->统计全链路、负缓存命中指标、
过期 410、删除后缓存失效、跨用户 404、限流 429+Retry-After、WebSocket 推送/鉴权/越权关闭。
