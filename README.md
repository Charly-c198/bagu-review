# 八股文智能复习系统

个人专属的面试八股文记忆 + 间隔重复（SM-2）+ 题库/知识库 Web 系统。按《八股文智能复习系统_项目文档_V0.4》的 **M1（P0）** 范围实现，本地优先、单用户、无 AI 也能完整使用。

前端在原型 HTML 的基础上迁移为 Vue 3 + TypeScript + Vite + Pinia，保留原型的设计语言（青绿主题、侧边栏、卡片、刷题卡、SVG 趋势图），并补齐登录、知识库、收藏夹、采集任务、规则打标、备份恢复等页面。

> 接手/继续开发：先阅读 [`HANDOFF.md`](HANDOFF.md)，其中包含当前状态、运行方式、关键约定、已知缺口与下一步建议。

---

## 1. 已实现功能

### 学习闭环
- 仪表盘：今日到期 / 已学 / 已精通 / 错题 / 连续打卡 / 知识条目，近 7 天复习趋势。
- 主动刷题：按分类、标签、公司、难度、频率、来源筛选；答案后置；三档自评（不熟 / 熟悉 / 精通）。
- 今日复习：实时生成到期队列 + 新题队列，显示积压与每日上限；同一题同一天不重复出现。
- SM-2 排程：EF 更新顺序、间隔 1/6/round(interval×EF)、EF 下限 1.3、间隔封顶、同日防重、跨日、提前复习开关。
- 错题本：评“不熟”自动收录；连续两次“熟悉/精通”自动移出（阈值可配）；手动移出保留流水。
- 收藏夹、考前冲刺（忽略到期日期，按频率抽题，默认不改排程）。
- 个人笔记、关键词搜索、软删除、归档/恢复。

### 题库与知识库
- 分类树：方向 → 技术栈 → 知识点（最多 3 级）；顶部岗位板块切换映射到一级分类。
- 自由标签、公司、难度、频率；多分类路径。
- 知识条目库：概念/原理/流程/对比/易错点；别名；与题目多对多关联（`related` / `prerequisite` / `derived_from`）。
- 题目详情展示关联知识、掌握历史、来源溯源；知识详情展示关联题目与来源。
- 统计：掌握度分布、正确率趋势、不熟知识点分布、知识覆盖率。

### 导入 / 爬虫 / 待审
- 本地导入：Markdown / CSV / JSON；文件上传或批量粘贴；UTF-8/GB18030；逐行错误定位；大小与行数限制；相同文件哈希提示。
- Markdown 支持题目 + 显式知识块，并从定义/原理/对比/流程/注意等段落启发式抽取知识候选；无 `## 题目：` 标记的仓库文章按标题/问答启发式切分（低置信度进待审）。
- GitHub Markdown 爬虫：源管理、递归 tree 列表、raw 下载、逐文件状态、失败重试、任务日志；raw 域名 IPv4 绑定与连接池重建；TLS 校验可切到系统根证书（`BAJIU_GITHUB_SSL=system`，适合本机 TLS 代理）。
- 统一待审区 `pending_items`：`item_type=question|knowledge`；通过 / 拒绝 / 合并；审核时编辑建议元数据；低置信度置顶；相似项与重复命中提示。
- 规则打标 `tag_rules`：关键词 `contains` / `regex` → 标签、分类、难度、频率建议；启动时从 `config/tag_rules.yaml` 加载种子规则；设置页可增删改。
- 精确去重（归一化 SHA-256）+ SimHash 近似去重（汉明距离阈值可配）。
- 来源溯源：`question_origins` / `knowledge_origins`，支持按导入批次 / 爬虫源删除并归档无来源内容。
- 组合 JSON 的题-知识关联在双方审核通过后自动建立。

### 设置 / 数据
- SM-2 参数、每日上限、提前复习、导入直接入库、手动新建进待审、去重阈值、爬虫单次文件数等可配置。
- 导出 JSON / Markdown（可回环导入，含知识条目与关联）。
- SQLite 在线备份（backup API）、保留最近 7 份、恢复前完整性校验并自动生成 pre-restore 备份。
- 口令登录、服务端会话、登录限流、CORS 白名单、CSRF 保护（cookie 模式）、Markdown 文本按纯文本渲染避免 XSS。
- Docker Compose：nginx 静态前端 + FastAPI 单 worker + 命名卷 SQLite。

### 尚未实现（按文档后置）
- M2：牛客爬虫、定时调度、FTS5、xlsx、PostgreSQL、知识图谱。
- M3a/M3b：大模型网关、AI 质量审查、自动打标、错题解析、仿真面试、周报告（D4 明确 AI 全部后置）。
- M4：TTS/ASR、多人化、移动端。

---

## 2. 技术栈与结构

```text
bajiu-review/
├─ backend/
│  ├─ app/
│  │  ├─ main.py                 FastAPI 入口 / 异常包 / 静态托管
│  │  ├─ config.py               环境变量与路径
│  │  ├─ database.py             SQLAlchemy / SQLite PRAGMA
│  │  ├─ models.py               25 张业务表（对应文档第 7 章）
│  │  ├─ security.py             bcrypt / 会话 / 限流 / CSRF
│  │  ├─ routers/                auth、题库、知识、导入、爬虫、待审、复习、统计…
│  │  ├─ services/               SM-2、导入解析、去重、规则打标、爬虫、审核管线…
│  │  ├─ utils/                  归一化 / SimHash / 时区 / SM-2 纯函数
│  │  └─ seed_demo.py            演示数据
│  ├─ config/tag_rules.yaml      规则打标种子
│  ├─ seed/demo_seed.json        35 题 + 22 条知识
│  ├─ alembic/                   迁移
│  ├─ tests/                     27 个单元/接口测试
│  ├─ requirements.txt
│  ├─ run.py
│  └─ Dockerfile
├─ frontend/
│  ├─ src/
│  │  ├─ views/                  14 个页面
│  │  ├─ components/             侧边栏、TopBar、Modal、LineChart、BarRows…
│  │  ├─ stores/app.ts           Pinia（登录、板块、徽标、Toast）
│  │  ├─ api/                    fetch 封装 + 类型
│  │  ├─ router/                 hash 路由 + 登录守卫
│  │  └─ styles/main.css         原型设计语言
│  ├─ package.json
│  ├─ vite.config.ts
│  ├─ nginx.conf
│  └─ Dockerfile
├─ docker-compose.yml
├─ docs/八股文智能复习系统_项目文档_V0.4.md
├─ .env.example
└─ README.md
```

- 后端：Python 3.11+（开发环境 3.13）、FastAPI、SQLAlchemy 2、Alembic、SQLite（WAL）、bcrypt、httpx、PyYAML。
- 前端：Vue 3、TypeScript、Vite、Pinia、Vue Router。
- **前端图表与 UI 未引入 Element Plus / ECharts**：为最大限度保留原型视觉，使用原生 CSS + 零依赖 SVG 组件实现；这属于文档允许的“合理优化”，不改变功能验收口径。
- API 前缀 `/api/v1`，统一返回 `{ code, data, message }`；Swagger：`/api/docs`。

---

## 3. 快速开始（本地开发）

### 3.1 后端

```powershell
cd "D:\Program Files\JetBrains\PythonProject\bajiu-review\backend"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 可选：写入 35 道演示题、22 条知识、待审/批次/爬虫样例
python -m app.seed_demo

python run.py
```

macOS / Linux：

```bash
cd bajiu-review/backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m app.seed_demo
python run.py
```

- 后端默认：`http://127.0.0.1:8000`
- 健康检查：`http://127.0.0.1:8000/api/v1/healthz`
- 默认账号：`admin / admin123`（可用 `APP_PASSWORD` 覆盖；首次启动自动创建用户）

### 3.2 前端（开发模式）

```bash
cd bajiu-review/frontend
npm install
npm run dev
```

打开 `http://127.0.0.1:5173`。Vite 已把 `/api` 代理到 `http://127.0.0.1:8000`。

> 本机 npm 曾使用腾讯镜像导致 tarball 损坏；如遇 `TAR_ENTRY_ERROR` / `ENOENT`，执行：
> `npm install --registry=https://registry.npmjs.org`

### 3.3 单端口运行（无需 Vite）

```bash
cd bajiu-review/frontend
npm run build
cd ../backend
python run.py
```

后端检测到 `frontend/dist` 后会在 `http://127.0.0.1:8000` 直接托管前端。

### 3.4 演示数据

```bash
cd backend
python -m app.seed_demo          # 空库时写入；已有题目则跳过
python -m app.seed_demo --reset  # 删除当前数据库并重建（会丢数据；请先停止后端）
```

演示数据包含 8 个岗位板块、35 道题、22 条知识、35 条复习排程、错题/收藏、8 条待审项、3 个导入批次、2 个爬虫源与 1 个成功任务。

---

## 4. 配置

复制 `.env.example` 为项目根目录 `.env`，或直接设置环境变量。配置在 `backend/app/config.py` 读取。

| 变量 | 默认 | 说明 |
|---|---|---|
| `APP_USERNAME` | `admin` | 首次启动创建的用户名 |
| `APP_PASSWORD` | `admin123` | 首次启动口令；已有用户不会自动改 |
| `BAJIU_DATA_DIR` | `backend/data` | SQLite、备份、爬虫缓存目录 |
| `BAJIU_DB_PATH` | `$DATA_DIR/bajiu.db` | SQLite 文件路径 |
| `BAJIU_HOST` | `127.0.0.1` | 监听地址 |
| `BAJIU_PORT` | `8000` | 端口 |
| `BAJIU_TOKEN_TTL_MINUTES` | `10080` | 会话有效期（7 天） |
| `BAJIU_CORS_ORIGINS` | `http://127.0.0.1:5173,http://localhost:5173` | CORS 白名单 |
| `BAJIU_MAX_IMPORT_BYTES` | `5242880` | 导入硬上限（设置页可再调低） |
| `BAJIU_MAX_IMPORT_ROWS` | `2000` | 导入行数硬上限 |
| `GITHUB_TOKEN` | 空 | 可选，GitHub API 限流时使用 |
| `BAJIU_GITHUB_SSL` | `certifi` | 采集 TLS 校验：`certifi` / `system`（系统根证书，本机走 TLS 代理时用）/ `none`（仅排障） |

> `.env` 中的相对路径以启动进程的工作目录为基准。建议从 `backend/` 启动，或写绝对路径。

---

## 5. 关键口径

### 5.1 掌握度
取每题最近一次评分：
- `q=2` → 不熟
- `q=4` → 熟悉
- `q=5` → 精通
- 无记录 → 未学

数据层实现上 `review_schedule.last_q` 与最新 `mastery_records.q` 同步维护。

### 5.2 SM-2
- 三档自评映射 q=2/4/5。
- q<3：`lapses+1`、`reps=0`、`interval=1`、EF 不变、进错题本。
- q≥3：先更新 EF，再计算间隔：`reps=1 → 1 天`，`reps=2 → 6 天`，`reps≥3 → round(interval × EF)`；EF 下限 1.3，间隔封顶可配。
- q=5 时 EF +0.1；q=4 时 EF 不变；q=3 时 EF -0.14。
- 同日防重：`last_schedule_date == 本地今天` 时不再推进/重置排程，只记录评分。
- 新题首次评分一定推进；未到期题评熟悉/精通默认只记录（`review.early_advances=true` 可开启提前推进）；未到期题评“不熟”会重置。
- 时区固定 `Asia/Shanghai`；存储 UTC，业务日期用本地 `YYYY-MM-DD`。

### 5.3 复习队列
- 请求时实时生成，不物化每日队列表。
- 到期题按 `next_review_date` 升序，新题随后；已评分题当天不再出现。
- 超过每日上限时返回上限条，并返回积压数，不丢题。

### 5.4 导入与待审
- 导入默认进 `pending_items`；`import.direct_to_active=true` 时题目可直接入库，知识条目始终走待审。
- 精确重复：题干归一化 SHA-256 命中 → 待审记录标 `merged` 并追加来源，不再进入待审队列。
- 近似重复：SimHash 汉明距离 ≤ 阈值（默认 3）→ 待审项标记 `dup_of`，由人工决定合并。
- 从题目要点（≥3 条）自动生成一条知识候选，仍进入待审区。

---

## 6. 测试

```bash
cd backend
python -m pytest -q
```

覆盖：
- SM-2 文档 10.6 的十类用例、EF 下限、间隔封顶、同日防重、提前复习、跨日边界。
- Markdown / CSV / JSON 解析、代码块跳过、组合 JSON 关联；无标记 Markdown 的标题/问答应答式切分。
- 题库 CRUD、评分、同日防重、复习队列排除已评分、统计。
- 导入 → 待审 → 通过 → 来源溯源；题-知识关联；导出 → 再导入回环（含关联恢复）。
- 错题本、收藏夹、设置与规则、备份导出。
- **爬虫确定性验收**（`tests/test_crawl_acceptance.py`）：58 个 fixture 文件 → 92+ 候选题、≥30 知识、精确去重、失败重试、逐文件状态、批量审核与关联建立。
- 规则打标独立覆盖率验收（`tests/test_tagging_coverage.py`，20 条未参与调规则的题干）。
- Markdown XSS 纯文本存储、前端无 `v-html`、Alembic 空库迁移与表覆盖检查（`tests/test_ops.py`）。

当前结果：后端 `54 passed`（约 40s），前端 `npm run build` 与 E2E 均通过。

一键本地检查（与 CI 同口径：ruff + pytest + 前端构建，可选 `-WithE2E` / `--with-e2e`）：

```powershell
.\scripts\check.ps1
```

```bash
./scripts/check.sh            # Git Bash / WSL / Linux
```

CI 配置在 `.github/workflows/ci.yml`：后端 `ruff check` + `pytest`，前端 `npm ci` + `npm run build`，不构建镜像、不跑 E2E（E2E 依赖本机 Edge）。

前端 E2E 冒烟（使用本机已安装的 Edge，无需下载浏览器）：

```bash
cd frontend
npm run e2e
```

覆盖登录、仪表盘、刷题翻答案、今日复习、题库详情、知识库、导入、采集任务、待审、统计、设置、收藏/错题/冲刺，并断言无浏览器控制台错误。截图输出到 `frontend/e2e/artifacts/`。如 Edge 不在默认路径，设置 `EDGE_PATH` 环境变量。

数据库迁移：

```bash
cd backend
alembic upgrade head       # 全新空库建表
alembic revision --autogenerate -m "change"
```

应用启动时会 `create_all` 兜底；如果数据库已经由 `create_all` 创建、尚无 `alembic_version`，首次接入 Alembic 请执行：

```bash
alembic stamp head
```

---

## 7. Docker Compose（W6 交付）

```bash
cd bajiu-review
copy .env.example .env      # 可选，修改 APP_PASSWORD / GITHUB_TOKEN
docker compose up -d --build
```

- 访问：`http://127.0.0.1:8080`
- 服务：
  - `web`：nginx 托管前端静态产物，`/api` 反向代理到 `api:8000`
  - `api`：FastAPI + uvicorn **单 worker**，非 root 用户
- 数据卷：命名卷 `bajiu_data` 挂载 `/app/data`（Windows 下避免绑定挂载直接写 SQLite）
- 健康检查：`GET /api/v1/healthz`
- 写入演示数据：

```bash
docker compose exec api python -m app.seed_demo
```

- 备份文件位于容器 `/app/data/backups`，可用 `docker compose cp api:/app/data/backups/<file>.db ./` 取出。
- 端口只发布到 `127.0.0.1:8080`，符合 M1 本机单用户默认安全值。

---

## 8. 数据备份与恢复

- 页面：设置 → 数据与备份
- 导出题库/知识：JSON（组合格式，含关联）或 Markdown（附录 A.1/A.6 兼容）
- 生成备份：SQLite backup API；自动保留最近 7 份
- 恢复：校验 SQLite magic、`PRAGMA integrity_check`、必要表；自动生成 `pre-restore-*.db`；恢复后建议重启服务
- 手动备份：

```bash
sqlite3 backend/data/bajiu.db ".backup 'backend/data/backups/manual.db'"
```

---

## 9. 与原型/文档的对应关系

| 原型 | 实现 |
|---|---|
| 顶部岗位板块 | 一级分类（方向）；“全部题目”= 不筛选 |
| 仪表盘 | `/dashboard`，6 项指标 + 7 天趋势 + 到期队列 |
| 主动刷题 | `/practice`，支持筛选、答案后置、三档自评 |
| 今日复习 | `/review`，到期 + 新题、积压、内联复习 |
| 错题本 / 收藏夹 | `/mistakes`、`/bookmarks` |
| 题库管理 | `/library`，CRUD + 搜索 + 详情 + 关联知识 |
| 本地导入 | `/import`，MD/CSV/JSON + 粘贴 + 批次错误报告 |
| 采集任务 | `/crawl`，源管理 + 任务 + 逐文件状态 + 重试 |
| 采集待审 | `/pending`，题目/知识统一审核 |
| 统计复盘 | `/stats`，掌握度/正确率/薄弱点/知识覆盖 |
| 设置 | `/settings`，SM-2、导入、规则打标、板块、备份、账号 |
| 原型没有的登录 | 已补口令登录 + 会话 + 限流 |
| 原型没有的知识库/收藏/冲刺 | 按文档补齐 |

项目文档：
- 工作区根目录：`D:\Program Files\JetBrains\PythonProject\八股文智能复习系统_项目文档_V0.4.md`
- 项目内副本：`bajiu-review/docs/八股文智能复习系统_项目文档_V0.4.md`

---

## 10. 常见问题

**登录 401 / 口令错误**
- 默认 `admin / admin123`。若数据库已存在用户，修改 `APP_PASSWORD` 不会改旧口令；可删除 `bajiu.db` 重新初始化（会丢数据），或在 Python 环境中重置 `users.password_hash`。

**端口被占用**
- 修改 `BAJIU_PORT`；前端代理地址在 `frontend/vite.config.ts`。

**导入乱码**
- 优先 UTF-8（含 BOM），失败自动尝试 GB18030；仍失败会提示“无法识别编码”。

**爬虫没有抓到文件**
- 确认源 URL 是公开 GitHub 仓库 / tree / raw URL；GitHub API 限流时配置 `GITHUB_TOKEN`；任务详情里可看逐文件 HTTP 状态与错误。

**SQLite 锁**
- 已启用 WAL、`busy_timeout=5000`、单 worker；避免多个后端进程同时写同一个数据库。

**npm 安装失败**
- 使用 `npm install --registry=https://registry.npmjs.org`，或清理 `node_modules` 后重试。

---

## 11. 安全与合规

- 默认仅监听 `127.0.0.1`；如需局域网访问，请自行加 HTTPS 反向代理。
- 口令 bcrypt 哈希；会话 token 只存 SHA-256 哈希；登录限流。
- CORS 白名单；cookie 模式写操作要求 `X-CSRF-Token`；前端默认使用 Bearer。
- GitHub 源 URL 仅允许 `github.com` / `raw.githubusercontent.com` / `api.github.com`，拒绝私网/任意主机（SSRF 防护）。
- 爬虫仅抓公开内容、限频、记录来源、不绕过登录/付费；个人学习不商用。
- Markdown/答案以纯文本渲染，不使用 `v-html`；导入文件限制大小/扩展名/MIME。
- AI 功能未接入，不会把答题记录发送给任何 LLM。
