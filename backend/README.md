# 智能体平台后端

基于 Python 3.12/3.13、FastAPI、LangChain、LangGraph 和 RAGFlow 的制度审核与会话服务。独立审核接口同步返回报告；会话助手通过意图识别决定普通回答、追问或调用现有制度审核，异步运行并通过 SSE 推送普通回答增量、真实阶段与最终结果。会话历史依赖 PostgreSQL 18 与 asyncpg 0.32.0，不依赖 Redis。

## 会话助手与持久历史

上传为可选步骤：无文件直接发消息，也可上传 DOCX 或将正文粘贴为用户消息。普通聊天、制度概念解释和摘要仅调用聊天模型，明确制度审核意图且参数齐全才执行子智能体。缺少审核方式、草稿或标准角色时先追问，用户转移话题时清除待补齐任务。只接入 `institution_review`，不新增工作汇总、报告生成 Agent。

`conversation_assistant/graph/` 使用 LangGraph 表达材料准备、上下文选择、结构化意图识别、参数门控及回复/子调用分支。`ConversationService` 只负责会话用例、任务生命周期和 HTTP 映射；`infrastructure/conversation/postgres_store.py` 保存中立会话记录，`active_runs.py` 只管理活动通知与临时文本。业务图状态与存储分开，未接入 checkpointer。

上传阶段调用 `nodes/document/parse.py` 并复用既有 DOCX 转换器，聊天不重复解析。通用输入预算由 `nodes/llm/context.py` 处理，材料选择策略留在会话 Agent；模型上下文最多 24000 个序列化字符，历史审核结果仅带最多 4000 字符片段，审核始终使用独立保留的完整原文。父子调用通过同一个 `AgentRuntime`，制度审核图在启动时构建并复用。

以下路径沿用 `api_prefix`（默认 `/api/v1`）：

| 方法与路径 | 行为 |
| --- | --- |
| `GET /api/v1/agents` | 读取数据库中的 agent_id/name/description；不授予执行能力 |
| `POST /api/v1/sessions` | 创建持久会话，返回 201 |
| `DELETE /api/v1/sessions/{session_id}` | 永久删除空闲会话及关联消息、结果和附件；空 204 表示全部完成，重复请求幂等 |
| `GET /api/v1/sessions/{session_id}?after_sequence=0` | 读取 session_id、消息 message_id 和文件元数据，支持按消息序号增量获取 |
| `POST /api/v1/sessions/{session_id}/files` | multipart 字段 `file` 上传一份 DOCX，返回 file_id/original_name/size_bytes/content_chars/created_at，不暴露路径；不自动触发审核 |
| `POST /api/v1/sessions/{session_id}/messages` | JSON `{client_message_id, content, file_ids: []}`，返回 202 及 run_id |
| `GET /api/v1/sessions/{session_id}/runs/{run_id}` | 查询 queued/running/succeeded/failed/cancelled 及结果 |
| `GET /api/v1/sessions/{session_id}/runs/{run_id}/events` | SSE 订阅同一运行：snapshot、delta、state、done |
| `POST /api/v1/sessions/{session_id}/runs/{run_id}/cancel` | 停止任务；终态请求幂等 |

相同 `client_message_id` 与相同内容复用原运行；同 ID 异内容返回 409。失败运行仍以 HTTP 200 返回运行资源，并在 `error` 中保存安全错误；只有请求本身无效时使用 HTTP 错误。无模型配置时可管理会话及材料，消息执行返回 503。知识库配置只影响知识库审核。

SSE 使用已锁定 FastAPI 0.141.1 的官方 `EventSourceResponse` 与 `ServerSentEvent`，不增加依赖。首个 `snapshot` 数据为 `{event, run, text}`，包含当前状态及累计临时回答；`delta` 的 `text` 为新文本，`state` 和 `done` 的 `run` 为 RunView，终态包含正式消息。事件分帧、JSON 编码、空闲约 15 秒的注释心跳及防缓存/防代理缓冲响应头均由框架负责，不保留手写实现；`ServerSentEvent(retry=3000)` 指定浏览器重连间隔。目标通过 FastAPI 依赖在响应开始前校验，不存在时仍返回标准 JSON 404。代理部署需保持长连接并及时转发事件。[官方 SSE 文档](https://fastapi.tiangolo.com/tutorial/server-sent-events/) 与本地 `fastapi/sse.py`、`fastapi/routing.py` 已核对；会话快照、容量管理和取消属于应用策略，仍由既有服务与存储负责。

每次订阅只读取现有运行，不调用模型；断开不取消任务，重连先获取累计快照，不提供持久事件日志或跨进程重放。官方 LangGraph `astream` 只将 `reply_chat` 的模型文本对外发送；结构化意图、思考内容和子审核中间输出不外发。审核只推送顶层真实阶段及最终完整结果。累计临时文本属于活动运行内存状态，计入临时字节额度；慢读者按偏移获取合并增量，不创建无界队列。成功、失败、取消或超时时通知订阅，临时文本占用被回收，正式消息仍执行原容量检查。

会话历史不自动过期。每会话最多 8 文档/100 消息，用户消息 12000 字符，材料累计 100000 字符，消息与子结果累计 1000000 字符，输出单次最多 200000 字符。进程默认 3 个运行、6 个等待，排队 30 秒、运行 600 秒超时；原有并发与超时配置保留。`CONVERSATION_TRANSIENT_MAX_BYTES` 默认 134217728，仅限制临时流式文本及解析中的上传字节，不统计全库历史，也不等于 RSS 上限。旧 TTL、MAX_SESSIONS、MAX_BYTES 配置不再使用。

运行和 DOCX 解析仍受并发控制。原始 DOCX 与解析 Markdown 通过 `infrastructure/documents/local_file_store.py` 保存到 `backend/documents/<agent_id>/<session_id>/<file_id>/`，数据库只保存路径和元数据。`DOCUMENTS_DIR` 可指定其他根目录，相对路径按 backend 解析；数据库和文件目录必须共同备份。应用关闭先取消并收尾任务，再关闭数据库及外部客户端。使用单工作进程；没有用户认证或权限隔离。固定 PostgreSQL advisory lock 防止同库第二实例启动，锁连接丢失或终态提交失败后拒绝新写入并结束订阅，需要重启服务；已提交历史保留，未提交临时结果可能丢失。

### SQL 初始化与配置

会话删除不依赖模型配置。上传、排队、运行或本地执行收尾期间返回 `CONVERSATION_BUSY`（409），不隐式取消任务。数据库已删除但附件或凭据清理失败返回 `CONVERSATION_DELETE_INCOMPLETE`（503），重复同一 DELETE 可继续清理；提交结果无法确认返回 `STORAGE_UNAVAILABLE`（503），保留材料与凭据等待重试。合法且不存在的 ID 返回 204，非法 ID 返回 404。

附件根目录下 `.deletions/<session_id>.json` 仅保存版本、Agent 与会话 ID。在数据库事务删除前落盘，数据库提交确认后精确清理会话目录，完成后移除凭据。启动取得运行权并恢复中断任务后逐项核对：会话不存在才清理文件；会话尚存则保留其文件并移除未提交删除的凭据。单项 IO 失败保留待处理项，不扫描附件库或运行常驻清理任务。DELETE 在服务端接纳后不因客户端断开而撤回，关闭服务会等待删除收尾。

数据库设计与操作说明统一见 [数据库设计与初始化](../docs/database.md)，包括表关系、字段、约束、索引及完整初始化命令。

建库和建表 SQL 位于 `backend/database/`：先在 postgres 管理库执行 `database/create_databases.sql`，再分别连接应用库和专用测试库执行 `database/schema_v2.sql`。在后端 `.env` 配置 `DATABASE_URL` 后启动单工作进程服务；应用启动只验证结构版本，不自动建库或建表。本地旧会话表已按用户授权清理并初始化为 v2，旧建表和一次性清理脚本已移除；不提供迁移或旧接口兼容。已有 v2 库不要重复执行初始化。

### 历史查询

- `GET /api/v1/sessions?agent_id=conversation_assistant&limit=20&cursor=...`：按更新时间与 ID 倒序的键集分页，返回 items/next_cursor。
- `GET /api/v1/sessions/{session_id}`：默认最新 50 条消息，响应按 sequence 升序；before_sequence 读取更早一页，after_sequence 追赶新消息，两者互斥。limit 为 1–100。
- has_more 说明本次方向还有下一页，next_before_sequence/next_after_sequence 为下一页位置；last_sequence 是全会话最高序号，不能当作已收到的位置。响应不再含 expires_in_seconds。
- 完整消息、已提交报告和材料关联可以在刷新/重启后恢复；SSE 增量仅在当前运行进程内重连恢复，订阅历史终态返回终态后关闭，不重新调用模型。

### PostgreSQL 测试

执行测试前在当前终端显式提供指向专用 `agent_platform_test` 的 `TEST_DATABASE_URL`。真实数据库测试与 CI 统一使用 `database/schema_v2.sql`；测试 schema 隔离及清理范围见 [数据库测试与维护](../docs/database.md#测试与维护)。模型和检索仍使用替身。


## Langfuse 追踪、Prompt 与实验

后端支持自托管 Langfuse 4.59.0+，当前锁定 Python SDK 5.0.2。凭据仅填写后端 `.env`；示例字段见 `.env.example`。开启 `LANGFUSE_ENABLED=true` 后，业务 POST 请求、后台会话运行、父子 Agent、图节点、模型调用及 RAGFlow 检索关联到同一执行上下文；会话每轮使用独立追踪，同会话以 session_id 分组。健康检查、GET 状态读取和 SSE 订阅仅保留本地请求日志，不重复生成模型调用追踪。

`LANGFUSE_CAPTURE_CONTENT` 默认 false：远端只保存层级、标识、状态、用量及白名单元数据。显式设为 true 会将模型输入输出和图状态持久写入 Langfuse，区别于原有临时内存会话；凭据仍过滤。最终 OTel 导出过滤也清除自动异常事件和资源属性，避免绕过开关。SDK 异步批量上报，关闭应用先回收任务再发送剩余数据；上报故障不改变业务就绪或结果。

Token 来自供应商真实 usage，输入、输出和缓存桶分别统计，不使用字符预算代替。费用由 Langfuse 根据匹配的模型价格推算；缺少价格或用量时是未知值。自定义模型名称、私有价格和币种须在 Langfuse 模型设置中核对，系统不会自动改价，也不统计 RAGFlow 内部不可见模型的费用。

Langfuse 原生 `cost_details` 的单位是美元。人民币模型可通过 `LANGFUSE_COST_MODEL`（精确名称）及 `LANGFUSE_INPUT_CNY_PER_MILLION`、`LANGFUSE_OUTPUT_CNY_PER_MILLION`、`LANGFUSE_CACHED_INPUT_CNY_PER_MILLION` 配置在线文本单价。每个 generation 的 metadata 包含 `estimated_cost_cny`、`cost_currency=CNY`、`cost_basis=online-token-estimate`，供核对人民币估算；缺少用量、价格或出现未配置的计量桶时不生成估算。当前本机按用户提供的 0.8/2.7/0.1 元每百万 Token 配置，未使用 Batch 或显式缓存创建价。

2026-10-21 按用户指定的固定记账汇率 **1 USD = 6.8 CNY**，已在当前 Langfuse 项目创建 `qwen3.8-flash` 自定义模型价表（精确匹配名称）。输入、输出、缓存命中分别为 **0.117647058824 / 0.397058823529 / 0.014705882353 USD 每百万 Token**；API 实际按每 Token 价格保存，即人民币每百万价格 ÷ 6.8 ÷ 1000000，未使用上述显示值截断计价。缓存桶覆盖 `input_cache_read` 及对应别名，独立 reasoning 输出桶按相同输出价计费；不对 `total` 重复计费。该汇率不自动跟随市场变化，后续原本以美元计价的模型直接配置其美元价格。业务代码不会自动同步或覆盖远端价表，更换项目或重建 Langfuse 后须重新配置。模型价表仅作用于生效后的新记录，历史费用不会自动补算；实际费用仍以完整的供应商输入、输出及缓存用量为前提。[官方计费说明](https://langfuse.com/docs/observability/features/token-and-cost-tracking)。

Prompt 共 8 个，覆盖会话意图/回答与审核的知识库条款、标准条款、术语、简述、冲突报告及建议。开启 `LANGFUSE_PROMPTS_ENABLED=true` 后按 `LANGFUSE_PROMPT_LABEL`（默认 production）读取；当前轮同名模板版本固定，跨轮可刷新。两开关任一关闭时使用本地模板。远端读取失败或变量不匹配时日常请求兜底，固定版本实验明确失败。

在 `backend/` 运行：

```powershell
# 检查远端模板差异；仅创建缺失模板，不覆盖冲突或移动已有标签
uv run python -m scripts.sync_langfuse_prompts --dry-run
uv run python -m scripts.sync_langfuse_prompts --apply --initial-label development

# 离线校验样例及版本文件，不调用模型或远端
uv run python -m scripts.run_langfuse_experiments --dataset tests/fixtures/langfuse/conversation_cases.json --prompt-versions tests/fixtures/langfuse/prompt_versions.example.json --run-name conversation-v1 --dry-run

# 显式运行会消耗已配置模型额度并写入 Langfuse；--sync-dataset 仅补建缺失合成项
uv run python -m scripts.run_langfuse_experiments --dataset tests/fixtures/langfuse/standard_review_cases.json --prompt-versions tests/fixtures/langfuse/prompt_versions.example.json --run-name standard-v1 --dataset-name agent-platform/acceptance-standard --execute --sync-dataset
```

版本文件示例中的 1 仅是样例，执行前应替换为项目中真实存在的版本。已有数据集异内容项会报错，不覆盖或删除。实验执行真实注册表/图，在同一个事件循环复用运行时和并发额度；SDK runner 在工作线程桥接，不逐项创建事件循环。默认并发 1，输出包含成功/失败总数、确定性规则分数及全部样例结果；失败不能从评分分母中消失。合成数据与真实会话隔离，不自动把用户文档加入数据集。

发布/回滚通过 Langfuse 标签指向进行；初始同步不会移动既有 production 标签。当前本机开发配置使用 development。关闭两个开关可恢复本地模板及原业务执行，已写入 Langfuse 的数据仍保留。没有接入图检查点、断点或恢复执行，也未增加前端监控页面。

相关检查：`uv run ruff check app tests scripts`、`uv run pytest`。测试使用受控模型及 SDK 内存导出，核对父子图并发隔离、generation 不重复、用量不被过滤、正文开关、取消、Prompt 固定与兜底及实验失败计数；真实模型准确率、网关计量和模型价格仍需独立验收。

## 模型与 RAGFlow 配置

需要 Python 3.12 或 3.13。

复制 `.env.example` 为 `.env`，填入模型服务配置。标准文档模式不要求 RAGFlow；使用知识库审核时再配置 RAGFlow：

- `LLM_MODEL`、`LLM_API_KEY`：OpenAI 兼容模型名称与密钥。
- `LLM_BASE_URL`：可选的 OpenAI 兼容服务地址；连接 OpenAI 官方服务时留空。
- `LLM_TIMEOUT_SECONDS`：模型请求超时时间，默认 180 秒，可配置范围为 30–600 秒；百炼兼容接口通过 `enable_thinking=false` 关闭思考模式。
- `RAGFLOW_BASE_URL`、`RAGFLOW_API_KEY`、`RAGFLOW_DATASET_ID`：RAGFlow 地址、API Key 和制度知识库 ID。
- `MAX_UPLOAD_BYTES`：单个上传文件大小上限，默认 20 MiB。
- `MAX_REVIEW_CHARS`：DOCX 转换为 Markdown 后的正文字符数上限。
- `INSTITUTION_REVIEW_CONCURRENCY`：正整数，默认 3。同一应用进程内的制度审核请求共享条款任务额度；多进程各自计算，不包含全文术语、报告和建议节点。

草稿和标准分别应用文件及字符上限。标准模式每组草稿输入完整标准，不截断正文；字符上限不等于模型 token 上限，需按实际模型选择合适的标准长度和并发数。模型上下文或额度错误会返回调用失败，不按审核通过处理。

## 安装与启动

在 `backend/` 目录下执行：

```powershell
uv sync
uv run uvicorn app.main:create_app --factory --reload
```

使用 Python 虚拟环境时，也可以在 `backend/` 目录下运行 `python -m pip install -e .`，然后执行 `uvicorn app.main:create_app --factory --reload`。

后端依赖包含 `pypandoc-binary==1.17`，为 Markdown 转 Word 提供包内 Pandoc；使用 `uv sync --locked` 安装锁定依赖即可，无需系统级安装 Pandoc。实际转换显式使用包内程序，不依赖系统 PATH，也不在应用启动或请求期间下载程序。目标平台必须有可用的包内二进制；不可用时导出返回 503，不影响已有审核服务启动。

## 质量检查

使用 `uv` 安装开发依赖后，在 `backend/` 目录执行：

```powershell
uv sync --locked --group dev
uv run ruff check app tests
uv run pytest
```

GitHub Actions 会在 Pull Request 和推送到 `main` 时执行后端静态检查、测试，以及前端锁文件安装和生产构建。

测试目录按职责划分：

- `tests/infrastructure/`：RAGFlow 等外部服务适配测试。
- `tests/agents/institution_review/`：制度审核 Agent 的配置、分块、并发、标准对比、报告、服务及审核 API 测试；后续 Agent 在 `tests/agents/` 下使用各自目录。
- `tests/conftest.py`：共享测试夹具。
- `tests/test_agent_graph_api.py`：平台流程图 API 测试。
- `tests/test_document_export_config.py`、`test_document_export_service.py`、`test_document_exports_api.py`：导出契约、样式、共享并发、取消和独立下载接口。
- `tests/infrastructure/test_pandoc.py`：包内二进制定位、超时、有界管道和进程回收。
- `tests/test_document_export_integration.py`：真实包内 Pandoc 和完整 HTTP 导出，不调用模型、检索或远程图片。缺少依赖会标记跳过，发布验收要求真实转换测试实际运行。

全量检查命令保持不变；可用 `uv run pytest tests/agents/institution_review` 单独运行制度审核测试。

## 接口

- `GET /health/live`：进程存活状态。
- `GET /health/ready`：主状态检查聊天模型配置和运行时；`modes.standard_document`、`modes.knowledge_base` 分别提供 `configured` 与 `issues`。这是配置检查，不保证网络连通或账户额度充足。
- `POST /api/v1/reviews`：使用 `multipart/form-data` 上传草稿 `file`，同步返回 `text/markdown` 报告。`review_mode` 缺省为 `knowledge_base`；选择 `standard_document` 时必须同时上传 `standard_file`。知识库模式附带标准文件返回 422；知识库配置不完整返回 503。
- `GET /api/v1/agents/institution_review/graph`：返回制度审核智能体的静态流程节点及有向连线；流程图结构查询不要求 AgentRuntime 就绪，不表示实际运行进度。
- `POST /api/v1/documents/export/docx`：接收 JSON 的 `markdown` 和可选 `title`，直接返回 DOCX 文件。纯转换不依赖模型、RAGFlow 或 AgentRuntime，也不重新执行审核；`api_prefix` 配置同时适用于该路由。

PowerShell 示例：

```powershell
curl.exe -X POST "http://127.0.0.1:8000/api/v1/reviews" -F "file=@制度草稿.docx"

# 标准文档对比：不调用知识库或 embedding
curl.exe -X POST "http://127.0.0.1:8000/api/v1/reviews" -F "review_mode=standard_document" -F "file=@制度草稿.docx" -F "standard_file=@标准文档.docx"
```

审核流程由全文术语检查分支和并发条款审查分支组成。条款拆分由代码完成。知识库模式每条分别检索 RAGFlow；标准模式直接对比上传标准全文，超过 30 个草稿条款块时合并相邻条款为 30 组，不丢弃原文或定位信息。30 是条款审查批次上限，不包含其他模型节点，也不限制发现数量。

`review_clauses` 是直接注册到父图的 LangGraph 编译子图，内部按模式通过官方 `Send` 分发单组审核，使用私有 reducer 累积并验证完整性，再按原条款顺序汇总。父图节点 ID、结构接口及四部分报告保持，流程页面仍只展示静态父图概览。共享 semaphore 只覆盖条款检索和模型调用，约束同一图实例的多个请求；没有旧批量调度入口、兼容包装或回退开关。

当前父图先并行执行拆分和术语检查；受 LangGraph superstep 屏障约束，这一步结束后才启动条款子图，报告在所需结果全部就绪后生成。任务失败或取消由原生执行器清理，本轮退出时释放额度，其他请求继续。没有新增图层重试、checkpointer 或跨进程限流；失败后重新提交会重做。取消仅保证本进程调用退出，不保证供应商停止远端计算或计费。

未发现问题默认通过，通过条款不进入报告问题汇总上下文；模型和检索调用失败仍返回错误。标准发现需有组内真实条款序号及可在标准中定位的原文摘录。最终 Markdown 保持简述、冲突检测、术语检测和修改建议四部分。文档读取复用公共 `app/nodes/`。

后端测试使用假模型与检索器，覆盖分组、跨请求并发额度、取消清理、完整审核图与 ASGI 双文件入口，不消耗真实账户额度。真实模型准确率、上下文适配及吞吐需另行验收，知识库联调需可用的检索服务与额度。

## Markdown 导出 Word

请求为 `application/json`，例如 `{"markdown":"## 一. 简述\n\n审核内容……","title":"制度审核报告"}`。`markdown` 必填且非空白，最多 200000 字符；`title` 默认“制度审核报告”，最多 200 字符且不能含控制字符。额外字段、空值和错误类型返回 422。服务转换请求中的内容，不证明其来自某次原始审核。

可先将 JSON 请求保存为 UTF-8 的 `request.json`，再执行：

```powershell
curl.exe -X POST "http://127.0.0.1:8000/api/v1/documents/export/docx" -H "Content-Type: application/json" --data-binary "@request.json" --output "制度审核报告.docx"
```

成功响应为 `application/vnd.openxmlformats-officedocument.wordprocessingml.document`，包含附件文件名和 `Cache-Control: no-store`。服务通过内存返回文件，不保存审核结果或附件。前端报告页通过“下载 Word”按钮调用此接口。`DocumentExportService.export_docx()` 同时可由后续 Python 业务工具复用，返回文件字节、文件名和 MIME 类型；Chat 和 MCP 尚未接入。

支持 GFM 标题、段落、粗斜体、列表、引用、分隔线、代码、常规链接及管道表格。表格等行内内容中的无属性 `<br>`、`<br/>`、`<br />`（大小写均可）映射为 Pandoc 原生 `LineBreak`，在 Word 中保留单元格内换行；代码或转义文字中的标签原样保留。真实图片、带属性的换行标签及其他原始 HTML 仍返回 422。Word 使用 A4、2.5 cm 页边距、宋体/Times New Roman 正文、重复表头和自动换行；字体不嵌入，复杂排版需在目标 Word/WPS 环境验收。

| 环境配置 | 默认值 | 范围与含义 |
| --- | --- | --- |
| `DOCUMENT_EXPORT_TIMEOUT_SECONDS` | 30 | 正数；两次 Pandoc 调用共享预算，不含排队 |
| `DOCUMENT_EXPORT_CONCURRENCY` | 2 | 正整数；同进程所有导出共享，包含转换及样式处理 |
| `DOCUMENT_EXPORT_MAX_CHARS` | 200000 | 1–200000；独立于上传文档字符上限 |
| `DOCUMENT_EXPORT_MAX_BODY_BYTES` | 1048576 | 正整数；JSON 请求体字节上限，实际读取时执行 |
| `DOCUMENT_EXPORT_MAX_OUTPUT_BYTES` | 10485760 | 正整数；每次 Pandoc 输出及最终文件大小上限 |

排队最多 5 秒；多工作进程分别计算并发额度。超时返回 504，繁忙或引擎不可用返回 503，请求体超限返回 413，内容不支持或文件超限返回 422，其他转换失败返回 500。失败响应使用现有统一错误结构，不包含文档、机器路径或原始进程诊断。原 Markdown 可独立重试导出。
