# 八股文智能复习系统 · M2 对接文档

> 写给：下一位接手的开发者 / AI 会话。
> 最后核实：**2026-10-20**。后端 65 tests、ruff、前端 build、E2E 均在本轮实测通过；牛客单帖与 sitemap 批量采集都做过真实端到端冒烟（采集后已清理数据）；文档、E2E 交互覆盖与 git 提交已收尾。
> M1 的完整背景见 `NEW_SESSION_HANDOFF.md`；本文只覆盖 M2。

---

## 0. 30 秒结论

用户指定的 M2 范围是 **牛客公开页爬虫、FTS5 全文搜索、统计可视化增强、多维筛选增强、知识图谱基础版**；M2 的定时调度、xlsx、PostgreSQL 明确不做。

**这五项已全部落地并有测试/构建验证；交接文档同步、真实 sitemap 批量采集复核、E2E 交互覆盖与 git 提交也已完成（2026-10-20）。M2 可视为交付完成。** 剩余只有 §4 列出的可选增强与用户暂缓的 Docker。

| 功能 | 状态 |
|---|---|
| 牛客公开页爬虫 | ✅ 后端 + UI + API；真实单帖实跑 1 篇 → 解析 9 条；sitemap 批量实跑 5 篇 → 40 条；单测使用 HTML fixture |
| FTS5 全文搜索 | ✅ questions / knowledge 索引 + 触发器同步；题库、知识库、组卷搜索已接入；短查询回退 LIKE |
| 统计可视化增强 | ✅ 近 30 天复习热力图 + 各技术栈掌握度堆叠条 |
| 多维筛选增强 | ✅ 题库/组卷支持分类、标签、公司、难度、频率、来源、掌握度多选；前端 MultiSelect |
| 知识图谱基础版 | ✅ `/graph` 共现图 API + 力导向 SVG 页面 + 聚焦/题目节点 |
| 定时调度 / xlsx / PostgreSQL | ⏸ 按用户要求不实现 |

---

## 1. 当前环境状态（接手先确认）

- **后端正在运行**：`127.0.0.1:8000`，进程 PID **29256**（本轮为跑 E2E 启动）。
  - 启动方式（从 `backend/`）：
    ```powershell
    $env:BAJIU_GITHUB_SSL="system"; & "D:\Program Files\JetBrains\PythonProject\.venv\Scripts\python.exe" run.py
    ```
  - 本机 DNS 指向本机 TLS 代理，`certifi` 会证书校验失败；`system` 模式仍校验证书，只是改用 Windows 根证书。牛客与 GitHub 采集都复用这个配置。
  - 改后端代码后先 `taskkill //PID <PID> //F` 再启动；不要直接起第二个（`WinError 10048`）。
- **演示库**：`backend/data/bajiu.db`，**123 题 / 67 知识 / 46 关联 / 待审 0**。
- **前端 dist**：已用本轮代码构建，后端单端口托管。
- **git**：M2 全部改动已提交，工作区干净（交付提交见 `git log` 最新一条）。
- **Docker** 仍未实跑（用户暂缓）。

---

## 2. 本轮完成内容

### 2.1 牛客公开页爬虫（`nowcoder`）

**关键事实**：牛客对爬虫 UA 返回服务端渲染的完整 HTML（约 172KB），对浏览器 UA 反而返回 SPA 壳（约 6KB）。因此**不需要 Playwright**，用 httpx + 爬虫 UA 即可拿到正文；文档里“动态页用 Playwright”在本场景不是必需。

- 新文件 `backend/app/services/nowcoder.py`：
  - 源 URL 支持：
    - 帖子：`https://www.nowcoder.com/discuss/<id>`
    - sitemap：`https://www.nowcoder.com/sitemap*.xml`（自动筛出 `/discuss/<id>`；索引文件会再取一层，最多 5 个子 sitemap）
    - 列表页 `/discuss` 是 SPA，服务端无帖子链接，**明确拒绝并提示改用帖子或 sitemap**。
  - 域名白名单 `nowcoder.com / www.nowcoder.com`，仅 https。
  - 遵守 `robots.txt`：拉取并缓存 1 小时，命中 Disallow 直接失败（`CRAWL_DISALLOWED`）。
  - 正文提取：`content-post-title` 的 h1 → 标题；`nc-slate-editor-content` 内嵌 HTML → 用 `HTMLParser` 转 Markdown（保留标题/列表/代码块）；失败时回退 `richText` JSON 字段。
  - 编号问答抽取：`**1.** 题干 … **答案：…**` 形式（笔试/选择题常见）转成题目候选，答案为空时置信度 0.4。
  - 每个帖子仍走 `parse_markdown` 的启发式，知识条目来自正文小标题。
- `backend/app/services/crawler.py`：
  - `run_task` 按 `source_kind` 分派；新增 `_run_nowcoder()`，复用逐文件状态、重试、缓存、日志、入库管线。
  - 牛客每篇之间至少 sleep 1 秒（遵守源配置间隔）。
- API/UI：
  - `POST /api/v1/crawl/sources` 接受 `source_kind=nowcoder`，创建/改 URL 时走牛客校验。
  - `POST /api/v1/crawl/sources/{id}/run` 不再只允许 GitHub。
  - 前端 `CrawlView.vue` 新增“来源类型”选择、牛客 URL 提示、默认间隔/超时；源卡片显示类型并允许运行。
- 验证：
  - 真实帖子 `https://www.nowcoder.com/discuss/931015704499802112` 通过 API 实跑：任务 1/1 成功，解析 9 条（5 题 + 4 知识）；验证后已删除测试源与待审数据。
  - `tests/test_nowcoder.py` + `tests/fixtures/nowcoder_post.html` 覆盖 URL 校验、robots、HTML 提取、编号问答、任务管线。

**限制**：只支持公开帖/ sitemap；不支持登录态、付费内容、列表页动态加载；sitemap 索引只递归一层。

### 2.2 FTS5 全文搜索

- 新文件 `backend/app/services/fts.py`：
  - `question_fts(stem, answer, notes)`、`knowledge_fts(title, content, aliases)`，使用 `tokenize='trigram'`（中文按 3 字窗口，支持中文子串）。
  - 独立 FTS 表 + 触发器（insert/update/delete）自动同步；启动时补齐历史数据。
  - `ensure_fts(engine, force=True)` 在 `init_db()` 中调用；备份恢复会走 `init_db()`，因此恢复后索引自动重建（未单独写测试）。
  - 查询函数：`search_question_ids` / `search_knowledge_ids`，返回 `None` 表示应回退 LIKE。
    - **<3 字的查询**（如“握手”）直接回退 LIKE；trigram 无法命中。
    - 旧 SQLite 不支持 trigram 时自动退回 unicode61（中文搜索会退化，英文正常）。
  - `rebuild_fts(db)` 供需要时手动重建。
- 接入位置：
  - `GET /questions?q=`：FTS 命中题干/答案/笔记，同时保留标签 LIKE 命中。
  - `GET /knowledge?q=`：FTS 命中标题/内容/别名。
  - `POST /practice/quiz` 的 `q`。
- 迁移：`backend/alembic/versions/9f1c2d3e4a5b_fts5_search.py`（建表、触发器、回填）。
- 测试：`tests/test_fts.py`（中文/英文/短查询、更新/删除同步、表存在）。

### 2.3 统计可视化增强

- 后端 `services/review.py` 新增：
  - `review_heatmap(db, days, category_id)`：按本地日期统计每日自评次数与正确率，返回连续 N 天（含 0 值）。
  - `category_mastery(db, category_id)`：按二级分类汇总精通/熟悉/不熟/未学，最多 10 行。
- 新端点：
  - `GET /api/v1/stats/review-heatmap?days=30&category_id=`
  - `GET /api/v1/stats/category-mastery?category_id=`
- 前端 `StatsView.vue`：
  - 近 30 天复习热力图（5 档颜色 + tooltip）。
  - 各技术栈掌握度堆叠条（含图例）。
  - 原有掌握度分布、7 天正确率、不熟知识点、知识覆盖保留。
- 测试：`tests/test_m2_stats_graph.py::test_review_heatmap_and_category_mastery`。

### 2.4 多维筛选增强

- 新文件 `backend/app/services/filters.py`：统一多值筛选，**维度之间 AND、维度内部 OR**。
- 题库 `GET /questions` 新增（逗号分隔）：
  - `category_ids`、`tag_ids`、`company_ids`、`difficulties`、`frequencies`、`sources`、`masteries`
  - 旧单值参数保持不变。
- 知识库 `GET /knowledge` 新增：`category_ids`、`kinds`。
- 组卷 `POST /practice/quiz` 新增数组字段：`category_ids/tag_ids/company_ids/difficulties/frequencies/sources/masteries`。
- 前端：
  - 新组件 `src/components/MultiSelect.vue`（复选面板、摘要、清空）。
  - `LibraryView.vue`：难度/频率/来源/掌握度/标签/公司全部改为多选，新增“重置”。
  - `PracticeView.vue`：同样改为多选，标签/公司选项从 `/tags`、`/companies` 加载。
- 测试：`tests/test_filters.py`（单维度 OR、跨维度 AND、分类多选、掌握度、组卷）。

### 2.5 知识图谱基础版

- 新路由 `backend/app/routers/graph.py`：
  - `GET /api/v1/graph?knowledge_id=&category_id=&include_questions=&limit=`
  - 节点：知识条目（按关联题数排序，上限 `limit` 10–150，默认 50）；`include_questions=true` 时附加题目节点（掌握度）。
  - 边：
    - 知识-知识：共享同一道题的**共现边**，`weight` = 共现题数（`co_occurrence`）。
    - 知识-题：`related / prerequisite / derived_from`。
  - 指定 `knowledge_id` 时返回它的一跳邻居（共享题目的知识）。
  - 没有关联数据时回退到最近更新的知识条目，页面不会空白。
- 前端 `src/views/GraphView.vue`：
  - 同步力导向布局（斥力 + 弹簧 + 向心，260 轮）绘制 SVG。
  - 点击节点查看详情；“以此为中心”按知识聚焦；“显示题目节点”切换；30/50/80/120 上限。
  - 路由 `/graph`，侧边栏“分析与设置 → 知识图谱”。
- 测试：`tests/test_m2_stats_graph.py::test_knowledge_graph_nodes_edges_and_focus`。

---

## 3. 验证基线（2026-10-20 实测）

```powershell
# 后端
cd "D:\Program Files\JetBrains\PythonProject\bajiu-review\backend"
& "D:\Program Files\JetBrains\PythonProject\.venv\Scripts\python.exe" -m ruff check app tests
& "D:\Program Files\JetBrains\PythonProject\.venv\Scripts\python.exe" -m pytest -q

# 前端
cd ..\frontend
npm run build
npm run e2e
```

结果：

- 后端 **65 passed**（约 56s），ruff 全绿。
- 前端 `vue-tsc + vite build` 通过。
- E2E `problems: []`，覆盖：统计热力图 `.heatmap`、知识图谱渲染、**难度多选交互**（123 条 → 单选 5 条 → 双选 37 条 → 重置回 123 条，并校验结果行难度）、**图谱点击节点/以此为中心/显示题目节点**。
- E2E 在待审为空时会临时创建 2 条知识候选，测试结束调用 reject 清理（会留下 `rejected` 审计行，不影响待审）。
- **sitemap 批量复核（2026-10-20 实测）**：源 `https://www.nowcoder.com/sitemap1.xml`、`max_files_per_run=5`、`interval_sec=2` → 发现 5 篇、5/5 成功、解析 40 条（5+9+4+15+11）、待审 40；删除源后待审回 0，任务行/缓存目录已清理。sitemap1.xml 当前含 13737 个 loc（1005 个 `/discuss/<id>`），URL 会规范化为不带查询串的帖子地址。
- E2E 曾依赖“待审队列非空”，已修复为自给自足；清空待审后 E2E 曾失败是历史问题。

---

## 4. 收尾结果与可选增强

**已完成的收尾（2026-10-20）：**

1. ✅ **git 提交**：M2 全部改动已提交（见 §1 的最新提交号）。
2. ✅ **README / NEW_SESSION_HANDOFF 同步**：README 已补 M2 五项、65 tests、M2 搜索/筛选/图谱口径与 API；NEW_SESSION_HANDOFF 已改为“M1 + M2 指定范围已完成”。
3. ✅ **牛客 sitemap 批量采集复核**：`sitemap1.xml` + `max_files_per_run=5` → 5/5 成功、40 条解析；测试源与待审数据已删除。生产前仍建议保持 `interval_sec ≥ 2`（代码下限 1 秒），不要一次抓全站。
4. ✅ **E2E 交互覆盖**：难度多选的行数/行内容/重置断言；图谱节点点击、聚焦、显示题目节点断言。

**仍可做（不属于本轮验收）：**

5. **性能与边界**：
   - FTS 在 5000 题规模未压测；图谱在节点≥120、边数很多时布局与接口耗时未测。
   - `limit` 上限 150，若需要更大图谱要分页/聚类。
6. **可选增强**：
   - 知识图谱目前只有“共现边”，没有知识-知识手工关系表；如需“前置知识”图谱，需新增 `knowledge_relations` 表与维护 UI。
   - 统计可继续加标签/公司维度、掌握度趋势；热力图目前只统计自评记录。
7. **Docker**：仍按用户要求暂缓。

---

## 5. 实现约定与坑（M2 新增）

1. **FTS 启动顺序**：`init_db()` 先 `create_all` 再 `ensure_fts(force=True)`。测试会重建数据库文件，`ensure_fts` 的模块级 `_READY` 会被 `force=True` 绕过；不要改成普通调用，否则第二个测试起 FTS 表不存在。
2. **FTS 查询**：trigram 需要 ≥3 字；2 字中文查询走 LIKE。FTS 查询异常时自动回退 LIKE，不抛 500。
3. **FTS 表不在 ORM 里**：`Base.metadata` 看不到 `question_fts/knowledge_fts`；Alembic 用单独迁移维护。`tests/test_ops.py::test_alembic_upgrade_from_empty_database` 的“迁移覆盖 ORM 全部表”不受影响。
4. **多选筛选**：查询参数是逗号分隔字符串，组卷是 JSON 数组；空数组/空串表示不过滤。维度内 OR、维度间 AND。
5. **牛客 UA**：不要为了“像浏览器”改默认 UA——浏览器 UA 会拿到 SPA 壳导致正文为空。默认 `InterviewReviewBot` 才有 SSR HTML。
6. **牛客 robots**：`/discuss` 与 sitemap 允许；`/search`、`/nccommon` 等被禁。改动 URL 类型时先看 `parse_nowcoder_source`。
7. **牛客任务日志**：每篇帖子解析数 = 题 + 知识；编号问答可能没有答案（置信度 0.4），待审时要人工补。
8. **图谱 API**：`knowledge_id` 聚焦时只返回一跳邻居；`category_id` 会先按分类过滤知识再取图；没有数据时回退最近知识条目。
9. **图谱前端布局是同步计算**：节点多时首屏可能卡顿；超过 120 节点建议先降 `limit` 或后续改成 Web Worker。
10. **E2E 临时数据**：smoke 会创建 `E2E 待审条目*` 知识并 reject；如果中途失败，可能留下 pending 行，需手动清理（本轮已清理一次）。
11. **TLS**：牛客与 GitHub 共用 `BAJIU_GITHUB_SSL`（`system` 适配本机代理）；默认 `certifi` 在普通网络可用。
12. **服务器进程**：本轮启动的后端 PID 29256；新会话可能已变化，先 `netstat -ano | grep ':8000'`。

---

## 6. 文件地图（M2 新增 / 修改）

```text
bajiu-review/
├─ backend/
│  ├─ alembic/versions/9f1c2d3e4a5b_fts5_search.py   ← 新增：FTS 迁移
│  ├─ app/
│  │  ├─ database.py                 ← init_db 调用 ensure_fts(force=True)
│  │  ├─ main.py                     ← 注册 graph 路由
│  │  ├─ schemas.py                  ← QuizRequest 多维字段
│  │  ├─ routers/
│  │  │  ├─ crawl.py                 ← nowcoder 校验/运行
│  │  │  ├─ graph.py                 ← 新增：知识图谱 API
│  │  │  ├─ knowledge.py             ← FTS + category_ids/kinds
│  │  │  ├─ practice.py              ← FTS + 多维筛选
│  │  │  ├─ questions.py             ← FTS + 多维筛选
│  │  │  └─ stats.py                 ← heatmap / category-mastery
│  │  ├─ services/
│  │  │  ├─ crawler.py               ← 按 source_kind 分派 + _run_nowcoder
│  │  │  ├─ filters.py               ← 新增：多值筛选
│  │  │  ├─ fts.py                   ← 新增：FTS5 索引与查询
│  │  │  ├─ nowcoder.py              ← 新增：牛客客户端/解析
│  │  │  └─ review.py                ← 热力图 / 分类掌握度
│  │  └─ tests/
│  │     ├─ test_fts.py              ← 新增
│  │     ├─ test_filters.py          ← 新增
│  │     ├─ test_m2_stats_graph.py   ← 新增
│  │     ├─ test_nowcoder.py         ← 新增
│  │     ├─ fixtures/nowcoder_post.html ← 新增
│  │     └─ test_ops.py              ← subprocess 输出 UTF-8 修正
└─ frontend/
   ├─ e2e/smoke.mjs                  ← 待审为空时自建临时数据；图谱/热力图断言
   └─ src/
      ├─ api/types.ts                ← M2 类型
      ├─ components/AppSidebar.vue   ← 知识图谱入口
      ├─ components/MultiSelect.vue  ← 新增
      ├─ router/index.ts             ← /graph
      └─ views/
         ├─ CrawlView.vue            ← 牛客源
         ├─ GraphView.vue            ← 新增
         ├─ LibraryView.vue          ← 多维筛选
         ├─ PracticeView.vue         ← 多维筛选
         └─ StatsView.vue            ← 热力图 + 技术栈掌握度
```

---

## 7. 新会话开场提示（可直接复制）

```text
项目在 D:\Program Files\JetBrains\PythonProject\bajiu-review。
请先读 M2_HANDOFF.md（M2 进度、已完成功能、可选增强与坑），M1 背景见 NEW_SESSION_HANDOFF.md。
当前：M2 指定的五项（牛客爬虫、FTS5、统计增强、多维筛选、知识图谱基础版）已实现并提交；
后端 65 tests、ruff、前端 build/E2E 通过；工作区应为干净状态。
下一步我想做的是：<例如：开始 Docker 实跑 / 知识关系表与图谱增强 / FTS 与图谱性能压测 / 内容扩充>。
注意：后端 127.0.0.1:8000（admin/admin123）；本机爬虫要设 BAJIU_GITHUB_SSL=system；
牛客必须用爬虫 UA（浏览器 UA 只能拿到 SPA 壳）；FTS 短查询会回退 LIKE；改后端后先结束旧 uvicorn。
```
