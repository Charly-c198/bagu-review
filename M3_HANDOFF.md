# 八股文智能复习系统 · M3a Slice 1 交接

> 最后核实：**2026-10-20**。后端 76 tests、ruff、前端 build/E2E 均实测通过。
> M1/M2 背景见 `NEW_SESSION_HANDOFF.md` / `M2_HANDOFF.md`；本文只覆盖 M3a Slice 1。

---

## 0. 30 秒结论

M3a 已按“AI + 人工双通道”落地第一刀：**AI 网关、题目/知识质量审查、人工质检兜底、失败转人工、重试、缓存、预算、用量状态**。AI 配置全部走环境变量，未配置时人工质检完整可用，核心流程不受影响。

| 能力 | 状态 |
|---|---|
| AI 网关（OpenAI 兼容） | ✅ 重试、JSON 模式降级、Schema 校验 + 一次修复 |
| 质量审查（AI） | ✅ 待审 / 题目 / 知识条目手动触发，只写建议 |
| 人工质检 | ✅ 与 AI 共用 `issues` 结构，始终可用 |
| 失败降级 | ✅ 失败落 `quality_checks(status=failed)`，前端“待人工质检”+ 重试 |
| 缓存 / 成本 / 预算 | ✅ `ai_cache`、`ai_calls`、月 token 上限 |
| UI | ✅ 待审徽标/问题面板/人工表单；题目与知识详情入口；设置页 AI 状态 |
| 自动打标 / 错题解析 / 答案润色 | ⏭ 下一 Slice |
| 题目生产 / 仿真面试 / 周报告 | ⏭ M3b |

---

## 1. 配置（Key 由使用者自己填）

在项目根目录 `.env` 或环境变量中设置：

```ini
BAJIU_AI_BASE_URL=https://你的供应商/v1
BAJIU_AI_API_KEY=你的-key
BAJIU_AI_MODEL=你的模型名
```

可选：`BAJIU_AI_TIMEOUT_SEC`、`BAJIU_AI_MAX_INPUT_CHARS`、`BAJIU_AI_MAX_OUTPUT_TOKENS`、`BAJIU_AI_MONTHLY_TOKEN_LIMIT`、`BAJIU_AI_CACHE_TTL_DAYS`、`BAJIU_AI_JSON_MODE`、`BAJIU_AI_SSL`、`BAJIU_AI_PRICE_INPUT_PER_1K`、`BAJIU_AI_PRICE_OUTPUT_PER_1K`。完整说明见 `.env.example` 与 README 配置表。

- 三项任一为空 → `configured=false`，AI 按钮调用会得到 `AI_NOT_CONFIGURED`，并自动落一条失败质检记录，引导人工质检。
- Key 只从环境变量读取，不写数据库、不出现在 `/api/v1/ai/status`。
- 本机若有 TLS 代理，AI 请求可设 `BAJIU_AI_SSL=system`。

---

## 2. 使用流程

1. **待审详情** → “质量审查” → `AI 质检`。
2. 成功：显示整体风险、问题列表（类型/严重度/证据/建议/置信度），列表出现“质检 低/中/高风险”徽标。
3. 失败：显示“待人工质检”+ 错误原因；可直接点“人工质检”填写同结构表单，或“重试 AI”。
4. **题库详情 / 知识详情** → “AI 质量审查” → 同样支持 AI / 人工。
5. **设置 → AI 能力（M3a）**：查看是否配置、模型、本月 tokens/调用/缓存命中、Prompt 版本。

AI 质检不改变待审状态、不修改正文；通过/拒绝/编辑仍是人工操作。

---

## 3. 接口

```text
POST /api/v1/pending/{id}/quality-check   body: {mode:"ai"|"manual", issues?, overall_risk?, summary?}
POST /api/v1/quality/check                body: {target_type, target_id, mode, ...}
GET  /api/v1/quality-checks               ?target_type=&target_id=&status=&page=&page_size=
GET  /api/v1/quality-checks/{type}/{id}   最近记录
POST /api/v1/quality-checks/{id}/retry    仅 failed 的 AI 记录
GET  /api/v1/ai/status                    配置与用量（不含 Key）
```

错误码：`AI_NOT_CONFIGURED` / `AI_UNAVAILABLE` / `AI_SCHEMA_INVALID` / `AI_BUDGET_EXCEEDED`。失败响应 `data.check` 会带回刚落库的失败记录。

---

## 4. 数据表与迁移

- `ai_prompt_versions`：prompt 版本、模板、JSON Schema。
- `ai_calls`：用途、模型、输入/输出 token、费用估算、耗时、状态、错误码；不存原文。
- `ai_cache`：内容哈希缓存，默认 30 天。
- `quality_checks`：`target_type(question/knowledge/pending)`、状态、issues JSON、整体风险、总结、model、prompt 版本、错误码、人工复核时间。
- 迁移：`alembic/versions/c3d4e5f6a7b8_m3a_ai_quality.py`（down_revision `9f1c2d3e4a5b`）。

演示库已执行：`alembic stamp 9f1c2d3e4a5b` → `alembic upgrade head`（历史库由 create_all 创建、没有 alembic_version）。

---

## 5. Prompt 与安全

- Prompt 文件：`backend/prompts/quality_check/v1.md` + `v1.schema.json`；改 prompt 必须升版本号，数据库记录模板内容。
- 输入只含题干/答案/要点或知识标题/内容/别名；**不含个人笔记、用户答题原文**。
- 输出经 Pydantic 校验；不合格先修复一次，仍失败记 `AI_SCHEMA_INVALID`。
- 上游错误重试 2 次（429/5xx/超时）；401/403/404 不重试。
- 外部调用前提交读事务，避免 SQLite 锁被慢请求拉长。

---

## 6. 验证基线

```powershell
cd "D:\Program Files\JetBrains\PythonProject\bajiu-review\backend"
& "D:\Program Files\JetBrains\PythonProject\.venv\Scripts\python.exe" -m ruff check app tests
& "D:\Program Files\JetBrains\PythonProject\.venv\Scripts\python.exe" -m pytest -q

cd ..\frontend
npm run build
npm run e2e
```

结果：后端 **76 passed**（约 65s），ruff 全绿；前端 build 通过；E2E `problems: []`（新增待审人工质检与设置页 AI 状态断言，不依赖真实 Key）。

---

## 7. 文件地图（Slice 1 新增 / 修改）

```text
backend/
├─ prompts/quality_check/v1.md / v1.schema.json   ← 新增：质检 prompt 与 Schema
├─ alembic/versions/c3d4e5f6a7b8_m3a_ai_quality.py ← 新增：4 张 AI 表
├─ app/
│  ├─ config.py                    ← AI_* 环境变量
│  ├─ models.py                    ← ai_prompt_versions / ai_calls / ai_cache / quality_checks
│  ├─ schemas.py                   ← 质检请求模型
│  ├─ main.py                      ← 注册 ai / quality 路由
│  ├─ routers/ai.py                ← 新增：AI 状态
│  ├─ routers/quality.py           ← 新增：AI/人工质检、历史、重试
│  ├─ routers/pending.py           ← 待审列表/详情附 quality 摘要
│  └─ services/ai/
│     ├─ gateway.py                ← OpenAI 兼容网关、缓存、预算、重试
│     ├─ prompts.py                ← prompt 加载与版本登记
│     └─ quality.py                ← 质检输入、AI/人工记录、摘要
└─ tests/test_ai_quality.py        ← 新增：11 项
frontend/
├─ src/components/QualityPanel.vue ← 新增：质检面板 + 人工质检表单
├─ src/views/PendingView.vue       ← 徽标 + 详情入口
├─ src/views/LibraryView.vue       ← 题目详情入口
├─ src/views/KnowledgeView.vue     ← 知识详情入口
├─ src/views/SettingsView.vue      ← AI 状态卡片
├─ src/api/types.ts                ← 质检/AI 类型
└─ e2e/smoke.mjs                   ← 人工质检 + AI 状态断言
```

---

## 8. 下一步（按已确认路线）

1. **Slice 2：自动打标建议**——待审详情“AI 建议”，规则建议与 AI 建议分开显示，用户应用后才写 `suggested_meta`。
2. **Slice 3：错题解析 + 答案润色**——生成建议，用户确认后保存；默认不发送用户答案。
3. **M3b**：题目生产 → 文字仿真面试 → 周报告。
4. ✅ **真实模型冒烟（2026-10-20）**：OpenAI 兼容端点 + `qwen3.8-max`，质量审查 API 返回 `success`（约 32s，1 个低严重度 issue），二次相同请求命中缓存（0.0s）。推理型模型延迟较高，质量审查建议把 `BAJIU_AI_TIMEOUT_SEC` 调到 120；当前 60 也能完成，但高峰期余量偏小。

## 9. 新会话开场提示

```text
项目在 D:\Program Files\JetBrains\PythonProject\bajiu-review。
请先读 M3_HANDOFF.md（Slice 1 状态、AI 配置、接口与坑），M1/M2 见 NEW_SESSION_HANDOFF.md / M2_HANDOFF.md。
当前：M3a Slice 1 已完成（AI 网关 + 质量审查 + 人工质检双通道）；后端 76 tests、ruff、build/E2E 通过。
下一步：Slice 2 自动打标 / Slice 3 错题解析与润色 / M3b。
注意：AI 配置只走环境变量；未配置时人工质检必须保持可用；AI 输出只进建议记录。
```
