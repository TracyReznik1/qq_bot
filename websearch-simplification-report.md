# WebSearch 精简迁移 — 最终交付报告

## 1. 目标与范围

按已批准的规格 `docs/superpowers/specs/2026-08-09-websearch-simplification-design.md`
与实施计划 `docs/superpowers/plans/2026-08-09-websearch-simplification.md`
（Task 1–11），把 qqbot 的证据化网页搜索从 `skip / light / standard / deep`
精简为 `skip / light / standard`，并让检索复杂度、Evidence 时效、回答风险
三者单向解耦。保留 DDGS-first/Tavily 回退、Reader、Evidence admission、
Claim/Citation、绝对 deadline、body-free Trace 等既有可靠性骨架。

工作分支：`codex/ddgs-first-search`（基于 `main` 的 36 个提交）。

## 2. 提交链

| 提交 | 任务 | 内容 |
|---|---|---|
| `a06bcfa` | Task 5 收尾 | EvidenceConflict 契约校验 |
| `4bc2100` | Task 6 | 统一标准档 Repair、repair 后无条件停止 |
| `c3189d8` | Task 7 | 纯函数 answer policy（`src/search/policy.py`） |
| `32b67ca` | Task 8 | Validator 状态 / RenderState 分离，不改写 Evidence |
| `3687435` | Task 9 | Renderer 纯视图化，重接 chat 与 `/search` |
| `6560490` | Task 10 | 删除 deep 与迁移期重复状态 |
| `04df535` | Task 11 | SearchTrace 关闭 + 评估器 2 档 + 文档 + 验收报告 |

累计改动：42 个文件，+11453 / −3209。

## 3. 逐任务进度

- **Task 1–5**（基线冻结、停用 operational deep、拆解 RequestAnalysis 三上下文、
  Planner direct-query/material-topic 契约、主题级 freshness/充分性）：
  已在分支上落库并随 Task 5 收尾提交补齐。核心：`RetrievalDecision` 之外引入
  `RequestAnalysis(retrieval/freshness/risk)`，`RequiredTopic`/`TopicAssessment`/
  `FreshnessEligibility`，以及 `EvidenceConflict` 的“至少两个不同 evidence id /
  至少两个不同断言值”契约。
- **Task 6**：七种封闭 `RepairReasonCode`、`RetrievalStopReason`、
  `EvidenceGapAnalysis`/`RepairPlan`、`QueryTraceEntry`、确定性 budget/stop 门控、
  repair 后 `POST_REPAIR_STOP` 无条件停止；`semantic_query_count`/`repair_query_count`
  由唯一 `query_index` 派生。
- **Task 7**：`src/search/policy.py` 新增纯函数 `decide_answer_state`，把
  `RequestAnalysis` + 不可变 `EvidenceBundle` + `SearchFailureCode` 映射为
  封闭 `AnswerState`（certainty/claim scope/disclosure/warning/validator requirement）。
- **Task 8**：`validate_and_filter` 改收 `answer_state` 并单调降级；新增
  `ValidatorStatus`/`RenderOutcome`/`RenderState`；`build_render_state` 只从保留
  claim 与冲突成员生成引用编号与来源。
- **Task 9**：`render_search_reply(RenderState, *, qq_limit)` 纯视图；文本清理
  （状态/风险提示句）整体移入 `validation.sanitize_visible_block_text`。
- **Task 10**：删除 `SearchTier.DEEP`、`_TIER_RANK`/`max_tier`、
  `_operational_tier`、`LLMRoutingAdvisor` 别名、deep Planner/Provider 分支、
  `Freshness.HIGH`；`RetrievalDecision` 收敛为 4 字段。
- **Task 11**：评估器 2 档（`TIERS=("light","standard")`）、SearchTrace 遗留字段
  关闭、`test_search_evaluation.py` 迁移、README 与 `eval/search/README.md` 更新、
  旧文档标注历史基线、最终验收报告。

## 4. 关键取舍与决策

1. **子代理投递失效 → 直接 TDD 执行。** 本会话宿主层的父→子消息投递缺陷
   （消息正文不进子代理上下文），导致 Task 6 之后的子代理（实现/复核）大多收不到
   任务。Task 6 由子代理完成，Task 7–11 改为我按计划书直接以 TDD 方式实现
   （先 RED 后最小 GREEN、每步全量测试、逐任务单一提交）。这是方法层面的偏离，
   验收口径未变。
2. **低风险“不要联网”改为固定限制提示。** `decide_answer_state` 把
   `USER_FORBID_WEB` 归为 `FIXED`，且计划只允许 `PLAIN` 调普通模型，因此低风险
   no-web 不再调用普通模型补知识，改为固定 no-web 限制 + （高风险时）一次性警告。
   相应更新了 `test_no_web_low_risk_*` 测试。
3. **渲染不再展示 evidence limitation 披露。** 新 `RenderState.disclosure_codes`
   是封闭枚举，不含“证据限制：单来源/弱来源”等 limitations，因此从渲染输出移除。
   这些信息仍保留在 Trace 元数据中。
4. **`ValidationReport` 新增字段放末尾并给默认值。** 为避免一次性破坏约 25 处
   按位置构造，`status/effective_certainty/effective_claim_scope` 放在 dataclass
   末尾且带默认值（后续 Task 9 已整体替换该测试文件）。
5. **Task 9 整体替换 1061 行旧渲染测试。** 旧测试按 `render_search_reply(result,
   report, ...)` 旧 API 编写，改为约 12 个聚焦的纯视图新测试 + 静态归属检查，
   而非逐行迁移。
6. **SearchTrace schema 关闭推迟到 Task 11。** Task 10 只移除了生产代码对这些
   遗留 trace 字段（`trigger_codes/factuality/external_fact_required/
   program_minimum_tier/final_tier`）的赋值；字段定义与序列化、评估器引用一并
   在 Task 11 与评估器 2 档化一起关闭。
7. **删除 deep 专用测试与 legacy 契约测试。** 包括 `PlannerDeepTests`、
   `PlannerDegradationTests` 中的 5 个 deep 用例、orchestrator/evidence 的 4 个
   legacy 测试、router 的 `LLMRoutingAdvisor` 别名测试，以及
   `test_trace_legacy_positional_constructor`（测试的是已删除的位置构造契约）。
8. **评估器 integrity 计数 142 → 214。** 遗留的 checked-in `deep` 行现按计划作为
   迁移/integrity 错误处理（不重写其标签），因此 owner-review/迁移错误总数上升。
9. **Git 提交需授权。** 工作树 `.git` 元数据在沙箱内只读，`commit`/`checkout` 均需
   走 escalate 授权（`git commit` 为非破坏性操作，已按需申请）。

## 5. 验证结果

- 全量测试：`python -B -m unittest discover -s tests -t . -q` → **916 OK**。
- `python -B -m compileall -q src tests` → 退出 0。
- `git diff --check` → 退出 0。
- 静态清理：`SearchTier.DEEP`、`Freshness.HIGH`、`recommended_tier.*deep`、
  `route.*deep` 在 `src/tests/tools` 零命中。
- 结构不变量：`SearchTier` = `{skip,light,standard}`；
  `DEFAULT_TIER_BUDGETS` = `{light,standard}`；
  `RetrievalDecision` = `{route,skip_reason,must_search,reason_codes}`。
- 评估器三门：`integrity` errors=214（非零，预期）；`offline` 非认证；
  `online` exit 2 / not run（无授权，未调用 Provider）。

## 6. 外部门槛（未认证）

140 条评测数据尚未完成 owner 人工复核（其中两条非法 `potential_harm=medium`），
离线 fixture 只能证明评估管线可运行，不能证明真实搜索质量。真实 DDGS/Tavily
在线评测需单独授权、脱敏、人工审查 Query/Evidence/Claim/Citation/失败披露。
本轮只认证架构符合规格、hermetic 行为正确、既有可靠性不变量保留。

## 7. 最终审核结论

对照批准规格逐项核验，无 Critical / Important 阻断：

- 无 operational deep；light 永不 repair；standard 至多一次修复且修复后无条件停止。
- stale/unknown 主题不能产生 SUFFICIENT；Risk/Freshness 只进 Answer Policy/Planner，
  不进 Router 决策。
- Renderer 为纯视图；Answer Policy 与 Validator 无搜索回调。
- Trace 用 `QueryTraceEntry` 元数据，不记录原始 query/正文/URL。

待办：合并决策（本地合并 / 推送 PR / 保持 / 丢弃）尚未执行，`main` 未动。
