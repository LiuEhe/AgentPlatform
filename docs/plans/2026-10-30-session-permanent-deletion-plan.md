# 会话永久删除 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 提供经用户确认的单条会话永久删除，完整处理数据库、附件、前端缓存以及删除中断后的收尾。

**Architecture:** 删除用例由现有 ConversationService 协调；PostgresConversationStore 负责关联记录事务，LocalFileStore 负责安全目录清理和最小落盘凭据。前端仍使用现有 feature 的页面内状态，通过幂等 DELETE 区分完成、附件清理未完成与结果未确认；不增加数据库表、队列、Agent 节点或全局状态库。

**Tech Stack:** Python 3.12/3.13、asyncpg 0.32.0、FastAPI 0.141.1、Vue 3、TypeScript、浏览器原生 dialog、Node 内置测试和 pytest；不新增依赖。

**Spec:** [会话永久删除 Spec](../specs/2026-10-30-session-permanent-deletion-design.md)。执行前同时阅读 Spec、AGENTS.md 及相关治理文档。

**状态：** 已按用户“execute plan”指令实施并通过下方记录的检查；尚未经用户最终验收。开发验证仅使用专用测试库和临时文件，未删除实际用户会话或附件。

## Global Constraints

- 单条永久删除，不提供撤销、回收站、批量删除、清空全部或自动清空旧空白会话。
- “上传、queued/running 或服务端执行仍在收尾的目标会话暂不能删除”。不隐式取消任务。
- “不新增表、不修改外键、不引入任务队列或清理框架。”不改变结构版本、依赖、认证及 Agent 图。
- DELETE 成功为 204 空响应；409 为 CONVERSATION_BUSY；503 区分 CONVERSATION_DELETE_INCOMPLETE 与 STORAGE_UNAVAILABLE；非法 ID 沿用 404。
- “初始化、刷新和 KeepAlive 激活时列表为空，均不自动调用创建接口。”点击新建才创建，首次进入同样适用。
- “保持 origins、credentials、headers 及认证现状不变。”CORS 只增加 DELETE 方法；执行前确认这一具体范围已包含在实施授权中。
- 本地清理凭据只保存版本、agent_id、session_id；不存正文、不扫描附件库孤立文件、不创建常驻清理任务。
- 自动化验证仅使用 `agent_platform_test` 的随机测试 schema 和临时文件目录，不读取或清理实际用户附件。
- 不覆盖用户已有修改；本计划与 Spec 放在可跟踪的 `docs/plans/`、`docs/specs/`，不调整忽略规则。

## Review Focus

1. 终态已落库、执行协程仍持有材料：删除仍须返回 409；由 Task 3 的 `test_delete_rejects_terminal_run_before_task_exit` 固定。
2. DELETE 提交 ACK 丢失且原事务未结束：复核必须等待该事务，确认不存在前不删文件；由 Task 2 的锁测试及 Task 3 的未确认测试固定。
3. 凭据文件名与内容 ID 不一致或凭据目录是 junction：拒绝清理且保留外部文件；由 Task 1 的参数化安全测试固定。
4. 删除非当前会话时，另一个 SSE 正在完成：保留当前回答、草稿与订阅，迟到历史分页不能复活目标；由 Task 6 的并发测试固定。
5. 同一页面先后留下多个未确认/待清理删除：刷新后每个目标均可独立重试，不被最后一个覆盖；由 Task 6 的多目标存储测试固定。

## 文件职责、接口与依赖

| 文件 | 拟变更职责及输入输出 | 调用方/依赖 |
| --- | --- | --- |
| `backend/app/infrastructure/documents/local_file_store.py` | 清理凭据 DTO、校验、落盘/读取/枚举/移除、精确会话目录删除 | 服务；标准库和现有路径防护 |
| `backend/app/schemas/conversation_session.py` | 在既有中立 DTO 模块增加只供删除检查使用的 SessionDeletionTarget | 仓储输出、服务消费；不依赖文件系统或 HTTP |
| `backend/app/infrastructure/conversation/postgres_store.py` | 锁定查询删除目标、事务删除关联行、提交复核 | 服务；既有 asyncpg 连接封装 |
| `backend/app/services/conversation_service.py` | 删除用例、同会话互斥、独立执行句柄、取消/停机、凭据恢复 | 路由/应用生命周期；上述两类基础设施 |
| `backend/app/api/conversations.py`、`backend/app/main.py` | DELETE 空响应、恢复调用和必要 CORS 方法 | HTTP 客户端、FastAPI 生命周期 |
| `frontend/src/api/conversations.ts` | deleteSession 与 204 空响应支持 | composable；现有错误转换 |
| `frontend/src/features/conversation-assistant/types.ts` | 前端删除重试条目的字段定义 | composable、页面；不改变服务端 DTO |
| `frontend/src/features/conversation-assistant/useConversation.ts` | 空态、失效指针、删除状态、目标隔离、导航与重试 | 页面；现有 API/快照 |
| `frontend/src/features/conversation-assistant/ConversationHistory.vue` | 独立删除按钮和事件 | 桌面与移动端页面组合 |
| `frontend/src/views/AgentConversationView.vue` | 原生确认 dialog、提示和空态组合 | composable、历史列表 |
| `frontend/src/style.css` | 仅为新增删除按钮/确认/空态提供必要样式 | 上述 Vue 页面；既有 tokens |
| 现有测试文件及 README/治理文档 | 对应任务的行为验证与现状同步 | 见每项任务 |

不新增源码文件或顶层模块。新增运行时目录仅为 Spec 已描述的附件根下 `.deletions/`；本文增加的 DTO 与样式位置属于现有职责。实际必要文件超出本表时，先说明原因并更新计划，不顺带重构。

任务依赖：Task 1、2 提供基础能力 → Task 3 编排 → Task 4 接口与恢复；Task 5 提供前端 API/空态 → Task 6 删除状态 → Task 7 界面与整体验收。作为一个功能依次交付，后端和前端不拆成独立产品项目。

### Task 1：安全的会话目录清理与本地凭据

**Files:** Modify `backend/app/infrastructure/documents/local_file_store.py`；Test `backend/tests/infrastructure/test_local_file_store.py`。

**Interfaces:** 在现有文件存储模块定义 frozen dataclass `SessionDeletionIntent(version: int, agent_id: str, session_id: str)`，版本固定为整数 1。增加同步方法：

```python
validate_session_deletion(self, agent_id: str, session_id: str) -> None
write_deletion_intent(self, agent_id: str, session_id: str) -> SessionDeletionIntent
read_deletion_intent(self, session_id: str) -> SessionDeletionIntent | None
list_deletion_intents(self) -> list[SessionDeletionIntent]
discard_session(self, agent_id: str, session_id: str) -> None
discard_deletion_intent(self, session_id: str) -> None
```

服务通过 `asyncio.to_thread` 消费这些方法；基础设施不查询数据库、不解释 HTTP。目录路径由允许的 `conversation_assistant` 与规范 UUID 生成，不接受自由路径；不存在的清理目标视作完成。

- [x] **Step 1：编写失败测试。** 复用 tmp_path、现有 stage/publish 与 junction 夹具模式，添加以下测试和断言：
  - `test_session_delete_preserves_other_sessions_and_staging`：目标目录不存在；另一会话原件、解析正文和 `.staging` 哨兵字节不变；重复清理不报错。
  - `test_deletion_intent_roundtrip_and_atomic_write_failure`：JSON 字段恰为 version/agent_id/session_id，version 为 1；模拟原子替换前失败，不出现可被枚举的半份有效凭据，既有完整凭据不被截断。
  - `test_deletion_intent_rejects_invalid_identity`：参数化非法 UUID、额外字段、非整数版本、版本非 1、文件名与正文 ID 不一致、Agent 非白名单；不触碰外部哨兵。
  - `test_session_delete_rejects_directory_links`：覆盖目标、子目录及 `.deletions` 的 symlink/junction，拒绝操作且链接目标字节不变；沿用已有平台条件，不靠删除有效安全用例通过。
  - `test_partial_directory_cleanup_can_resume`：模拟删除部分内容后 IO 错误，第二次调用完成；真实错误不当作文件已缺失吞掉。
- [x] **Step 2：验证红灯。** 在 backend 执行 `uv run pytest tests/infrastructure/test_local_file_store.py -q`；新增测试因能力不存在而失败，既有测试结果保留。
- [x] **Step 3：最小实现上述接口。** `.deletions/<session_id>.json` 使用同目录临时文件、关闭写句柄后 `os.replace`；严格验证字段和路径。枚举仅处理规范 `.json`，非法项记录安全错误类型并保留；单个坏文件不阻止其他有效项，目录本身不可安全访问则抛错交给恢复调用方处理。删除前及实际清理时都复用整树路径校验，不跟随 reparse point。
- [x] **Step 4：验证绿灯。** 重跑上述命令，全部通过。实施时核对本地 Python 的 os.replace/shutil.rmtree 语义，记录源码或官方 API 依据；不增加自行实现的通用文件事务层。
- [x] **Step 5：审查并提交本任务文件。** 建议消息 `feat: add recoverable session file cleanup`；提交前只暂存本任务范围，不能带入已有用户修改。

### Task 2：原子删除关联记录与可等待的提交复核

**Files:** Modify `backend/app/schemas/conversation_session.py`、`backend/app/infrastructure/conversation/postgres_store.py`；Test `backend/tests/infrastructure/test_conversation_postgres.py`。

**Interfaces:** 中立模块增加 frozen dataclass `SessionDeletionTarget(session_id: str, agent_id: str, run_ids: tuple[str, ...], active_run_id: str | None)`。仓储提供：

```python
async def inspect_deletion(self, session_id: str) -> SessionDeletionTarget | None: ...
async def delete_session(self, session_id: str) -> None: ...
```

inspect_deletion 使用新的 read-committed 写事务和 `SELECT ... FOR UPDATE`，等待原会话写事务结束后再返回目标或 None；不通过 repeatable-read 旧快照证明不存在。run_ids 覆盖全部历史运行，供服务检查仍未退出的本地任务。delete_session 自行再次锁行并检查 queued/running，合法且不存在时幂等返回，非法 ID 沿用现有 identifier 的 404。

- [x] **Step 1：编写真实数据库失败测试。** 使用现有 postgres_target 创建随机测试 schema：
  - `test_delete_session_removes_all_owned_rows`：构造两个会话，目标含已完成审核子结果、失败/取消记录和文件引用；删除后六类目标记录计数均为 0，另一会话和 agents 数据不变，结构 version 仍为 2；重复删除不报错。
  - `test_delete_session_rolls_back_all_rows`：在测试 schema 给 chat_sessions 安装仅用于本用例的拒删触发器，在最后一步引发异常；之前的 messages/files/runs/引用/结果仍完整存在。不要靠生产测试钩子注入故障。
  - `test_delete_session_rejects_active_run`：queued/running 均产生 CONVERSATION_BUSY/409，记录数不变；非法 ID 产生 CONVERSATION_NOT_FOUND/404。
  - `test_deletion_confirmation_waits_for_original_transaction`：参数化 commit/rollback；连接 A 锁行并执行删除但尚未结束时，连接 B 的 inspect_deletion 不得完成；A 提交后为 None，回滚后返回原目标。沿用已有 file_confirmation 锁测试的事件/短 wait_for 模式，不用 sleep 猜完成顺序。
- [x] **Step 2：验证红灯。** `uv run pytest tests/infrastructure/test_conversation_postgres.py -k 'delete_session or deletion_confirmation' -q`，确认失败来自缺少接口；没有专用 TEST_DATABASE_URL 时先报告环境缺口，不使用应用库或弱化测试。
- [x] **Step 3：实现两个接口。** 复用 `_connection(write=True)` 和 asyncpg 参数绑定；按 Spec 的依赖顺序在一个事务删除 message_files/agent_calls → messages → files → runs → chat_sessions。不查询正文来拼装删除 SQL，不改 schema、索引或外键。
- [x] **Step 4：验证绿灯。** 重跑该文件全量 `uv run pytest tests/infrastructure/test_conversation_postgres.py -q`；核对 asyncpg 0.32.0 的事务 API 与异常路径，确保复核等待超时时返回不可确认，而不是无记录。
- [x] **Step 5：审查并提交本任务文件。** 建议消息 `feat: delete session history in one transaction`。

### Task 3：删除用例、忙碌判定、取消与恢复

**Files:** Modify `backend/app/services/conversation_service.py`；Test `backend/tests/test_conversation_service.py`、`backend/tests/test_conversation_history_lifecycle.py`。

**Interfaces:** 消费 Task 1/2 接口，新增 `async delete(self, session_id: str) -> None`、`async recover_deletions(self) -> None`；内部执行方法为 `async _delete_session(self, session_id: str) -> None`。新增 `_deletion_tasks: dict[str, asyncio.Task[None]]`，相同 ID 的同时请求等待同一任务。接口不依赖 runtime 是否配置。

- [x] **Step 1：先写用例及故障断言。** 在现有真实仓储/临时目录测试基础上添加：
  - `test_delete_busy_session_has_no_side_effects`：上传、queued/running 均返回 409；会话、附件不变，未写凭据；另一会话仍能操作。
  - `test_delete_rejects_terminal_run_before_task_exit`：控制 runtime 返回前后及终态收尾的事件，在持久状态终态而 `_tasks[run_id].done()` 为 false 时删除仍为 409。
  - `test_delete_failure_boundaries_and_retry`：参数化凭据写失败、SQL 明确回滚、提交 ACK 丢失、复核失败、文件部分失败、凭据移除失败。分别断言是否保留数据库/文件/凭据及准确错误码；复核未知时文件字节必须原样保留；DB 已确认不存在且清理未完必须为 CONVERSATION_DELETE_INCOMPLETE。
  - `test_delete_waiter_cancel_and_shutdown_drain_worker`：用事件阻塞文件线程，取消 HTTP 等待方，独立删除任务仍在；同会话操作锁不提前释放，服务关闭等待线程与任务退出后才关存储。
  - `test_delete_races_with_upload_and_submit`：在同一入口锁上控制两个请求先后；先获锁的一方决定 busy 或 missing，不出现已删除会话新写入或新发布材料。
  - `test_recovery_after_each_delete_boundary`：重新实例化服务模拟写凭据后、DB 提交后、部分文件清理后的进程中断；DB 存在时只去凭据，DB 不存在时收尾；坏凭据/单项 IO 失败不影响其余有效项；DB 不可核实时不删附件。
  - `test_delete_unknown_uuid_does_not_remove_untracked_directory`：合法未知 ID 无凭据时直接完成，即使恰有同名孤立目录也不推测其归属删除。
- [x] **Step 2：验证红灯。** `uv run pytest tests/test_conversation_service.py tests/test_conversation_history_lifecycle.py -k 'delete or recovery_after' -q`；确认新增行为失败，保留失败证据。
- [x] **Step 3：实现编排。** _delete_session 持有 `_active.operation(session_id)`，先查 `_uploads`，再 inspect_deletion，利用 target.run_ids 检查 `_tasks` 未退出情况，禁止只依赖 `_run_sessions`（它可能在任务退出前已被移除）。完成预检/写凭据后执行 SQL；成功或锁定复核确认不存在后清理目录及凭据。delete_session 抛错后统一再次 inspect_deletion，不根据异常文案推断提交结果：None 表示确认已删，仍有目标表示未提交并保留材料、移除多余凭据后返回原存储错误，复核也失败则保留凭据并返回 STORAGE_UNAVAILABLE。仅清理阶段异常映射为 CONVERSATION_DELETE_INCOMPLETE，不把未知提交误报为部分完成。
- [x] **Step 4：实现执行句柄与恢复生命周期。** delete 接纳前检查服务开放状态，创建/复用独立任务后通过 `asyncio.shield` 等待；调用方取消不能取消任务或释放其锁，done callback 消费异常并清理索引。aclose 拒绝新请求后等待已接纳任务，才关闭文件/数据库相关资源；已接纳任务不因关闭标记而被再次拒绝执行。存储运行权丢失仍遵守既有拒写规则，不借删除复核绕过可用性检查。recover_deletions 逐项处理有效凭据，仅数据库确认无记录后删目录；文件目录枚举失败安全记录后退出，数据库启动失败沿用既有失败行为。
- [x] **Step 5：验证绿灯与回归。** `uv run pytest tests/test_conversation_service.py tests/test_conversation_history_lifecycle.py -q`，覆盖既有取消/SSE/额度；确认没有长数据库事务包住文件 IO，线程清理与独立任务退出均被等待。
- [x] **Step 6：审查并提交本任务文件。** 建议消息 `feat: coordinate permanent session deletion and recovery`。

### Task 4：DELETE 接口、启动恢复与 CORS

**Files:** Modify `backend/app/api/conversations.py`、`backend/app/main.py`、`backend/README.md`、`docs/database.md`、`docs/ai-coding/architecture-rules.md`；Test `backend/tests/test_conversations_api.py`、`backend/tests/test_conversation_history_lifecycle.py`。

**Interfaces:** 路由 `async delete_conversation(session_id: str, request: Request) -> Response` 消费 service.delete，返回 `Response(status_code=204)`；lifespan 在 store.initialize/recover_interrupted 完成后、服务开始接收请求前调用 recover_deletions。

- [x] **Step 1：写 HTTP 与生命周期失败测试。** 使用既有 TestClient 和自动数据库隔离：

  ```python
  response = client.delete(f"/api/v1/sessions/{session_id}")
  assert response.status_code == 204
  assert response.content == b""
  assert client.get(f"/api/v1/sessions/{session_id}").status_code == 404
  assert client.delete(f"/api/v1/sessions/{session_id}").status_code == 204
  ```

  再添加 `test_delete_contract_errors_and_no_model`（非法 ID 404、忙碌409、部分完成503专用码、未确认503存储码、无模型仍可删）、`test_delete_cors_preflight_keeps_origin_policy`（已有允许来源预检包含 DELETE，未允许来源仍失败）、`test_startup_recovers_only_admitted_deletions`（服务接收请求前完成有效项，单项 IO 失败不使其他会话不可用）。
- [x] **Step 2：验证红灯。** `uv run pytest tests/test_conversations_api.py tests/test_conversation_history_lifecycle.py -k 'delete or startup_recovers' -q`；预计当前 DELETE 为 405 或缺少恢复调用，不改测试期待掩盖缺口。
- [x] **Step 3：实现路由和装配。** 复用 APIRouter.delete、Response、AppError；allow_methods 精确改为 GET/POST/DELETE/OPTIONS，其余安全设置不动。删除现有响应不引入 JSON DTO；按 Task 3 接口调用启动恢复。
- [x] **Step 4：同步已实现事实。** 后端 README 记录 API/错误/模型独立性；database 文档记录无 schema 变更、显式删除顺序和 `.deletions` 目录/备份边界；架构规则记录服务与文件存储职责，不把未来计划描述成已经实现。
- [x] **Step 5：验证绿灯。** 重跑两文件全量，再运行 `uv run ruff check app tests`；检查空 204、错误结构、启动顺序和 CORS 仅此一项差异。
- [x] **Step 6：审查并提交本任务文件。** 建议消息 `feat: expose session deletion API and startup cleanup`。

### Task 5：前端 DELETE API 与显式新建的空态

**Files:** Modify `frontend/src/api/conversations.ts`、`frontend/src/features/conversation-assistant/useConversation.ts`、`frontend/src/features/conversation-assistant/useConversation.test.cjs`、`frontend/README.md`。

**Interfaces:** API 新增 `deleteSession(id: string, signal?: AbortSignal): Promise<void>`；现有 request<T> 对 204 返回 undefined，其余 JSON 行为保持。initialize 不再创建会话；无有效指针且列表空时 sessionId 为 null，新建由现有 newSession 执行。

- [x] **Step 1：写失败测试。** 沿用现有 TS 编译/Module 加载和 streamApiFixture，不引入测试框架：
  - `delete API accepts an empty 204 response`：真实 request/deleteSession 配合受控 fetch，校验方法 DELETE、URL 编码、signal、结果 undefined；若调用 response.json 就让用例失败。失败响应仍交现有 createApiError 转换，不另写一套业务错误解析。
  - `empty history stays empty across initialization and activation`：多次 initialize/suspend/initialize 后 sessionId 为 null、sessions 空、createSession 调用次数为 0；显式 newSession 后才为 c1。
  - `missing stored session falls back without creating`：明确会话404后选择服务端首屏最近有效项或空态；网络失败仍保留原草稿和可重试状态。
  - `history reload replaces stale summaries without losing cached drafts`：新首屏取代过期列表位置和游标，但未被确认删除的其他会话快照不因未出现在首屏就丢失。
- [x] **Step 2：验证红灯。** frontend 执行 `node --test --test-name-pattern='empty history|missing stored session|history reload|delete API' src/features/conversation-assistant/useConversation.test.cjs`，确认当前隐式创建和 204 解析导致失败。
- [x] **Step 3：实现 API 与初始化分支。** 维持现有 list/get/create 职责，不新增发送时自动建会话。恢复失效指针时仅针对明确的会话不存在错误；不把任意文件/运行404当作会话已删。列表重新初始化取权威首屏并重置 cursor，不把所有旧摘要无条件合并回来。
- [x] **Step 4：迁移既有测试准备，不降低断言。** 当前 fixture 初始化依赖空库自动 create；需要新会话的场景显式 initialize → newSession，测试恢复历史的场景使用 list/get 夹具，重新激活已有会话的场景不额外新建。保留创建计数、幂等 ID、草稿附件、SSE 与取消断言。原“首次连接失败可重试”将失败放在 listSessions 以继续验证初始化重试；创建失败另保留显式新建重试场景。
- [x] **Step 5：验证绿灯并更新 README。** `node --test src/features/conversation-assistant/useConversation.test.cjs` 与 `pnpm build` 全部通过；记录首次/删空后均显式新建的新行为，不误称草稿已持久化。
- [x] **Step 6：审查并提交本任务文件。** 建议消息 `feat: keep empty history until explicit session creation`。

### Task 6：前端删除状态、隔离与可刷新重试

**Files:** Modify `frontend/src/features/conversation-assistant/types.ts`、`frontend/src/features/conversation-assistant/useConversation.ts`、`frontend/src/features/conversation-assistant/useConversation.test.cjs`、`frontend/README.md`。

**Interfaces:** types 定义 `PendingSessionDeletion = { session_id: string; phase: 'unconfirmed' | 'cleanup_pending' }`。composable 新增并返回：

```typescript
deleting: Ref<boolean>
canDelete: ComputedRef<boolean>
pendingDeletions: Ref<PendingSessionDeletion[]>
deletionError: Ref<string>
deleteSession(id: string): Promise<void>       // 页面完成确认后调用
retryDeletion(id: string): Promise<void>       // 仅已有待确认目标，无需再次确认
hasDraft(id: string): boolean                 // 当前草稿或已有快照，不发网络请求
```

使用独立删除 AbortController，不复用关闭当前 SSE 的 controller。新增存储键 `agent-platform-session-deletions`，只序列化上述条目数组，版本/结构校验失败忽略，不包含标题或正文；同 ID 去重，不覆盖其他待处理目标。重试失败提示与现有发送 retryAction 分离，不能触发 send。

- [x] **Step 1：写失败测试。** 扩展 fixture 为 `fixture(overrides = {}, initialStorage = [])`，以 `new Map(initialStorage)` 模拟刷新，并让测试 ApiError 支持 code；不改变生产错误类。添加：
  - `deleting current session restores latest remaining draft`：删除 c1 后恢复 c2 快照草稿/附件，c1 指针/快照/失败切换目标全部失效。
  - `deleting last loaded item reloads server first page`：本地页空但服务器仍有 c3 时打开 c3；服务器真空时 sessionId 为 null、create次数0、cursor重置；列表刷新失败显示加载错误而非空态。
  - `deleting another session preserves active SSE and draft`：不关闭当前订阅，不丢当前输入/附件，当前终态仍正常落入页面。
  - `late history and run callbacks cannot resurrect deleted session`：延迟返回 loadMore/getSession/refreshCompleted/订阅事件，确认被删 ID 不再被 sessions 或快照接收；其他会话更新照常。
  - `deletion outcomes distinguish busy incomplete and unconfirmed`：409保留输入；专用503清除目标内容并保留 cleanup_pending；网络/普通503保留 unconfirmed；同ID重试仅 DELETE，不调用 send/create。
  - `multiple deletion targets survive refresh independently`：两个目标不同 phase 被同一存储数组保留，重新 fixture 恢复后逐个重试；204仅移除本目标。
  - `deletion request serializes page actions`：在 DELETE pending 时重复删除、新建、切换、发送、上传、翻页不发请求；结束后恢复原可用状态。
  - `suspended deletion reconciles on activation`：中止客户端等待仍保留 unconfirmed，激活后可重试；明确会话404清除旧缓存但运行/文件404不误清会话。
- [x] **Step 2：验证红灯。** `node --test --test-name-pattern='delet|resurrect' src/features/conversation-assistant/useConversation.test.cjs`；确认失败对应新状态和隔离缺失。
- [x] **Step 3：实现单次请求与重试条目。** canDelete 要求无 initializing/sending/uploading/deleting；当前活动运行的删除由本地提示或后端409约束，不因当前 SSE 活动而禁止删除另一个空闲目标。请求前保存 unconfirmed，204移除条目并失效目标，专用503更新 cleanup_pending且失效目标；一般失败保留目标以供用户重试，不自动循环重发。
- [x] **Step 4：实现目标失效与导航。** 私有 `invalidateSession(id: string): void` 清目标快照并清除其他快照中指向它的 switch 重试，不丢其他草稿。使用页面内 `deletedSessionIds` 集合过滤该 ID 的迟到摘要，并用独立 `historyVersion` 使删除前历史分页失效；不要为删除非当前项调用 resetRequests 从而终止无关 SSE。仅删除当前会话成功/部分完成时推进当前请求代次、关闭其旧订阅，走 Task 5 的首屏恢复；接收回调仍校验 generation/session/run/subscriptionVersion。
- [x] **Step 5：实现停用/激活处理并同步 README。** 页面停用中止客户端 DELETE 等待但保留本地目标；已知完成结果即使在页面停用时到达，也不得被旧快照覆盖，激活按服务端和待重试条目协调。404需区分会话资源不存在与其他资源缺失；无实时跨标签页广播、无正文存储。
- [x] **Step 6：验证绿灯。** 重跑前端全量 Node 会话测试及 `pnpm build`；额外核对每个新增存储字段仅含ID/phase，GET恢复和删除重试不复用旧发送幂等动作。
- [x] **Step 7：审查并提交本任务文件。** 建议消息 `feat: manage session deletion state and isolated retries`。

### Task 7：确认交互、空态与端到端验收

**Files:** Modify `frontend/src/features/conversation-assistant/ConversationHistory.vue`、`frontend/src/views/AgentConversationView.vue`、`frontend/src/style.css`、`README.md`、`frontend/README.md`、`docs/ai-coding/architecture-rules.md`、`docs/ai-coding/quality-gates.md`；按整体验证发现的问题修改其所属前述文件，不扩展需求。

**Interfaces:** ConversationHistory 增加 `deleteDisabled: boolean` prop 与 `delete: [id: string]` emit；原 disabled 在删除中也置为 true，控制新建/选择/分页。页面用 `requestDeletion(id: string): void` 捕获目标标题/ID并打开原生 dialog，`confirmDeletion(): Promise<void>` 在确认后调用 Task 6 的 deleteSession；取消不调用 composable。两处历史组件使用同一套页面处理函数。

- [x] **Step 1：建立可失败的浏览器验收步骤。** 使用隔离浏览器与受控 HTTP，或专用测试 schema/临时附件启动完整服务。记录当前缺少删除入口时未满足：独立删除按钮、取消零DELETE、确认一次DELETE、默认焦点取消、Esc取消、移动抽屉可用、最后一条后空态。浏览器检查使用一次性测试数据，不加载用户实际会话，不新增浏览器测试依赖。
- [x] **Step 2：实现入口与确认。** 列表项外层改为非按钮容器，打开按钮与删除按钮为兄弟；仅改必要样式。删除按钮始终可被发现、具备 aria-label。确认标题文本渲染，固定提醒“将永久删除此对话、消息和上传文件，无法恢复”，hasDraft 为 true 时补充草稿清除提示；使用 dialog.showModal、取消按钮 focus、cancel/close 事件，不用插入 HTML、嵌套按钮或另加组件库。移动抽屉先收起再打开确认，取消后恢复适当焦点。
- [x] **Step 3：接入状态与空态。** 删除期间禁用 Spec 指定页面操作；pendingDeletions 的条目提供独立重试按钮，cleanup_pending 文案为“对话已删除，附件清理未完成”。无 sessionId 时展示“暂无会话，点击新建对话开始”，现有 composer disabled 与上传状态一致。当前会话仍在运行而删除的是另一项时，输入禁用沿用 busy，但不能关闭该运行订阅。
- [x] **Step 4：重跑浏览器步骤并验证异常。** 桌面/移动/键盘逐项通过；再验证409、部分完成503、网络断开、响应已到但首屏加载失败、刷新恢复、新建恢复输入、标题含HTML字符只作为文字、第二标签页旧指针404恢复。不得把浏览器受控HTTP通过称作真实模型/文件联调通过。
- [x] **Step 5：执行最终检查。** backend 运行 `uv run ruff check app tests`、`uv run pytest`；frontend 运行 `node --test src/features/conversation-assistant/useConversation.test.cjs`、`pnpm build`。真实数据库测试实际运行且通过是删除功能验收要求；环境缺失如实列为未检查，不以跳过代替通过。测试不调用真实模型、RAG 或 Langfuse 删除接口。
- [x] **Step 6：同步文档并作最终差异审查。** 根 README 更新会话管理能力；前端 README和架构规则记录交互/新增仅含ID与phase的存储键/空态，替换现有“仅两个存储键”的过时描述；质量门禁记录删除、凭据恢复与竞态覆盖和浏览器未覆盖边界。核对后端文档与代码的接口、目录和启动顺序一致。执行 `git diff --check` 与范围 diff；schema/锁文件/认证/来源配置不得有无关差异，生成物和测试附件不得进入版本控制。
- [x] **Step 7：交付并提交本任务范围。** 建议消息 `feat: add confirmed session deletion controls`；交付报告列出实现、实际执行检查、未检查和未验收事项。不得仅因测试通过宣称用户已验收，也不自动对现有用户会话执行清理。

## Spec 覆盖自检

| Spec 范围 | 落实任务 |
| --- | --- |
| §1–3 目标、取舍、删除边界与保留内容 | Task 1–3、7 |
| §4.1 入口、确认、可访问性 | Task 7 |
| §4.2 忙碌/互斥/客户端中止 | Task 3、6、7 |
| §4.3 完成/未确认/清理未完及刷新重试 | Task 3–4、6–7 |
| §4.4 显式新建、导航、分页、旧指针/跨标签页 | Task 5–7 |
| §5 DELETE、204、错误与必要CORS | Task 4–6 |
| §6 服务/仓储/文件职责与任务收尾 | Task 2–4 |
| §7 凭据、回滚/未知提交、重试/恢复、文件边界 | Task 1–4 |
| §8–9 模块/文档、官方API复用、零依赖/零结构变更 | 各任务的 Files/Interfaces、Task 1–2核查、Task 4/7文档 |
| §10 检查命令、真实事务、前端/浏览器验收 | 各任务红绿步骤、Task 7最终检查 |
| §11 授权与不操作真实数据 | Global Constraints、Task 7交付 |

## 执行前提与本轮检查

- 执行前确认本计划覆盖了用户认可的 Spec 范围，尤其清理凭据、首次空态和 CORS 仅增加 DELETE；未获实施指令前不修改产品代码。
- 推荐在当前会话直接执行，按上述依赖逐任务推进；这些接口联系紧密，保留完整上下文有利于控制状态与恢复的一致性。执行方式由用户选择，不将写 plan 推断为启动实施。
- 实施使用 superpowers:executing-plans；若用户选择按任务分配代理，则使用 superpowers:subagent-driven-development。无论哪种方式，相关独立审查和完成前验证均保留。
- 文档交付时只检查计划引用、接口命名、任务依赖、Spec覆盖和Markdown格式。本轮不运行功能测试，不把上面的预期 PASS 写成已通过。

## 实施记录（2026-10-30）

上述“执行前提与本轮检查”记录编写计划时的边界；用户后续发出 execute plan，现已实施。任务按接口顺序完成，测试先失败再通过；部分同类故障用例以参数化测试合并命名，验收语义保留。

| 阶段 | 提交/验证证据 |
| --- | --- |
| Task 1 文件清理与凭据 | 9b98901；新增12项先失败，最终文件测试23项通过 |
| Task 2 数据库事务 | 38f534a；新增5项先失败，真实仓储测试文件11项通过；一处新测试行宽修正在Task 3提交 |
| Task 3 服务编排 | c102863；新增服务用例先失败；取消/关闭、上传/提交竞态、重建服务恢复通过 |
| Task 4 HTTP/启动/CORS | 5010126；先验证405、预检400和缺失恢复；相关服务/API/生命周期共64项通过，Ruff通过 |
| Task 5 显式空态与DELETE客户端 | ad23ef6；空态、失效指针、204用例先失败；Node 28项与构建通过 |
| Task 6 前端状态隔离 | 4a8c454；新增7项先失败，Node35项与构建通过 |
| Task 7 UI与最终审查 | 隔离浏览器先确认无入口，再完成桌面、390px移动、键盘、Esc、纯文本标题、409、清理未完重试、网络失败重试、删空刷新零POST和显式新建恢复输入；只使用受控HTTP |

最终独立审查发现两个P2页面生命周期竞态：旧刷新解除新删除互斥；停用后已知删除结果未清目标快照。新增3项回归均先失败，再修复。最终 Node 会话回归 **38 passed**，`pnpm build`通过；全部后端 **434 passed**（实际使用仅连接 agent_platform_test 的任务测试启动器），`uv run --no-sync ruff check app tests`通过。数据库结构、依赖锁文件、认证、来源和凭据策略未变化；无真实用户数据清理，无外部模型或追踪删除。

执行方式调整：按桌面环境规则复用当前干净源码的 dev 检出，不创建额外 worktree；Windows 下用 PowerShell及任务内日志替代Bash记账脚本。代价是实现提交直接留在当前dev；未推送、未合并到其他分支。测试继续使用已安装环境，未安装或升级依赖。

浏览器检查与后端ASGI/真实事务测试分别证明界面行为和持久删除，不将受控页面检查称作真实用户会话联调。用户最终验收仍待完成；真实模型/RAG效果、备份及外部系统擦除不属于此功能验收范围。
