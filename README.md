# 八股文智能复习系统

个人专属的面试八股文记忆 + 间隔重复（SM-2）+ 题库/知识库 Web 系统。按《八股文智能复习系统_项目文档_V0.4》的 **M1（P0）**、**M2 指定范围**（牛客爬虫、FTS5 全文搜索、统计可视化增强、多维筛选增强、知识图谱基础版）与 **M3 全部范围**（M3a：AI 网关、质量审查、自动打标、错题解析、答案润色；M3b：AI 出题、文字仿真面试、周学习报告）实现，本地优先、单用户、无 AI 也能完整使用。

前端在原型 HTML 的基础上迁移为 Vue 3 + TypeScript + Vite + Pinia，保留原型的设计语言（青绿主题、侧边栏、卡片、刷题卡、SVG 趋势图），并补齐登录、知识库、收藏夹、采集任务、规则打标、备份恢复等页面。

> 接手/继续开发：先阅读 [`M3_HANDOFF.md`](M3_HANDOFF.md)（M3 全貌、AI 配置与坑）、[`M2_HANDOFF.md`](M2_HANDOFF.md)（M2 进度与坑）和 [`NEW_SESSION_HANDOFF.md`](NEW_SESSION_HANDOFF.md)（M1 背景与运行约定）。

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

### M2 指定范围（已完成）

- **牛客公开页爬虫**：支持公开帖子 `https://www.nowcoder.com/discuss/<id>` 与 sitemap（自动发现 `/discuss/<id>`，索引文件递归一层，单次最多 5 个子 sitemap）；域名白名单、仅 https、遵守 `robots.txt`（缓存 1 小时）；正文用 `HTMLParser` 转 Markdown（保留标题/列表/代码块），编号问答转题目候选；每篇间隔 ≥1 秒；与 GitHub 爬虫共用逐文件状态、重试、缓存、任务日志与待审管线。列表页是 SPA，明确拒绝并提示改用帖子或 sitemap。
- **FTS5 全文搜索**：`questions` / `knowledge` 独立 FTS 表 + 触发器同步，`tokenize='trigram'` 支持中文子串；题库、知识库、组卷搜索已接入；<3 字查询自动回退 `LIKE`；启动时补齐历史索引，备份恢复后自动重建。
- **统计可视化增强**：近 30 天复习热力图（每日自评次数与正确率，5 档颜色） + 各技术栈掌握度堆叠条，新端点 `/api/v1/stats/review-heatmap`、`/api/v1/stats/category-mastery`。
- **多维筛选增强**：题库/组卷支持分类、标签、公司、难度、频率、来源、掌握度多选，**维度之间 AND、维度内部 OR**；前端 `MultiSelect` 复选面板；知识库支持分类/类型多选。
- **知识图谱基础版**：`GET /api/v1/graph` 返回知识节点、知识-知识共现边（共享同一道题，权重=共现题数）与知识-题关系边；前端 `/graph` 同步力导向 SVG，支持点击详情、“以此为中心”一跳聚焦、显示题目节点、30/50/80/120 节点上限。

### M3a Slice 1（AI 质检 + 人工质检）

- **AI 网关**：OpenAI 兼容 `POST /chat/completions`，通过环境变量配置 base_url / key / model；支持超时重试、JSON 模式自动降级、JSON Schema 校验与一次修复重试。
- **质量审查**：待审项、题目、知识条目均可手动发起 AI 质检；输出问题类型、严重度、证据、修改建议、置信度与整体风险，写入 `quality_checks`，**只做建议**，不改变审核状态或正文。
- **人工质检兜底**：AI 未配置、超时、限流、预算用完或返回格式不合法时，落一条 `status=failed` 记录；前端显示“待人工质检”，可填写同结构表单，或稍后重试 AI。人工通道始终可用，不依赖 Key。
- **成本与缓存**：`ai_calls` 记录 token、耗时与状态；`ai_cache` 按内容哈希缓存；月 token 预算硬上限，超限后提示转人工。
- **隐私**：AI 输入不包含题目个人笔记与用户答题原文；Key 只从环境变量读取，不落库、不回显。
- **状态入口**：设置页展示 AI 配置、模型、本月用量与缓存命中；接口 `GET /api/v1/ai/status`。

### M3a Slice 2/3（自动打标 / 错题解析 / 答案润色）

- **AI 建议表** `ai_suggestions`：所有增强输出先落库，**用户显式“应用”后才修改**待审建议元数据或正式题目；失败也保留记录与错误码，可重新生成。
- **自动打标建议**：待审详情中“规则建议”与“AI 建议”分开显示；AI 参考现有分类路径与标签，给出分类、标签、难度、频率、置信度与理由。应用时合并标签、覆盖分类/难度/频率，规则命中记录保留。
- **错题解析**：题目详情与错题本均可发起；输出拓展讲解、易错点、2–3 个自测追问与相关知识点。默认只发送题干/答案/要点，**只有勾选同意才发送作答原文**。
- **答案润色**：题目详情生成“面试可口述”版本与要点；预览后由用户确认替换参考答案，不自动改题。

### M3b（AI 出题 / 仿真面试 / 周报告）

- **AI 题库生产**：知识详情按知识点生成题目（数量、难度可选），**一律写入 `pending_items`（source_type=ai）**，人工审核后才入正式题库；重复题干自动跳过。
- **文字仿真面试**：按分类/难度/频率随机组卷，题量与时长可配；逐题文字作答、倒计时、逐题评分与追问；**作答原文默认不发送 AI**，创建会话时显式勾选同意才启用 AI 评分；未同意或 AI 失败时作答仍保存，可手动评分。
- **复盘报告**：总分、逐题得分、亮点、知识缺口、建议与下一步；AI 复盘失败自动降级为基础报告。结束时按评分回写 SM-2 掌握记录，低于 3 分自动进入错题本。
- **周学习报告**：统计本周自评量、正确率、活跃天数、新学、错题、分类正确率与面试表现；AI 生成薄弱点与下周计划，AI 不可用时生成本地统计版；同一周重复生成覆盖同一条记录。

### 设置 / 数据
- SM-2 参数、每日上限、提前复习、导入直接入库、手动新建进待审、去重阈值、爬虫单次文件数等可配置。
- 导出 JSON / Markdown（可回环导入，含知识条目与关联）。
- SQLite 在线备份（backup API）、保留最近 7 份、恢复前完整性校验并自动生成 pre-restore 备份。
- 口令登录、服务端会话、登录限流、CORS 白名单、CSRF 保护（cookie 模式）、Markdown 文本按纯文本渲染避免 XSS。
- Docker Compose：nginx 静态前端 + FastAPI 单 worker + 命名卷 SQLite。

### 尚未实现（按文档后置）
- M2 其余项：定时调度、xlsx 导入导出、PostgreSQL（按用户要求本轮不做）。
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
│  │  ├─ models.py               34 张业务表（对应文档第 7 章与附录 B）
│  │  ├─ security.py             bcrypt / 会话 / 限流 / CSRF
│  │  ├─ routers/                auth、题库、知识、导入、爬虫、待审、复习、统计、图谱…
│  │  ├─ services/               SM-2、导入解析、去重、规则打标、爬虫（GitHub/牛客）、FTS、多维筛选、审核管线…
│  │  ├─ utils/                  归一化 / SimHash / 时区 / SM-2 纯函数
│  │  └─ seed_demo.py            演示数据
│  ├─ config/tag_rules.yaml      规则打标种子
│  ├─ seed/demo_seed.json        35 题 + 22 条知识
│  ├─ alembic/                   迁移（含 FTS5 建表/触发器迁移）
│  ├─ tests/                     15 个测试文件 / 76 个用例
│  ├─ requirements.txt
│  ├─ run.py
│  └─ Dockerfile
├─ frontend/
│  ├─ src/
│  │  ├─ views/                  15 个页面（含知识图谱）
│  │  ├─ components/             侧边栏、TopBar、Modal、LineChart、BarRows、MultiSelect、QualityPanel…
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
| `BAJIU_GITHUB_SSL` | `certifi` | 采集 TLS 校验（GitHub 与牛客共用）：`certifi` / `system`（系统根证书，本机走 TLS 代理时用）/ `none`（仅排障） |
| `BAJIU_AI_BASE_URL` | 空 | M3a：OpenAI 兼容接口地址（如 `https://api.deepseek.com/v1`）；与 Key、模型任一为空即关闭 AI |
| `BAJIU_AI_API_KEY` | 空 | M3a：AI API Key；只从环境变量读取，不落库、不回显 |
| `BAJIU_AI_MODEL` | 空 | M3a：模型名，例如供应商文档中的 chat/completions 模型 ID |
| `BAJIU_AI_TIMEOUT_SEC` | `60` | AI 请求超时（秒） |
| `BAJIU_AI_MAX_INPUT_CHARS` | `8000` | 单次送入 AI 的最大正文字符数，超出会截断 |
| `BAJIU_AI_MAX_OUTPUT_TOKENS` | `2000` | 单次输出 token 上限 |
| `BAJIU_AI_MONTHLY_TOKEN_LIMIT` | `1000000` | 每月 token 预算硬上限；`0` 表示不限制 |
| `BAJIU_AI_CACHE_TTL_DAYS` | `30` | AI 结果缓存天数 |
| `BAJIU_AI_JSON_MODE` | `auto` | `auto`（不支持时自动去掉 response_format）/ `on` / `off` |
| `BAJIU_AI_SSL` | `certifi` | AI 请求 TLS 校验：`certifi` / `system` / `none` |
| `BAJIU_AI_PRICE_INPUT_PER_1K` | `0` | 可选费用估算：每 1K 输入 token 单价 |
| `BAJIU_AI_PRICE_OUTPUT_PER_1K` | `0` | 可选费用估算：每 1K 输出 token 单价 |

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

### 5.5 M2 搜索 / 筛选 / 图谱口径

- **FTS5**：`trigram` 分词，≥3 字查询走 FTS；<3 字（如“握手”）回退 `LIKE`；FTS 异常也自动回退，不抛 500。索引由触发器随增删改同步。
- **多维筛选**：题库/知识库用逗号分隔查询参数，组卷用 JSON 数组；**维度之间 AND、维度内部 OR**，空值/空数组表示不过滤。
- **牛客采集**：必须使用默认爬虫 UA（浏览器 UA 只能拿到 SPA 壳，正文为空）；仅公开帖/sitemap，遵守 `robots.txt`，不支持登录态与付费内容。
- **知识图谱**：知识-知识边为共现边（共享同一道题的题数），知识-题边为 `related / prerequisite / derived_from`；`knowledge_id` 聚焦只返回一跳邻居；无关联数据时回退最近知识条目。

### 5.6 M3a AI 质检口径

- AI 质检只写 `quality_checks`，**不改变待审状态、不修改正式内容**；通过/拒绝仍由人工操作。
- 最新一条记录决定徽标：最新 `success` → 已质检；最新 `failed` → 待人工质检；没有记录 → 未质检。
- 人工质检与 AI 共用 `issues` 结构；人工记录 `model='manual'`、`prompt_version_id` 为空，可随时使用。
- AI 失败记录会保留，可对 failed 记录重试；重试成功新增一条记录，不覆盖历史。
- AI 输入只含题干/答案/要点或知识标题/内容/别名，**不含个人笔记与用户答题原文**。
- 预算按当月 `ai_calls` 的 success/failed token 合计计算；达到上限后拒绝新调用，缓存命中不消耗 token。
- 相关接口：`POST /pending/{id}/quality-check`、`POST /quality/check`、`GET /quality-checks`、`POST /quality-checks/{id}/retry`、`GET /ai/status`。

### 5.7 M3a 增强与 M3b 口径

- **建议与应用分离**：打标、错题解析、答案润色全部先写 `ai_suggestions`；打标应用只合并 `suggested_meta`，润色应用才覆盖题目答案与要点，错题解析只读。失败记录保留 `error_code`，可重新生成。
- **AI 出题**：只能写 `pending_items`，`source_type='ai'`；题干哈希与正式题/待审重复时跳过；审核通过后走正常入库与来源溯源流程。
- **真实模型耗时**（`qwen3.8-max`）：打标 15s、错题解析 60s、润色 43s、出题 40s、面试评分 21–41s、复盘 44s、周报 90s；建议 `BAJIU_AI_TIMEOUT_SEC=120`，周报可设 180。复跑脚本：`python scripts/smoke_m3_ai.py`（建议在演示库副本上运行）。
- **仿真面试评分**：AI 评分只在会话创建时勾选同意后启用；未同意时作答保存为未评分，由用户手动评分。AI 评分失败也会先保存作答，再提示手动评分；报告请求只含题目、评分与反馈，不含作答原文。
- **结束面试回写**：每题评分写入 `mastery_records`（`mode=interview`）并推进 SM-2；低于 3 分自动加入错题本。报告 AI 失败时生成基础报告，不阻塞结束。
- **周报告**：按本地周一至周日统计；同一 `week_start` 覆盖更新；AI 失败自动降级基础版，并在响应中带 `ai_error_code`。
- 相关接口：`POST /ai/suggestions`、`GET /ai/suggestions`、`POST /ai/suggestions/{id}/apply`、`POST /ai/generate-questions`、`POST/GET /interview/sessions`、`POST /interview/sessions/{id}/answers`、`PATCH /interview/sessions/{id}/turns/{turn_id}`、`POST /interview/sessions/{id}/finish`、`POST /interview/sessions/{id}/abort`、`POST/GET /reports/weekly`。

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
- **M2**：FTS5 中英文/短查询回退/增删改同步（`test_fts.py`）、多值筛选维度内 OR 与维度间 AND（`test_filters.py`）、统计热力图/分类掌握度与知识图谱节点边/聚焦（`test_m2_stats_graph.py`）、牛客 URL/robots/HTML 提取/编号问答/任务管线（`test_nowcoder.py` + HTML fixture）。
- **M3a Slice 1**：AI 质检成功、AI 失败转人工、人工质检、重试、未配置降级、隐私输入裁剪、AI 状态不泄露 Key（`test_ai_quality.py`）；网关缓存、429/5xx 重试、Schema 修复、月预算（MockTransport，不访问真实网络）。
- **M3a Slice 2/3**：打标建议成功/失败/应用/重复应用、失败不改建议元数据、答案润色应用、错题解析隐私（默认不含作答与笔记）、AI 出题进待审与重复跳过（`test_m3_suggestions.py`）。
- **M3b**：组卷不下发答案、AI 评分与追问、结束回写错题本与 interview 掌握记录、AI 失败保留作答+手动评分+基础报告、未同意不调用 AI、中止与题量不足、周报告基础版/AI 版/降级覆盖（`test_m3_interview.py`、`test_m3_weekly.py`）。

当前结果：后端 `90 passed`（约 80s），`ruff check app tests` 通过，前端 `npm run build` 与 E2E（含 M3a 建议面板、仿真面试基础报告、周报告）均通过，E2E `problems: []`。

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

覆盖登录、仪表盘、刷题翻答案、今日复习、题库详情、难度多选筛选（行数与行内容、重置恢复）、知识库、导入、采集任务、待审批量选择与人工质检（保存后列表徽标）、统计热力图、知识图谱（点击节点、以此为中心、显示题目节点）、设置页 AI 状态、收藏/错题/冲刺，并断言无浏览器控制台错误。待审为空时自建临时知识候选并在结束时拒绝清理。截图输出到 `frontend/e2e/artifacts/`。如 Edge 不在默认路径，设置 `EDGE_PATH` 环境变量。

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
| 统计复盘 | `/stats`，掌握度/正确率/薄弱点/知识覆盖 + 30 天热力图 + 技术栈掌握度 |
| 知识图谱 | `/graph`，共现力导向图 + 节点详情 + 一跳聚焦 |
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
- 牛客源只支持 `/discuss/<id>` 与 `/sitemap*.xml`；列表页 `/discuss` 是 SPA，无法发现帖子链接。不要改成浏览器 UA（只能拿到 SPA 空壳）。

**SQLite 锁**
- 已启用 WAL、`busy_timeout=5000`、单 worker；避免多个后端进程同时写同一个数据库。

**npm 安装失败**
- 使用 `npm install --registry=https://registry.npmjs.org`，或清理 `node_modules` 后重试。

---

## 11. 安全与合规

- 默认仅监听 `127.0.0.1`；如需局域网访问，请自行加 HTTPS 反向代理。
- 口令 bcrypt 哈希；会话 token 只存 SHA-256 哈希；登录限流。
- CORS 白名单；cookie 模式写操作要求 `X-CSRF-Token`；前端默认使用 Bearer。
- GitHub 源 URL 仅允许 `github.com` / `raw.githubusercontent.com` / `api.github.com`；牛客仅允许 `nowcoder.com` / `www.nowcoder.com` 且仅 https；均拒绝私网/任意主机（SSRF 防护）。
- 爬虫仅抓公开内容、限频、遵守 `robots.txt`、记录来源、不绕过登录/付费；个人学习不商用。
- Markdown/答案以纯文本渲染，不使用 `v-html`；导入文件限制大小/扩展名/MIME。
- AI 默认关闭；配置 Key 后只发送待审/题目/知识正文，不发送个人笔记与用户答题原文；Key 只从环境变量读取，不落库、不回显；AI 输出只作为建议记录，不直接进入正式题库。AI 不可用时自动提示转人工质检，核心流程不受影响。
