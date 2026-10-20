# 八股文智能复习系统 · 新会话开场文档

> 写给：同项目上一位会话的接替者（下一位开发者或 AI）。
> 最后核实：**2026-10-20（第二轮）**。本文所有断言都在当天对代码 / 数据库 / 测试实测过；没核实的事情会明确写“未核实”。

---

## 0. 30 秒结论

项目 `D:\Program Files\JetBrains\PythonProject\bajiu-review` 是 M1（P0）基线：Vue3 + FastAPI + SQLite，功能闭环能跑，测试全绿。

**上一轮遗留的 A/B/C/E/F 已完成；只剩 D（Docker Compose 实跑）按用户要求暂缓。**

| # | 未完成项 | 状态 |
|---|---|---|
| A | GitHub 爬虫端到端验收 | ✅ 已补 fixture 确定性验收（`tests/test_crawl_acceptance.py`）并对真实仓库 `doocs/advanced-java` 实跑：92/92 文件成功，465 条解析，168 题 / 296 知识进待审 |
| B | 内容门槛（爬虫审核 ≥20 题、≥20 知识、≥20 关联） | ✅ 演示库现有爬虫题 37、爬虫知识 24、全库关联 46 |
| C | 规则打标独立 20 条验收 | ✅ 未参与调规则的样例 19/20 命中；已固化为 `tests/test_tagging_coverage.py` |
| D | Docker Compose 实跑 | ⏸ 用户明确暂缓，配置已就绪 |
| E | CI | ✅ `git init` + 首次提交；`.github/workflows/ci.yml`、`scripts/check.ps1` / `check.sh`、`backend/ruff.toml`、`requirements-dev.txt` |
| F | Markdown XSS、Alembic 自动化等补测 | ✅ XSS 纯文本存储 + 前端无 `v-html` + Alembic 空库迁移；导出回环含关联确认已有测试覆盖 |

**若用户说“继续做项目”**：先确认是否开始 Docker（D）；否则可做内容整理（待审区还有 147 题 / 273 知识待审）或进入 M2。

---

## 1. 当前环境状态（下一位请先确认，可能已变化）

- **后端进程**：本会话在 `127.0.0.1:8000` 启动了 `run.py` 后台进程，环境变量 **`BAJIU_GITHUB_SSL=system`**。
  - 本机 DNS 把 GitHub 域名解析到 `127.0.0.1`（本机 TLS 代理）。代理根证书在 Windows 系统证书库，不在 certifi：**默认 `certifi` 模式会报 `CERTIFICATE_VERIFY_FAILED`**。
  - 启动命令（从 `backend/`）：
    ```powershell
    $env:BAJIU_GITHUB_SSL="system"; & "D:\Program Files\JetBrains\PythonProject\.venv\Scripts\python.exe" run.py
    ```
  - 端口被占用但页面可打开 = 旧进程还活着，**不要直接再起一个**；改后端后先 `taskkill //PID <PID> //F` 再启动。
- **演示数据库**：`backend/data/bajiu.db`，当前 **123 题 / 67 知识 / 46 关联 / 待审 424（150 题 + 274 知识）**。
  - 爬虫来源：`doocs/advanced-java`（真实任务 2：92/92 成功）；`CyC2018/CS-Notes`（种子演示源，任务 1 为 3 个示例文件，不是真跑）。
  - 动手改库前可参考备份：`backend/data/backups/bajiu_pre_crawl_20261020.db`。
- **前端 `dist`**：已重新构建，后端自动托管，单端口 8000 可访问。
- **git**：已初始化并完成首次提交；之后改动可用 `git status` / `git diff` 回看。
- **Docker Desktop 未启动**，按用户要求暂缓。

---

## 2. 运行 / 测试（已验证）

复用工作区 venv：`D:\Program Files\JetBrains\PythonProject\.venv\Scripts\python.exe`（Python 3.13，依赖已装齐，含 ruff）。

```powershell
# 后端 + 单端口前端（先构建前端一次）
cd "D:\Program Files\JetBrains\PythonProject\bajiu-review\frontend"; npm run build
cd ..\backend; & "D:\Program Files\JetBrains\PythonProject\.venv\Scripts\python.exe" run.py

# 测试
cd backend; & "D:\Program Files\JetBrains\PythonProject\.venv\Scripts\python.exe" -m pytest -q
cd ..\frontend; npm run build; npm run e2e

# 一键检查（ruff + pytest + build，可选 E2E）
cd ..; .\scripts\check.ps1            # 或 .\scripts\check.ps1 -WithE2E
```

基线（2026-10-20 第二轮实测）：**后端 54 passed（约 45s）**，`ruff check app tests` 通过，`vue-tsc + vite build` 通过，E2E `problems: []`。

默认账号 `admin / admin123`。

---

## 3. 必须知道的关键约定（改代码前看）

1. **时间**：数据库存 UTC naive；业务日期用 `Asia/Shanghai`。`next_review_date` 等是本地日期字符串 `YYYY-MM-DD`。统一用 `utils/timeutil.py`。
2. **列表序列化走批量预加载**：`services/batch_loader.py` + `serialize_question(..., list_ctx=...)`；新列表接口必须用 `serialize_question_list` / `serialize_knowledge_list`，否则性能测试 SQL 计数会失败。
3. **待审是唯一入口**：待审只在 `pending_items`；精确重复生成 `status='merged'` 审计行，不进队列。导入/爬虫共用 `services/ingest.py`。
4. **规则打标**：`config/tag_rules.yaml` **只在 `tag_rules` 表为空时加载**。改了 YAML 不会自动生效；本会话是清空表后 `load_seed_rules` 重载（现有 63 行规则）。`seed_demo --reset` 会丢演示数据。
5. **测试替身**：`tests/test_api.py::test_crawl_parse_and_dry_run` 的 Fake Client 与 `tests/test_crawl_acceptance.py::FixtureGitHubClient` 都没有真实客户端专属属性；真实客户端逻辑先判空。
6. **演示库 vs 测试库**：pytest 用临时目录，不会动 `bajiu.db`。
7. **前端**：自定义 CSS + SVG，禁用 `v-html`（XSS 防线）；E2E 用本机 Edge。
8. **爬虫取数**：
   - 默认 `certifi` TLS；本机 TLS 代理需 `BAJIU_GITHUB_SSL=system`（仍校验证书，只是换成系统根证书）。`none` 只用于排障。
   - raw 域名连接池绑定 IPv4、socket 层重试、单文件总时限 `5 × timeout_sec`；默认 UA 的源在 `interval_sec < 15` 时不固定等待，自定义 UA 行为不变。
   - 真实仓库实测：`timeout_sec=60`、`interval_sec=1`、`max_files_per_run=100` 时 92 个文件约 1 分钟跑完。
9. **Markdown 解析**：
   - 有 `## 题目：` / `## 知识：` 标记时走结构化解析；`---` 主题分隔线会结束当前块，未知 `**字段**` 收进题目笔记（不要再并入“频率”等字段）。
   - **无标记**时走 `parse_free_markdown`：标题像问题→题（正文为答案），“面试题”小节逐句拆题，其余标题→知识候选，全部低置信度（0.35–0.5），待审区置顶。这把真实文章仓库从“0 条产出”变成可用候选，但会带来较多低质知识候选，需要人工拒绝。

---

## 4. 本轮完成项细节（验收口径）

### A. 爬虫验收

- **fixture 确定性验收**（文档认可的主验收方式）：`tests/test_crawl_acceptance.py`
  - 58 个固定 commit 风格文件 → 92+ 候选题、30+ 知识；
  - 精确去重（跨文件重复 → merged）、失败重试（瞬时失败重试成功、永久 404 记 failed）、部分成功任务状态 `partial`、`max_files` 截断、重试任务复用文件记录、日志与逐文件状态、批量审核 24 题 + 24 知识 + 24 关联；
  - 规则打标在待审 meta 中可展示。
- **真实仓库演示**：`doocs/advanced-java` 的 `docs/` 目录（93 个 md，抓 92 个）：
  - 92/92 成功、0 失败；`crawl_task_files` 逐文件有状态与缓存；
  - 465 条解析（169 题，其中 1 条跨文件重复题进 merged；296 条知识）；
  - 通过待审审核 24 题 + 24 知识，建立 20 条题-知识关联。

### B. 内容门槛（1.3）

- 爬虫题审核通过：37（门槛 20）
- 导入题审核通过：64（门槛 20）
- 知识条目：67（门槛 20）
- 题-知识关联：46（门槛 20）

### C. 规则打标独立验收

- 最终验收样本 20 条（`tests/test_tagging_coverage.py::SET_C`，规则设计阶段未使用），命中 **19/20**，门槛 15/20。
- 规则从 31 行扩到 63 行：Redis、JVM、Java 并发/集合/Spring、MySQL 事务/原理/分库分表、消息队列、限流熔断、微服务、分布式 ID/锁/幂等/理论、K8s、Git、CDN。
- 未命中样例：“如何设计一个短链接系统？”（系统设计题，暂未覆盖；可后续加规则或接受人工打标）。

### E. CI

- `.github/workflows/ci.yml`：backend job（ruff + pytest）、frontend job（npm ci + build），不构建镜像、不跑 E2E。
- 本地：`scripts/check.ps1`（UTF-8 **带 BOM**，PowerShell 5.1 才能正确解析中文）、`scripts/check.sh`。
- `backend/ruff.toml` 只启用 `E4,E7,E9,F,I`；`requirements-dev.txt` 增加 `ruff`。
- 工作区已 `git init` 并首次提交（数据文件、`node_modules`、`dist`、`.env` 均已忽略）。

### F. 补测

- `tests/test_ops.py`：
  - 含 `<script>` 的题目/导入按纯文本存储，导出 Markdown 原样保留；
  - 扫描 `frontend/src/**/*.vue`，不得出现 `v-html` / `innerHTML`；
  - `alembic upgrade head` 在空库建表，且迁移覆盖 ORM 全部表。
- 导出 → 删除 → 再导入回环：已有 `test_export_import_roundtrip` 断言关联 `relation_type` 恢复，本轮确认通过。

---

## 5. 已知弱点（不是 bug，但要知道）

- **启发式解析噪音**：无标记文章的标题会大量变成知识候选（当前 273 条爬虫知识待审），且标题脱离上下文后可能无意义（如“方法二：分治法”已过滤，但仍有“类似快排法”类）。复核时建议按置信度/来源批量拒绝。
- **SimHash 阈值 3 对中文短句太严**：差一个字常差 14+ 位，近似去重主要靠精确哈希生效。设置页可调 `dedupe.simhash_threshold`，或换字符 n-gram。
- **规则打标**：通用主题覆盖已明显提升，但系统设计类（短链接、秒杀架构）仍可能无建议；英文面经命中率更低。
- **真实仓库演示依赖本机代理**：`BAJIU_GITHUB_SSL=system` + 代理可用时正常；CI / 其他网络默认 `certifi` 即可。raw 域名偶发慢（实测 0.4s–22s 波动），重试机制可兜底。
- **错题本导出**：只导出 Markdown，不可回环导入（设计如此）。
- **种子演示数据**：`CyC2018/CS-Notes` 源与任务 1 是演示数据（3 个示例文件），不代表真实采集；真实采集看 `advanced-java` 的任务 2。
- **性能**：500 题 11 条 SQL / 约 36ms 是 TestClient 口径，不是真实浏览器端到端。
- **Windows 终端中文乱码**：显示编码问题，浏览器和 JSON 正常。
- **未覆盖**：数据库 schema 与文档第 7 章逐字段比对、全部 API 与文档第 9 章逐条比对（上一份 HANDOFF 的清单大体可信，但不是验收结论）。

---

## 6. 文件地图（本轮新增 / 改动）

```text
bajiu-review/
├─ .github/workflows/ci.yml        ← 新增：CI（ruff + pytest + 前端构建）
├─ scripts/check.ps1 / check.sh    ← 新增：本地一键检查（ps1 带 BOM）
├─ .env.example                    ← 新增 BAJIU_GITHUB_SSL 说明
├─ README.md                       ← 测试/CI/爬虫解析说明更新
├─ backend/
│  ├─ requirements-dev.txt         ← 新增（ruff）
│  ├─ ruff.toml                    ← 新增
│  ├─ app/config.py                ← GITHUB_SSL_MODE
│  ├─ app/services/crawler.py      ← TLS 模式；IPv4/重试原有
│  ├─ app/services/import_parsers.py  ← 主题分隔线/未知字段修复；parse_free_markdown 启发式
│  ├─ app/routers/knowledge.py     ← 删除无用变量（lint）
│  ├─ app/seed_demo.py             ← 演示任务文件数改为与 3 个示例文件一致
│  ├─ config/tag_rules.yaml        ← 新增 12 条通用主题规则（共 63 行规则）
│  └─ tests/
│     ├─ test_crawl_acceptance.py  ← 新增：5.7 确定性验收
│     ├─ test_tagging_coverage.py  ← 新增：1.3 独立 20 题验收
│     ├─ test_ops.py               ← 新增：XSS / v-html / Alembic
│     ├─ test_parsers.py           ← 新增：分隔线/自由 Markdown 用例
│     └─ …（全量 54 passed）
└─ frontend/                       ← 无代码改动；已重新 build + E2E
```

---

## 7. 新会话开场提示（可直接复制给下一位）

```text
项目在 D:\Program Files\JetBrains\PythonProject\bajiu-review。
请先读 NEW_SESSION_HANDOFF.md（最新状态与未完成项），需要细节时再查 docs/ 下的项目文档 V0.4。
当前：后端 54 passed、ruff 通过、前端 build/E2E 通过；A/B/C/E/F 已完成，只剩 Docker 暂缓。
真实爬虫演示：doocs/advanced-java（92/92 文件，465 条解析）；演示库 123 题 / 67 知识 / 46 关联。
下一步我想做的是：<例如：开始 Docker 实跑 / 整理待审区 / 进入 M2>。
注意：后端 127.0.0.1:8000，admin/admin123；本机跑爬虫要设 BAJIU_GITHUB_SSL=system；改后端后先结束旧 uvicorn；npm 安装用官方 registry；工作区已是 git 仓库，改动可回看。
```
