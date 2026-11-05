# 智能体平台后端

基于 Python 3.12 / 3.13、FastAPI、LangChain / LangGraph 和 PostgreSQL 18，提供制度审核、会话助手与 Word 导出。制度审核同步返回报告，会话助手异步执行并通过 SSE 推送结果。

## 会话助手与持久历史

支持直接聊天、上传 DOCX 或粘贴正文。普通聊天和问答仅调用聊天模型；明确审核意图且参数齐全后，才调用 `institution_review`。缺少材料或审核方式时先追问，转移话题时清除待补齐任务。

会话图使用官方 `AsyncPostgresSaver` 保存短期记忆，每轮只输入当前消息和材料目录。多个助手可共享 saver 与公共摘要能力，各自定义图状态、提示和策略，以 `agent_id:session_id` 隔离记忆。完整消息、报告和附件另行归档；长期记忆 Store 尚未接入。

上下文最多 24000 个序列化字符；已完成消息超过 8 条或其序列化大小超过 12000 字符时摘要，优先保留最近两轮。摘要最多 3000 字符、历史分片最多 12000 字符、历史报告片段最多 4000 字符；仍放不下最新输入时明确失败。审核始终按材料 ID 读取授权会话内的完整原文，待补参独立保存。

`memory_checkpoint_id` 与助手消息、完整报告和成功终态同事务提交，之后才推送完成。失败、取消或容量超限不推进记忆位置，下轮从上次成功位置执行；重启将未完成任务标记中断，不自动续跑。

父子调用共用 `AgentRuntime`，审核图在启动时构建并复用。职责边界见[架构规则](../docs/ai-coding/architecture-rules.md)。

以下路径沿用 `api_prefix`（默认 `/api/v1`）：

| 方法与路径 | 行为 |
| --- | --- |
| `GET /api/v1/agents` | 智能体展示目录 |
| `POST /api/v1/sessions` | 创建持久会话，返回 201 |
| `DELETE /api/v1/sessions/{session_id}` | 永久删除空闲会话及关联消息、结果、检查点和附件；空 204 表示全部完成，重复请求幂等 |
| `GET /api/v1/sessions/{session_id}` | 读取历史消息和文件元数据，支持分页及按序号增量获取 |
| `POST /api/v1/sessions/{session_id}/files` | multipart 字段 `file` 上传 DOCX，返回 file_id 等元数据；不自动审核 |
| `POST /api/v1/sessions/{session_id}/messages` | JSON `{client_message_id, content, file_ids: []}`，返回 202 及 run_id |
| `GET /api/v1/sessions/{session_id}/runs/{run_id}` | 查询 queued/running/succeeded/failed/cancelled 及结果 |
| `GET /api/v1/sessions/{session_id}/runs/{run_id}/events` | SSE 订阅同一运行：snapshot、delta、state、done |
| `POST /api/v1/sessions/{session_id}/runs/{run_id}/cancel` | 停止任务；终态请求幂等 |

相同 `client_message_id` 和内容复用原运行，同 ID 异内容返回 409。查询失败运行仍返回 HTTP 200，失败原因在 `error` 中。无模型配置时可管理会话与材料，消息执行返回 503；RAGFlow 配置只影响知识库审核。

SSE 使用 FastAPI 0.141.1 的官方 [EventSourceResponse / ServerSentEvent](https://fastapi.tiangolo.com/tutorial/server-sent-events/)，由框架处理分帧、心跳及响应头。首个 `snapshot` 为 `{event, run, text}`；`delta.text` 为新文本，`state.run` 和 `done.run` 为 RunView，终态包含正式消息。重连间隔为 3000 ms，代理需保持长连接并及时转发。

订阅和重连只读取已有运行，不重复调用模型；断开订阅不取消任务。只推送普通回答、审核阶段和完整结果，不外发意图、思考或审核中间输出。累计文本保存在进程内存，重连先取快照，不支持持久事件重放。

会话历史不自动过期，默认限制如下；相关环境变量见 [.env.example](.env.example)。

| 项目 | 限制 |
| --- | --- |
| 每会话 | 8 文档、100 消息；材料累计 100000 字符，消息与子结果累计 1000000 字符 |
| 单次输入 / 输出 | 用户消息 12000 字符；输出 200000 字符 |
| 执行 / 等待 | 3 个运行、6 个等待；排队超时 30 秒，执行超时 600 秒 |
| 临时资源 | `CONVERSATION_TRANSIENT_MAX_BYTES=134217728`，仅约束流式文本与解析中上传字节，不代表总内存上限 |

附件保存在 `documents/<agent_id>/<session_id>/<file_id>/`，可通过 `DOCUMENTS_DIR` 修改根目录；数据库与附件须共同备份。使用单工作进程，同库第二实例拒绝启动。丢失数据库运行权或终态提交失败后停止接纳写入，需要重启服务；关闭时先收尾任务，再关闭存储与外部客户端。

### 永久删除

空闲会话可永久删除，无需模型配置；忙碌时返回 `CONVERSATION_BUSY`（409）。先写删除凭据并确认业务记录已删除，再清理官方检查点、附件和凭据。清理未完返回 `CONVERSATION_DELETE_INCOMPLETE`（503），可重试同一 DELETE；提交无法确认时返回 `STORAGE_UNAVAILABLE`，保留材料等待核实。启动会恢复待清理项，关闭会等待已接纳删除结束。

### SQL 初始化与配置

已经执行 `schema_v4.sql` 时，先停止后端，再在 `backend/` 目录补建官方检查点表：

```powershell
uv run python -m scripts.manage_users setup-checkpoints
```

该命令可重复执行，保留业务数据和管理员密码；完成后重新启动后端。

全新空库使用 `uv run python -m scripts.manage_users initialize`，一次创建全部表并设置管理员密码。当前结构为 v4，应用启动不自动建表或迁移；管理员密码恢复使用 `reset-admin`。详细说明见[数据库说明](../docs/database.md)。

### 历史查询

- `GET /api/v1/sessions?agent_id=conversation_assistant&limit=20&cursor=...`：按更新时间与 ID 倒序的键集分页，返回 items/next_cursor。
- `GET /api/v1/sessions/{session_id}`：默认最新 50 条消息，响应按 sequence 升序；before_sequence 读取更早一页，after_sequence 追赶新消息，两者互斥。limit 为 1–100。
- `has_more` 表示该方向还有下一页，`next_before_sequence` / `next_after_sequence` 为翻页位置；`last_sequence` 是全会话最高序号，不能当作已收到的位置。
- 完整消息、已提交报告和材料关联可以在刷新/重启后恢复；SSE 增量仅在当前运行进程内重连恢复，订阅历史终态返回终态后关闭，不重新调用模型。

### PostgreSQL 测试

在终端显式提供指向 `agent_platform_test` 的 `TEST_DATABASE_URL`。测试以 v4 初始化随机 schema，仅清理本次 schema；不会回退到应用库。准备步骤见[数据库测试与维护](../docs/database.md#测试与维护)，模型和检索使用受控替身。


## 账号接口与浏览器约束

公开接口为 `POST /auth/register`、`POST /auth/login`、`GET /agents` 及健康检查；业务路径均带 `api_prefix`。注册返回 201 和用户资料，不自动登录；其余业务接口要求有效登录，管理员也不能读取他人会话。

`GET /auth/me` 返回 user、auth_session_id、csrf_token、expires_at。其他私有请求携带 Cookie 和 `X-Auth-Session-ID`，写请求再加 `X-CSRF-Token`；SSE 通过查询参数携带 auth_session_id。写请求的 Origin 或 Referer 须与 `AUTH_TRUSTED_ORIGINS` 精确匹配，前端请求使用 credentials。

`POST /auth/logout`、`POST /auth/password` 撤销登录并返回 204；`GET/PATCH /users/me` 读取或局部更新本人资料。显示名称必填，邮箱、性别、生日、手机号、地址、签名选填，省略字段保持原值，空值/空白清空可选项。生日仅接收 YYYY-MM-DD，不晚于 UTC+08:00 当天；邮箱和手机号仅为资料，不参与登录或验证。登录、注册和 `/auth/me` 继续返回账号摘要，额外提供 `has_avatar`，不附带联系方式等完整资料。

`POST /users/me/avatar` 接收唯一 multipart 文件字段 `file`，支持 JPG/PNG/WebP，文件最多 2 MiB、请求含开销最多 2 MiB+64 KiB。Pillow 13.0.0 验证静态图片、像素边界并归一化为最长边 512px 的 PNG，去除元数据；email-validator 2.3.0 通过 Pydantic EmailStr 做邮箱语法校验，不探测 DNS。头像处理同进程最多两个请求，无无限队列。`GET/DELETE /users/me/avatar` 读取或移除头像，读取也须带身份上下文头，前端经受保护 blob 请求展示；移除重复请求均返回 204。头像保存是独立操作，不与文字资料保存捆绑。

管理员通过 GET/POST `/admin/users`、PATCH `/admin/users/{id}` 和 POST `/admin/users/{id}/password-reset` 管理普通用户；另可通过 `GET /admin/users/{id}` 和 `GET /admin/users/{id}/avatar` 只读查看目标资料和头像，包括停用用户和内置 admin 本人，不增加代编辑能力。内置 admin 恢复仍使用离线命令。

登录有效期固定 12 小时；Cookie 使用 HttpOnly、SameSite=Lax、Path=/，非 development 环境还使用 Secure 和 `__Host-` 前缀。生产部署须配置 `APP_ENV`、可信来源和同源或同站 HTTPS 入口。用户名为 3–32 位小写字母、数字或下划线且字母开头；密码为 6–20 个 Unicode 字符，不去空格，采用 Argon2 哈希。限额配置见 [.env.example](.env.example)，错误响应见[错误码](../docs/errors.md)。

## Langfuse 追踪、Prompt 与实验

支持自托管 Langfuse 4.59.0+，锁定 Python SDK 5.0.2。凭据填写在后端 `.env`，开启 `LANGFUSE_ENABLED=true` 后记录请求、Agent、图、模型和检索调用链；会话每轮独立追踪，以 session_id 分组。健康检查、状态读取和 SSE 订阅不生成重复追踪。

`LANGFUSE_CAPTURE_CONTENT=false` 时仅上传标识、状态、用量和白名单元数据；设为 true 才持久上传正文与图状态，凭据始终过滤。上报故障不改变业务结果。

Token 使用供应商 usage；费用按 Langfuse 匹配的模型价格估算，缺少价格或用量时为未知值，不统计 RAGFlow 内部不可见的费用。

人民币估算通过 `LANGFUSE_COST_MODEL` 精确匹配模型名，并配置 `LANGFUSE_INPUT_CNY_PER_MILLION`、`LANGFUSE_OUTPUT_CNY_PER_MILLION`、`LANGFUSE_CACHED_INPUT_CNY_PER_MILLION`。结果写入 generation metadata 的 `estimated_cost_cny`，不替代原生美元 `cost_details`；缺少必要用量或价格时不估算。

当前开发价表于 2026-10-21 配置：`qwen3.8-flash` 输入 / 输出 / 缓存命中为 0.8 / 2.7 / 0.1 元每百万 Token，按固定记账汇率 **1 USD = 6.8 CNY** 换算，美元每 Token 价格为人民币每百万价格 ÷ 6.8 ÷ 1000000。该汇率不随市场变化，价表不自动同步，重建项目后须重新配置，历史费用不补算。详见 [Langfuse 计费说明](https://langfuse.com/docs/observability/features/token-and-cost-tracking)。

共 9 个 Prompt，覆盖会话摘要、意图、回答及审核节点。追踪和 `LANGFUSE_PROMPTS_ENABLED` 同时开启时，按 `LANGFUSE_PROMPT_LABEL`（默认 production）读取远端模板，同一轮固定版本。日常请求读取失败时使用本地模板，固定版本实验则明确失败。

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

示例版本号须替换为远端真实版本；已有数据集内容冲突时失败，不覆盖。实验默认并发 1，失败计入总数；执行真实注册表与图，但使用独立 InMemorySaver 和合成材料，不读取应用会话或自动采集用户文档。

通过 Langfuse 标签发布或回滚模板；初始同步不移动既有 production 标签。当前开发配置使用 development，关闭追踪与 Prompt 开关可恢复本地模板，已上传数据仍保留。真实模型效果、网关计量及价格需独立验收。

## 模型与 RAGFlow 配置

复制 [.env.example](.env.example) 为 `.env` 后填写配置。标准文档模式无需 RAGFlow，知识库审核才需要：

- `LLM_MODEL`、`LLM_API_KEY`：OpenAI 兼容模型名称与密钥。
- `LLM_BASE_URL`：可选的 OpenAI 兼容服务地址；连接 OpenAI 官方服务时留空。
- `LLM_TIMEOUT_SECONDS`：模型请求超时时间，默认 180 秒，可配置范围为 30–600 秒；百炼兼容接口通过 `enable_thinking=false` 关闭思考模式。
- `RAGFLOW_BASE_URL`、`RAGFLOW_API_KEY`、`RAGFLOW_DATASET_ID`：RAGFlow 地址、API Key 和制度知识库 ID。
- `MAX_UPLOAD_BYTES`：单个上传文件大小上限，默认 20 MiB。
- `MAX_REVIEW_CHARS`：DOCX 转换为 Markdown 后的正文字符数上限。
- `INSTITUTION_REVIEW_CONCURRENCY`：正整数，默认 3。同一应用进程内的制度审核请求共享条款任务额度；多进程各自计算，不包含全文术语、报告和建议节点。

草稿和标准分别应用文件及字符上限。标准模式每组草稿输入完整标准，不截断正文；字符上限不等于模型 token 上限，需按实际模型选择合适的标准长度和并发数。模型上下文或额度错误会返回调用失败，不按审核通过处理。

## 安装与启动

使用 Python 3.12 / 3.13，在 `backend/` 目录执行：

```powershell
uv sync --locked
# 配置 .env，并按数据库说明完成初始化后启动
uv run uvicorn app.main:create_app --factory --reload --loop app.infrastructure.conversation.checkpoints:event_loop_factory
```

**Windows 特殊情况**：`--loop ...:event_loop_factory` 在 Windows 下选择 Selector，因为 Psycopg 异步驱动不支持默认的 Proactor。其他系统也可使用此命令；`--reload` 用于开发时自动重启。

Word 导出使用 `pypandoc-binary==1.17` 自带的 Pandoc，无需系统安装或运行时下载；包内程序不可用时导出返回 503，不影响审核服务启动。

## 质量检查

使用 `uv` 安装开发依赖后，在 `backend/` 目录执行：

```powershell
uv sync --locked --group dev
uv run ruff check app scripts tests
uv run pytest
```

GitHub Actions 在 Pull Request 及推送到 `main`、`dev` 时运行后端检查与前端构建。测试覆盖受控模型、真实隔离数据库和包内 Pandoc；发布验收须实际运行 `tests/test_document_export_integration.py`，不能以跳过代替通过。范围与限制见[质量门禁](../docs/ai-coding/quality-gates.md)。

## 接口

- `GET /health/live`：进程存活状态。
- `GET /health/ready`：检查模型配置和运行时，按审核模式返回 `configured` 与 `issues`；不探测网络或账户额度。
- `POST /api/v1/reviews`：使用 `multipart/form-data` 上传草稿 `file`，同步返回 `text/markdown` 报告。`review_mode` 缺省为 `knowledge_base`；选择 `standard_document` 时必须同时上传 `standard_file`。知识库模式附带标准文件返回 422；知识库配置不完整返回 503。
- `GET /api/v1/agents/institution_review/graph`：制度审核静态节点与连线，不表示运行进度。
- `POST /api/v1/documents/export/docx`：JSON 提交 `markdown` 和可选 `title`，返回 DOCX；不依赖模型或 RAGFlow。

以下 PowerShell 示例展示业务字段；私有接口还需携带前述登录 Cookie、身份与 CSRF 请求头及可信 Origin。

```powershell
curl.exe -X POST "http://127.0.0.1:8000/api/v1/reviews" -F "file=@制度草稿.docx"

# 标准文档对比：不调用知识库或 embedding
curl.exe -X POST "http://127.0.0.1:8000/api/v1/reviews" -F "review_mode=standard_document" -F "file=@制度草稿.docx" -F "standard_file=@标准文档.docx"
```

制度审核并行准备条款拆分和全文术语检查，再通过官方 LangGraph `Send` 分发条款审核。超过 30 个草稿块时按原顺序合并至 30 组，保留原文和定位；知识库模式检索 RAGFlow，标准模式使用完整标准文档。条款任务共享同进程并发额度，汇总按业务序号排序。

报告包含简述、冲突检测、术语检测和修改建议。通过条款不进入问题汇总，模型或检索失败仍报错。独立审核图不配置重试、checkpointer 或跨进程恢复，重新提交会重做；取消会清理本进程任务并释放额度，但不保证供应商停止远端计算或计费。

## Markdown 导出 Word

请求为 `application/json`，例如 `{"markdown":"## 一. 简述\n\n审核内容……","title":"制度审核报告"}`。`markdown` 必填且非空白，最多 200000 字符；`title` 默认“制度审核报告”，最多 200 字符且不能含控制字符。额外字段、空值或错误类型返回 422。

将 JSON 保存为 UTF-8 的 `request.json` 后执行；认证要求同上：

```powershell
curl.exe -X POST "http://127.0.0.1:8000/api/v1/documents/export/docx" -H "Content-Type: application/json" --data-binary "@request.json" --output "制度审核报告.docx"
```

成功返回 DOCX MIME、附件文件名及 `Cache-Control: no-store`；转换在内存中完成，不保存文件或重做审核。前端报告页通过“下载 Word”调用该接口。

支持 GFM 标题、段落、粗斜体、列表、引用、代码、链接及表格；无属性 `<br>`（含自闭合和大小写形式）保留为换行，代码或转义文本中的标签原样保留。图片、带属性标签和其他原始 HTML 返回 422。Word 使用 A4、2.5 cm 页边距、宋体 / Times New Roman、重复表头及自动换行；复杂排版须在目标 Word/WPS 环境验收。

| 环境配置 | 默认值 | 范围与含义 |
| --- | --- | --- |
| `DOCUMENT_EXPORT_TIMEOUT_SECONDS` | 30 | 正数；两次 Pandoc 调用共享预算，不含排队 |
| `DOCUMENT_EXPORT_CONCURRENCY` | 2 | 正整数；同进程所有导出共享，包含转换及样式处理 |
| `DOCUMENT_EXPORT_MAX_CHARS` | 200000 | 1–200000；独立于上传文档字符上限 |
| `DOCUMENT_EXPORT_MAX_BODY_BYTES` | 1048576 | 正整数；JSON 请求体字节上限，实际读取时执行 |
| `DOCUMENT_EXPORT_MAX_OUTPUT_BYTES` | 10485760 | 正整数；每次 Pandoc 输出及最终文件大小上限 |

排队最多 5 秒。超时返回 504，繁忙或引擎不可用返回 503，请求体超限返回 413，内容不支持或文件超限返回 422，其他转换失败返回 500。失败时可用原 Markdown 重试，响应格式见[错误码](../docs/errors.md)。
