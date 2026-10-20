# 八股文智能复习系统 · 项目转接文档

> 交接日期：2026-10-19；更新：2026-10-20（性能验收 / 内容补足 / 补测试 / 前端批量审核 / 错题导出）
> 当前状态：后端 44 个测试全绿；前端 `vue-tsc + vite build` 通过；无头 Edge 全流程冒烟（含批量审核选择、错题导出下载）通过，控制台无错误。
> 本文写给下一位接手的开发者/AI：先看本文，再按“关键文件阅读顺序”读代码。

---

## 1. 一句话状态

项目位于 `D:\Program Files\JetBrains\PythonProject\bajiu-review`，按《八股文智能复习系统_项目文档_V0.4》的 **M1（P0）** 范围实现：FastAPI + SQLite 后端、Vue3 + TS + Vite + Pinia 前端，覆盖题库/知识库/导入/爬虫/统一待审/SM-2 复习/错题收藏/统计/导出备份/登录。无 AI 依赖，本地单用户。

**原前端原型已经迁移进 Vue 应用**，保留原设计语言（青绿主题、侧边栏、卡片、刷题卡、SVG 折线/条形图），并补齐了原型没有的登录、知识库、收藏夹、采集任务、规则打标、备份恢复页面。

**2026-10-20 增量（本次接手完成）**：
- 列表 N+1 消除：题目列表/收藏/错题/复习队列/练习组卷改为批量预加载，500 题分页 100 固定 11 条 SQL、约 36ms（验收线 200ms）。
- 内容补足：`backend/seed/content_m1_supplement.md`（65 题 + 21 知识），已导入并批量审核入库。演示库现为 **99 题、43 知识、9 个活跃导入批次、1 条合并审计**。
- 规则打标：种子规则 20 条，对 20 条样例待审项覆盖 20/20；YAML 加载失败改为记警告日志（此前静默吞掉）。
- 前端待审批量通过 UI（多选 + 全选本页 + 批量通过，逐条报告失败）。
- 错题本 Markdown 导出：`GET /mistakes/export` + 错题本页按钮。
- 爬虫取数稳定性：raw 域名连接池显式绑定 IPv4、socket 层重试、每文件总时限（默认 `5 × timeout_sec`），默认 UA 源在 `interval_sec < 15` 时不再每次等待（自定义 UA 的源行为不变，测试替身不受影响）。
- 新增测试：CSV 导入逐行错误、同文件哈希提示、SimHash 近似重复、待审批量、精确重复审计、SSRF 白名单、登录限流、规则打标覆盖率、500 题性能与查询数、错题导出。
- 本次**未做**：Docker 实跑（按交接要求暂缓）、真实 GitHub 仓库端到端验收（见第 9 节）。

---

## 2. 路径与入口

| 内容 | 路径 |
|---|---|
| 项目根 | `D:\Program Files\JetBrains\PythonProject\bajiu-review` |
| 原始项目文档（工作区根） | `D:\Program Files\JetBrains\PythonProject\八股文智能复习系统_项目文档_V0.4.md` |
| 项目内文档副本 | `bajiu-review\docs\八股文智能复习系统_项目文档_V0.4.md` |
| 后端 | `bajiu-review\backend` |
| 前端 | `bajiu-review\frontend` |
| 演示数据库 | `bajiu-review\backend\data\bajiu.db` |
| 备份目录 | `bajiu-review\backend\data\backups` |
| 演示数据源 | `bajiu-review\backend\seed\demo_seed.json` |
| 规则种子 | `bajiu-review\backend\config\tag_rules.yaml` |
| E2E 冒烟 | `bajiu-review\frontend\e2e\smoke.mjs` |

启动后：
- 本地单端口：`http://127.0.0.1:8000`
- 前端开发模式：`http://127.0.0.1:5173`
- API 文档：`http://127.0.0.1:8000/api/docs`
- 健康检查：`http://127.0.0.1:8000/api/v1/healthz`
- 默认账号：`admin / admin123`

> 写本文时，当前会话在 8000 端口启动了一个 uvicorn 后台进程。新窗口先执行 `netstat -ano | grep ':8000'` 检查；如端口被占用但页面能打开，说明旧进程还在，**不要直接再起一个**（会 `WinError 10048`）。要加载最新后端代码，先结束占用 PID 再启动。

---

## 3. 当前验证结果（2026-10-20 实测）

```text
后端 pytest：44 passed（约 27s）
前端 npm run build：通过（vue-tsc --noEmit + vite build）
前端 npm run e2e：通过，problems: []
500 题性能：分页 100 固定 11 条 SQL、约 36ms（验收线 200ms）
docker compose config：通过（未改；按本次交接要求 Docker 实跑暂缓）
```

E2E 覆盖：登录 → 仪表盘 → 刷题翻答案 → 今日复习 → 题库详情 → 知识库 → 导入 → 采集任务 → 待审队列（8 条，含勾选/全选/取消与批量按钮计数断言）→ 统计 → 设置 → 收藏夹 → 错题本（含 Markdown 导出下载）→ 考前冲刺，断言无浏览器控制台错误。E2E 只做前端选择，不提交批量审核，避免改动演示数据。

演示数据规模（`seed_demo --reset` 后 + 导入 `seed/content_m1_supplement.md` 并批量通过）：
- 99 道正式题（原型 35 + 演示 10 + 补充内容 54；爬虫 13 / 导入 76 / 手动 10）
- 43 条生效知识条目（原型 22 + 补充 21）
- 99 条复习排程（原型 35 条已有掌握记录）
- 8 条待审
- 4 个导入批次（3 条演示 + 本次补充内容批次）；1 条 `merged` 合并审计（补充内容中 1 题与已有题精确重复）
- 2 个爬虫源（GitHub 启用、牛客停用占位）
- 1 个成功爬虫任务 + 3 个逐文件记录
- 题-知识关联 26 条，覆盖 23 道题 / 22 条知识

> 复现：`python -m app.seed_demo --reset` → 启动后端 → 设置页/导入页上传 `seed/content_m1_supplement.md` → 待审页全选批量通过。

---

## 4. 如何运行

### 4.1 后端（开发）

本机已有一个可复用的虚拟环境：`D:\Program Files\JetBrains\PythonProject\.venv`（Python 3.13.9），本次开发就用它，已安装 requirements 中的全部依赖。也可以新建独立 venv。

```powershell
cd "D:\Program Files\JetBrains\PythonProject\bajiu-review\backend"
# 方式 A：复用工作区 venv
& "D:\Program Files\JetBrains\PythonProject\.venv\Scripts\python.exe" run.py

# 方式 B：新建 venv
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m app.seed_demo     # 空库时写入演示数据
python run.py
```

### 4.2 前端开发

```powershell
cd "D:\Program Files\JetBrains\PythonProject\bajiu-review\frontend"
npm install
npm run dev
```

Vite 已代理 `/api` 到 `http://127.0.0.1:8000`。

### 4.3 单端口生产式本地运行

```powershell
cd frontend
npm run build
cd ..\backend
python run.py
```

后端检测到 `frontend/dist` 会自动托管前端，访问 8000 即可。

### 4.4 测试 / 构建 / E2E

```powershell
cd backend
& "D:\Program Files\JetBrains\PythonProject\.venv\Scripts\python.exe" -m pytest -q

cd ..\frontend
npm run build
npm run e2e
```

E2E 使用本机 Edge：
`C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe`
可用 `EDGE_PATH` 覆盖，可用 `BAJIU_BASE` 指定目标地址。

### 4.5 Docker Compose

`docker-compose.yml`、后端/前端 Dockerfile、nginx 配置均已写好，`docker compose config` 通过。本机 Docker Desktop 当时未启动，因此**镜像构建与容器启动尚未实跑**。

```powershell
# 先启动 Docker Desktop
cd "D:\Program Files\JetBrains\PythonProject\bajiu-review"
copy .env.example .env
docker compose up -d --build
# 访问 http://127.0.0.1:8080
docker compose exec api python -m app.seed_demo
```

结构：`web`（nginx 静态 + `/api` 反代）→ `api`（FastAPI 单 worker，非 root）→ 命名卷 `bajiu_data:/app/data`。

---

## 5. 账号、配置与数据

### 5.1 账号
- 首次启动自动创建：`admin / admin123`
- 环境变量 `APP_USERNAME`、`APP_PASSWORD` 只在用户不存在时生效
- 登录限流：5 次/分钟/IP；连续失败 10 次锁 15 分钟
- 前端用 Bearer token（localStorage），后端同时支持 HttpOnly cookie；cookie 写操作要求 `X-CSRF-Token`

### 5.2 主要环境变量
见 `.env.example` 和 `backend/app/config.py`：
`APP_USERNAME`、`APP_PASSWORD`、`BAJIU_DATA_DIR`、`BAJIU_DB_PATH`、`BAJIU_HOST`、`BAJIU_PORT`、`BAJIU_TOKEN_TTL_MINUTES`、`BAJIU_CORS_ORIGINS`、`GITHUB_TOKEN`。

### 5.3 演示数据重置

```powershell
# 先停止后端
python -m app.seed_demo --reset
```

会删掉 `backend/data/bajiu.db` 后重建。不要在后端运行时执行。

### 5.4 数据库
- SQLite，WAL、`busy_timeout=5000`、`synchronous=NORMAL`、`foreign_keys=ON`
- 启动时 `create_all` 兜底；Alembic 初始迁移已生成并通过 `alembic upgrade head` 验证
- 已有 `create_all` 建出的库接入 Alembic 时先 `alembic stamp head`
- 备份使用 SQLite backup API；恢复会校验 magic/integrity/必要表，并自动生成 `pre-restore-*.db`

---

## 6. 架构与文件地图

### 6.1 后端

```text
backend/app/
├─ main.py             FastAPI 入口、异常统一包、请求 ID、静态托管
├─ config.py           路径/环境变量/.env 加载
├─ database.py         engine、SessionLocal、SQLite PRAGMA、init_db
├─ models.py           25 张业务表，对应文档第 7 章
├─ schemas.py          Pydantic 请求模型
├─ security.py         bcrypt、会话、登录限流、CSRF、默认用户
├─ errors.py           ApiError / ok 响应包
├─ seed_demo.py        演示数据初始化
├─ routers/
│  ├─ auth.py          登录/登出/me
│  ├─ questions.py     题库 CRUD、筛选、归档、题-知识关联
│  ├─ knowledge.py     知识库 CRUD、送审
│  ├─ categories.py    三级分类树
│  ├─ tags.py          标签 + 公司
│  ├─ imports.py       MD/CSV/JSON/粘贴 + 批次 + 按批次删除
│  ├─ pending.py       统一待审、通过/拒绝/合并、建议关联知识
│  ├─ crawl.py         源、任务、逐文件、重试、按源删除
│  ├─ practice.py      练习/冲刺组卷（不下发答案）
│  ├─ review.py        今日队列/摘要
│  ├─ ratings.py       统一评分入口
│  ├─ mistakes.py      错题本
│  ├─ bookmarks.py     收藏夹
│  ├─ stats.py         仪表盘/掌握度/覆盖率/薄弱点
│  ├─ settings.py      app_settings + tag_rules
│  ├─ export.py        JSON/Markdown 导出
│  └─ backup.py        SQLite 备份/恢复
├─ services/
│  ├─ import_parsers.py  Markdown/CSV/JSON 解析、逐行错误
│  ├─ ingest.py          导入/爬虫共用清洗→去重→待审管线
│  ├─ cleaning.py        广告/水印/纯符号行清洗（保留行号）
│  ├─ dedupe.py          精确哈希 + SimHash（题目/知识/待审）
│  ├─ knowledge_extract.py 知识段落抽取、要点候选
│  ├─ tagging.py         规则打标、种子规则加载
│  ├─ categories.py      分类路径/树/标签公司 get_or_create
│  ├─ taxonomy.py        题目标签/分类/公司写入
│  ├─ review.py          SM-2 排程、队列、评分、统计口径
│  ├─ crawler.py         GitHub tree/raw、任务执行、重试
│  ├─ serializers.py     统一字段与掌握度
│  ├─ export_service.py  导出 MD/JSON
│  └─ settings_service.py 默认值/校验
└─ utils/
   ├─ sm2.py             SM-2 纯函数（10.3 公式）
   ├─ text.py            归一化/SHA-256/SimHash
   └─ timeutil.py        Asia/Shanghai、UTC 边界
```

### 6.2 前端

```text
frontend/src/
├─ main.ts / App.vue
├─ api/client.ts        fetch 封装、Bearer、统一错误、下载
├─ api/types.ts         核心类型
├─ stores/app.ts        登录、分类树、岗位板块、徽标、Toast
├─ router/index.ts      hash 路由 + 登录守卫 + 页面元信息
├─ styles/main.css      原型设计语言 + 表单/弹窗/登录/响应式
├─ components/
│  ├─ AppSidebar.vue / TopBar.vue / ToastHost.vue
│  ├─ LineChart.vue / BarRows.vue / DifficultyBars.vue
│  ├─ Modal.vue / Pagination.vue
└─ views/               14 个页面
   Login / Dashboard / Practice / Review / Mistakes / Bookmarks /
   Sprint / Library / Knowledge / Import / Crawl / Pending / Stats / Settings
```

前端**没有引入 Element Plus / ECharts**：为了保留原型视觉，使用原生 CSS + 零依赖 SVG 图表。这是有意的合理优化，功能口径不变。若要换组件库，先评估视觉回归。

### 6.3 关键文件阅读顺序（新窗口建议）

1. 本文 + 项目文档第 0/7/9/10 章。
2. `backend/app/models.py`（唯一数据模型来源）。
3. `backend/app/services/review.py` + `utils/sm2.py`（核心算法口径）。
4. `backend/app/services/ingest.py` + `routers/pending.py`（导入/去重/审核闭环）。
5. `backend/app/services/crawler.py`（爬虫任务）。
6. `backend/app/main.py`（路由与异常/静态托管）。
7. `frontend/src/stores/app.ts` + `router/index.ts` + 任一 view。
8. `backend/tests/`（行为契约）。

---

## 7. 已实现功能清单（对照文档 M1）

- 题库 CRUD、草稿/正式/归档、软删除、恢复、个人笔记、关键词搜索、组合筛选。
- 三级分类树（方向→技术栈→知识点）、多分类路径；顶部岗位板块映射一级分类。
- 标签、公司、难度、频率；题目详情展示来源、掌握历史、关联知识。
- 知识库 CRUD、别名、概念/原理/流程/对比/易错点、软删除/归档、关联题目、送待审。
- 练习组卷（答案不下发）、三档自评、错题自动收录、连续通过自动移出、收藏。
- SM-2：EF 先更新再算间隔、1/6/round、EF 下限、间隔封顶、同日防重、跨日、提前复习开关、冲刺例外。
- 今日到期 + 新题队列、每日上限、积压数、已评分题当天不重复。
- Markdown/CSV/JSON/粘贴导入；UTF-8/GB18030；大小/行数限制；逐行错误；文件哈希提示。
- Markdown 代码块跳过；广告/水印/纯符号清洗（空行占位保留行号）；知识段落抽取。
- 精确 SHA-256 去重 + SimHash 近似去重；去重语料覆盖题目/知识/待审项；合并保留来源。
- GitHub 爬虫：源管理、tree 递归、raw 下载、逐文件状态、任务日志、失败重试、按文件缓存。
- 统一待审：题目/知识、低置信度置顶、相似项、建议元数据、通过/拒绝/合并/编辑/批量通过接口。
- 题目通过时可勾选“建议关联知识”；组合 JSON 的题-知识引用在双方通过后自动建立。
- 规则打标：contains/regex、标签/分类/难度/频率/权重、种子 YAML、设置页 CRUD。
- 仪表盘 6 指标 + 7 天趋势；掌握度分布、正确率趋势、薄弱点、知识覆盖率。
- 导出 JSON/Markdown（可回环）；SQLite 备份/恢复；设置页全部参数。
- 登录、会话、限流、CORS、CSRF（cookie 模式）、SSRF 白名单、纯文本渲染。
- Docker Compose/nginx/非 root/健康检查/命名卷（配置已就绪，未实跑）。
- 测试：SM-2 十类用例、解析、导入→待审→入库、关联、导出回环、备份恢复、合并、爬虫 dry-run、CSV 逐行错误、文件哈希提示、SimHash 近似、待审批量、SSRF、登录限流、规则覆盖、500 题性能（SQL 计数）、错题导出。

---

## 8. 关键实现约定（改代码前必须知道）

1. **时间**：数据库存 UTC naive；业务日期用 `Asia/Shanghai`。`next_review_date`/`first_reviewed_at`/`last_schedule_date` 是本地日期字符串 `YYYY-MM-DD`。
2. **掌握度**：`review_schedule.last_q` 与最新 `mastery_records.q` 同步；`first_reviewed_at` 非空=已学；`last_q=5`=精通。
3. **同日防重**：`last_schedule_date == 本地今天` 时评分只写记录，不推进/重置排程（冲刺也遵守；但冲刺下新题评熟悉/精通另有 `sprint` 例外）。
4. **复习队列**：实时计算；到期题排除“今天已评分”的题；`due_total` 是未评分的到期总数，`backlog = due_total - 返回数`。
5. **待审唯一入口**：题目/知识待审只在 `pending_items`。精确重复会生成 `status='merged'` 的审计行并追加来源，不进入待审队列。
6. **分类主路径**：一个题可挂多个分类（含岗位板块根），序列化/导出取**层级最深、路径最长**的分类作为 `category_path`。
7. **导入直接入库**：只对 `source_type=import` 且设置 `import.direct_to_active=true` 且无组合 JSON links 时生效；知识条目始终走待审。
8. **知识候选**：题目通过时，若 `key_points≥3`，自动生成一条低置信度知识候选项进待审，不自动入知识库。
9. **建议关联知识**：待审详情返回 `suggested_knowledge`，前端勾选后随 approve 的 `knowledge_ids` 写入 `question_knowledge`；不是自动关联。
10. **爬虫**：M1 只支持 GitHub；URL 仅允许 `github.com`/`raw.githubusercontent.com`/`api.github.com`；牛客源可创建但运行报 M2。后台线程写库，启动时把遗留 `running` 任务标记 `failed`。
11. **SQLite 并发**：单 worker；WAL + busy_timeout；避免长事务；写操作尽量短并显式 commit。
12. **备份恢复**：`/backup/import` 会关闭当前 session、dispose engine、替换文件、重新 init；恢复时不要有爬虫任务运行。测试里已验证回环。
13. **测试 DB**：`tests/conftest.py` 在导入 app 前把 `BAJIU_DB_PATH` 指向临时目录；每个测试重建数据库文件。不要改成共享 demo DB。
14. **前端路由**：`createWebHashHistory`，URL 形如 `/#/dashboard`；后端静态托管不需要 SPA fallback。
15. **前端 auth**：token 存 localStorage，所有 API 带 Bearer；401 自动清 token 并跳登录。cookie/CSRF 后端也支持，但前端不走 cookie 写操作。
16. **前端设计**：自定义 CSS/SVG，`v-html` 禁用；答案按纯文本换行展示。
17. **板块**：一级分类即岗位板块；`boardId=0` 表示全部题目。板块顺序在 seed 中设置 sort_order，与原型一致。
18. **演示口令**：默认 `admin123`；改 `APP_PASSWORD` 不会改已有用户。

---

## 9. 已知缺口 / 建议下一步

### P0（建议新窗口优先）

1. **真实 GitHub 爬虫端到端验收**：代码侧已加固取数稳定性（IPv4 绑定、socket 重试、每文件时限、默认 UA 源不再固定等 10s），但本次未跑真实仓库。现场情况：本机对 `raw.githubusercontent.com` 经常被中途断连；直连（默认解析）单文件可达 80s，绑定 IPv4 后约 1s。验收步骤：配一个固定 commit 的公开英文面经 Markdown 仓库（中文仓库在 GitHub 搜索接口里基本检索不到），源设置 `interval_sec=1`、`timeout_sec=30`，观察任务的逐文件记录与待审增长；英文内容规则打标覆盖会较低。
   代码入口：`backend/app/services/crawler.py`；测试替身见 `tests/test_api.py::test_crawl_parse_and_dry_run`（Fake Client 不提供 `fetch_client`，凡真实客户端专属逻辑都要先判空）。
2. **内容量**：演示库已到 99 题 / 43 知识，达到文档 M1 “100–200 题”下限附近。补充内容格式见 `seed/content_m1_supplement.md`，样本 CSV 见 `seed/sample_import.csv`。
3. **Docker 实跑**：按本次交接要求暂缓。启动 Docker Desktop 后 `docker compose up -d --build` 验证。
4. **剩余补测试**：Markdown XSS（前端已禁用 `v-html`，后端纯文本渲染）、Alembic 迁移自动化、爬虫真实网络批次（建议用录制的 fixture 代替）。

### P1（M1 收尾/体验）

- `IMPORT_PARTIAL` / `CRAWL_FAILED` 业务码：当前 HTTP 200 + `code=OK` + `batch.status=partial`，与文档错误码表略有差异。
- 归一化规则版本化（文档 4.4）：当前无版本字段/常量，只有哈希。
- GitHub ETag/Last-Modified 缓存（文档“建议”项）。
- 待审合并时目标搜索的分页/更丰富筛选。
- 规则打标覆盖：补充内容中仍有约 1/3 题目没有规则命中（偏前沿/工程话题），可按需追加 `config/tag_rules.yaml` 规则；覆盖测试在 `tests/test_security.py::test_seed_rules_cover_sample_pending_items`。
- SimHash 阈值 3 对中文短句偏严：差一个字的表述常常差 14+ 位，近似去重主要靠精确哈希生效；如需更强相似提示可调 `dedupe.simhash_threshold`（设置页可改）或换成字符 n-gram 特征。
- 知识条目多分类（M2）、知识卡片复习（文档说 M1 不做）。
- 爬虫定时调度（M2）、牛客爬虫（M2）、xlsx（M2）、FTS5（M2）、PostgreSQL/知识图谱（M2 可选）。

### P2（M3，全部后置）
- AI 网关、题目/知识质量审查、自动打标、错题解析、答案润色、仿真面试、周报告；`quality_checks` 等表未建。文档 D4 明确 M1/M2 不依赖 AI。

### 已知非功能限制
- 性能验收为 TestClient 口径（500 题 11 条 SQL、约 36ms）；未做真实外网爬虫验收与 Docker 实跑。
- 前端为自定义组件，不含 Element Plus/ECharts。
- 控制台/终端在 Windows 下可能把中文显示为乱码，这是编码显示问题；浏览器/API JSON 正常。测试断言用 Unicode 字符串，结果可信。
- 工作区不是 git 仓库；没有提交历史。`.gitignore` 已准备好，建议接手后先 `git init` 并做首次提交。

---

## 10. 常用命令速查

```powershell
# 后端
cd "D:\Program Files\JetBrains\PythonProject\bajiu-review\backend"
& "D:\Program Files\JetBrains\PythonProject\.venv\Scripts\python.exe" run.py
& "D:\Program Files\JetBrains\PythonProject\.venv\Scripts\python.exe" -m pytest -q
& "D:\Program Files\JetBrains\PythonProject\.venv\Scripts\python.exe" -m app.seed_demo
& "D:\Program Files\JetBrains\PythonProject\.venv\Scripts\python.exe" -m app.seed_demo --reset

# 迁移
& "D:\Program Files\JetBrains\PythonProject\.venv\Scripts\python.exe" -m alembic upgrade head
& "D:\Program Files\JetBrains\PythonProject\.venv\Scripts\python.exe" -m alembic stamp head

# 前端
cd "D:\Program Files\JetBrains\PythonProject\bajiu-review\frontend"
npm run dev
npm run build
npm run e2e

# 端口检查 / 结束遗留进程
netstat -ano | grep ':8000'
tasklist //FI "PID eq <PID>"
taskkill //PID <PID> //F
```

API 登录示例：

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin123"}'
# 取 data.token，然后：
curl -s http://127.0.0.1:8000/api/v1/stats/dashboard \
  -H "Authorization: Bearer <token>"
```

---

## 11. 交接时的环境坑（重要）

1. **npm 镜像**：本机 npm registry 是腾讯镜像，本次安装出现 tarball 损坏/`TAR_ENTRY_ERROR`/`ENOENT`。已改用官方源成功：
   `npm install --registry=https://registry.npmjs.org`
   新增依赖时如再遇损坏，先删 `node_modules`，再用官方源。
2. **Python venv**：本机工作区 `.venv` 已安装 fastapi/sqlalchemy/alembic/pytest/freezegun 等；`requirements.txt` 新增 `python-dotenv` 也已安装。如新建 venv，按 requirements 重装。
3. **路径含空格**：`D:\Program Files\...`，所有 shell 命令请加引号；文件工具使用完整绝对 Windows 路径。
4. **Docker**：本机 Docker Desktop 未启动；`docker compose config` 可跑，`up/build` 需要先启动 daemon。
5. **端口幽灵进程**：本次遇到旧 uvicorn 占用 8000，新实例启动失败但旧页面仍可用，容易误判“新代码已生效”。改后端后请确认端口 PID 并重启。
6. **前端 Edge E2E**：使用本机 Edge，无需 `npx playwright install`；如路径不同设 `EDGE_PATH`。
7. **演示库 vs 测试库**：pytest 用临时目录，不会动 `backend/data/bajiu.db`；`seed_demo --reset` 才会动演示库。
8. **时区**：直接跑 `datetime.now()` 会引入时区错误，统一用 `utils/timeutil.py`。

---

## 12. 新窗口开场提示（可直接复制）

```text
项目在 D:\Program Files\JetBrains\PythonProject\bajiu-review。
请先阅读项目根目录 HANDOFF.md，再按“关键文件阅读顺序”读代码。
当前状态：M1 功能已完成，后端 32 tests passed，前端 build/E2E 通过。
我想继续做的下一件事是：<在这里写任务，例如：跑真实 GitHub 爬虫验收 / 补 500 题性能测试 / 实跑 Docker Compose / 补错题导出>。
注意：后端默认 127.0.0.1:8000，默认账号 admin/admin123；改后端后要确认旧 uvicorn 进程已结束；npm 安装用官方 registry。
```

---

## 13. 交接结论

代码已经是一个可运行、可演示、可继续开发的 M1 基线：核心闭环（导入/爬虫 → 待审 → 题库/知识库 → 刷题/复习 → 统计/导出/备份）全部打通，且关键算法与闭环路径有自动化测试保护。

下一步最有价值的不是继续堆页面，而是：
1) 用真实面经内容做一次爬虫/导入验收；
2) 做 500 题性能基准并消除列表 N+1；
3) 实跑 Docker Compose；
4) 再决定是否进入 M2（牛客/调度/FTS5/xlsx）或 M3（AI）。

祝接手顺利。
