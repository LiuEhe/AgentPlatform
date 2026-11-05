# AgentPlatform 后端

后端使用 Python 3.12 / 3.13、FastAPI、LangChain / LangGraph 和 PostgreSQL 18，提供会话助手、制度审核、账号管理和 Word 导出。

## 安装与启动

以下命令在 `backend/` 执行：

```powershell
Copy-Item .env.example .env  # 仅首次执行，已有配置时跳过
uv sync --locked
```

填写下表中的配置，再按[数据库说明](../docs/database.md#初始化)初始化新环境。已有库不要重复初始化。启动：

```powershell
uv run uvicorn app.main:create_app --factory --reload --loop app.infrastructure.conversation.checkpoints:event_loop_factory
```

`--reload` 用于开发时自动重启。`--loop` 在 Windows 下选择 Selector，满足 Psycopg 异步驱动要求；其他系统也可使用。

启动后在 `http://127.0.0.1:8000/docs` 查接口参数。`/health/live` 检查进程存活，`/health/ready` 检查模型配置和运行时，并分别列出两种审核模式的配置问题；不探测网络或账户额度。

## 必要配置

配置文件为 [.env.example](.env.example) 的本地副本 `.env`；全部配置及默认值见 [Settings](app/core/config.py)。

| 配置 | 用途 |
| --- | --- |
| `DATABASE_URL` | PostgreSQL 应用库连接串；账号和历史功能也需要数据库 |
| `LLM_MODEL`、`LLM_API_KEY` | OpenAI 兼容聊天模型名称与密钥 |
| `LLM_BASE_URL` | 兼容服务地址；连接 OpenAI 官方服务时可留空 |
| `LLM_TIMEOUT_SECONDS` | 单次模型请求超时，默认 180 秒，范围 30–600 秒 |
| `RAGFLOW_BASE_URL`、`RAGFLOW_API_KEY`、`RAGFLOW_DATASET_ID` | 仅知识库审核需要 |
| `MAX_UPLOAD_BYTES` | 每个 DOCX 的字节上限，默认 20 MiB |
| `MAX_REVIEW_CHARS` | 每个文档解析后的正文上限，默认 50000 字符 |
| `INSTITUTION_REVIEW_CONCURRENCY` | 同进程共享的条款审核额度，默认 3；不包含全文术语、报告和建议节点 |
| `DOCUMENTS_DIR`、`AVATARS_DIR` | 附件和头像目录，默认分别为 `backend/documents`、`backend/avatars` |

百炼兼容接口通过 `enable_thinking=false` 关闭思考模式。无模型配置时仍可管理账号、会话和材料，消息执行返回 503；标准文档审核不需要 RAGFlow。

## 制度审核

两种方式都上传 DOCX 草稿，返回带条款定位的完整 Markdown 报告：

| 方式 | 输入与依赖 |
| --- | --- |
| `knowledge_base`（接口默认） | 草稿 `file`，从 RAGFlow 查依据；不能附带标准文件 |
| `standard_document` | 草稿 `file` 与标准 `standard_file`，不调用知识库或 embedding |

`POST /api/v1/reviews` 使用 `multipart/form-data`，通过 `review_mode` 指定方式，同步返回 `text/markdown`。前端默认选标准文档，并显式传入方式。

流程是“拆分条款 + 全文术语检查 → 审核条款 → 汇总报告与建议”。条款任务由 LangGraph `Send` 分发，共享同进程额度，结果按原序号汇总，并等待全文检查完成。**标准文档模式**超过 30 个草稿块时按原顺序合并到最多 30 组，每组输入完整标准，不截断原文。

草稿与标准分别受文件和字符上限约束。字符数不等于模型 Token 数，模型上下文或额度不足时明确报错；通过条款不列入问题汇总，模型或检索失败不会当作通过。

独立审核图未配置节点重试或持久恢复，重新提交会从头执行。取消会清理本进程任务并释放额度，但不保证供应商停止远端计算或计费。

其他入口：`GET /api/v1/agents` 返回目录；`GET /api/v1/agents/institution_review/graph` 返回静态流程结构，不表示执行进度。

## 会话助手接口

支持聊天、粘贴正文和可选 DOCX。明确审核意图且参数齐全才调用制度审核，缺少材料或方式时先追问，转移话题时清除待补任务。父子 Agent 共用运行时，审核图在启动时构建并复用。

以下业务路径默认带 `/api/v1`，可由 `API_PREFIX` 修改。认证要求见下文。

| 方法与路径 | 用途 |
| --- | --- |
| `POST /sessions` | 创建会话，返回 201 |
| `GET /sessions?agent_id=conversation_assistant&limit=20&cursor=...` | 按更新时间和 ID 倒序分页，返回 `items/next_cursor` |
| `GET /sessions/{session_id}` | 读取消息和文件元数据 |
| `DELETE /sessions/{session_id}` | 永久删除空闲会话；空 204 才表示清理全部完成 |
| `POST /sessions/{session_id}/files` | multipart 字段 `file` 上传 DOCX，返回文件 ID；不自动审核 |
| `POST /sessions/{session_id}/messages` | JSON `{client_message_id, content, file_ids: []}`，返回 202 和运行记录 |
| `GET /sessions/{session_id}/runs/{run_id}` | 查询状态、结果和错误 |
| `GET /sessions/{session_id}/runs/{run_id}/events` | SSE 订阅执行状态与文本 |
| `POST /sessions/{session_id}/runs/{run_id}/cancel` | 请求停止；重复取消已结束任务不产生新操作 |

相同 `client_message_id` 与内容复用原运行，同 ID 不同内容返回 409。202 只表示已接收；查询 HTTP 200 只表示查询成功，执行是否成功要看 `status` 和 `error`。

消息默认读取最新 50 条，按 `sequence` 升序返回。用 `before_sequence` 读更早消息，`after_sequence` 追赶新消息，两者互斥，`limit` 为 1–100。下一页使用 `next_before_sequence/next_after_sequence`；`last_sequence` 是全会话最高序号，不能代替已收到的位置。

### 流式事件（SSE）

使用锁定的 FastAPI 0.141.1 官方 `EventSourceResponse/ServerSentEvent`，分帧、心跳和响应头交给框架，见 [conversations.py](app/api/conversations.py)。

| 事件 | 内容与客户端处理 |
| --- | --- |
| `snapshot` | `{event, run, text}`，用累计文本替换临时回答 |
| `delta` | `text` 为新增文字，追加显示 |
| `state` | `run` 为运行状态，更新执行阶段 |
| `done` | `run` 含最终状态与正式消息，替换临时回答并结束订阅 |

普通回答推送模型文本，审核只推送阶段与完整结果，不外发意图识别、思考或审核中间输出。订阅、重连不重复调用模型，断开订阅不取消任务。

服务端给出 3000 ms 重连间隔，代理需保持长连接并及时转发。累计文本只在进程内存中保存，重连先取快照，不提供持久事件重放；已归档的最终结果可从数据库读取。

### 记忆、容量与恢复

短期记忆使用官方 `AsyncPostgresSaver` 保存消息、摘要和待补参数，按 `agent_id:session_id` 隔离。每轮只传当前输入和材料目录；多个助手可共享 saver 与公共摘要能力，但各自定义图状态和策略。完整历史、报告与附件另行归档，未接入长期记忆 Store。

上下文预算如下，均按序列化字符计算：

| 项目 | 限制 |
| --- | --- |
| 总上下文 | 24000 字符，最新输入仍放不下时明确失败 |
| 摘要触发 | 已完成消息超过 8 条或 12000 字符，优先保留最近两轮 |
| 摘要 / 摘要分片 / 历史报告片段 | 3000 / 12000 / 4000 字符 |

审核通过材料 ID 读取授权会话内的完整原文，不使用摘要代替材料。成功时，助手消息、完整报告、成功状态与 `memory_checkpoint_id` 同事务提交，再通知完成。失败、取消或容量超限不推进记忆位置；下轮从上次成功位置执行。

| 资源 | 默认限制 |
| --- | --- |
| 每会话 | 8 个文档、100 条消息；材料累计 100000 字符，消息与子结果累计 1000000 字符 |
| 单次消息 / 输出 | 12000 / 200000 字符 |
| 执行 / 等待 | 3 个执行、6 个等待；排队 30 秒、执行 600 秒超时 |
| 临时资源 | `CONVERSATION_TRANSIENT_MAX_BYTES=134217728`，仅约束流式文本和解析中的上传字节，不是进程总内存上限 |

历史不自动过期。同库只允许一个应用进程；重启将未完成任务标记中断，不自动续跑。丢失数据库运行权或最终状态提交失败后停止接纳写入，需重启；关闭时先收尾任务，再关闭资源。

删除先记录清理凭据并确认业务数据已删除，再清理检查点、附件和凭据。忙碌时返回 409；`CONVERSATION_DELETE_INCOMPLETE` 表示数据库已删除、其余清理未完，可重试同一 DELETE。提交结果未知则返回 `STORAGE_UNAVAILABLE` 并保留材料。重复删除幂等，启动会恢复待清理项，关闭会等待已接纳删除。详见[数据库维护](../docs/database.md#存储与维护)。

## 账号与浏览器请求

注册、登录、智能体目录和健康检查公开，其余业务接口要求登录；管理员不能读取他人会话。

| 接口（默认前缀 `/api/v1`） | 用途 |
| --- | --- |
| `POST /auth/register`、`POST /auth/login` | 注册普通账号、登录；注册返回 201，不自动登录或替换已有登录 |
| `GET /auth/me` | 返回 `user/auth_session_id/csrf_token/expires_at` |
| `POST /auth/logout`、`POST /auth/password` | 退出或改密，撤销登录并返回 204 |
| `GET/PATCH /users/me` | 读取或局部更新本人资料 |
| `POST/GET/DELETE /users/me/avatar` | 上传、读取、移除本人头像 |
| `GET/POST /admin/users`、`PATCH /admin/users/{id}` | 管理普通账号 |
| `POST /admin/users/{id}/password-reset` | 重置普通用户临时密码 |
| `GET /admin/users/{id}`、`GET /admin/users/{id}/avatar` | 只读查看资料和头像，包括停用用户及内置 admin |

私有请求携带 Cookie 和 `X-Auth-Session-ID`，写请求再加 `X-CSRF-Token`；SSE 用查询参数携带 `auth_session_id`。浏览器使用 credentials，写请求的 Origin 或 Referer 必须精确匹配 `AUTH_TRUSTED_ORIGINS`。

登录默认有效 12 小时，通过 `AUTH_SESSION_TTL_SECONDS` 配置，期间不自动续期。Cookie 使用 HttpOnly、SameSite=Lax、Path=/；非 development 环境还启用 Secure 和 `__Host-` 前缀。生产环境需配置 `APP_ENV`、可信来源及同源或同站 HTTPS。

用户名为 3–32 位小写字母、数字或下划线，字母开头；密码为 6–20 个 Unicode 字符，不去空格，使用 Argon2 哈希。管理员创建或重置的临时密码须先修改；内置 admin 通过[离线命令](../docs/database.md#admin密码恢复)恢复。

资料中显示名称必填，邮箱、性别、生日、手机号、地址和签名选填；省略字段不变，空值或空白清空可选项。生日为 YYYY-MM-DD，不晚于 UTC+08:00 当天。邮箱和手机号仅为资料，邮箱用 EmailStr 校验语法，不探测 DNS；登录等账号摘要不返回完整联系方式。

头像独立保存：唯一文件字段 `file`，支持 JPG/PNG/WebP，文件最多 2 MiB，请求最多 2 MiB+64 KiB。Pillow 校验静态图片与像素边界，去元数据并转为最长边 512px 的 PNG；同进程最多处理两个，不设无限队列。读取也要身份头，前端通过受保护 Blob 请求展示；重复移除返回 204。管理员没有代编辑资料入口。

## Markdown 导出 Word

`POST /api/v1/documents/export/docx` 接收 JSON，返回 DOCX，独立于模型与 RAGFlow：

```json
{"markdown":"## 简述\n\n审核内容……","title":"制度审核报告"}
```

`markdown` 必填且非空，最多 200000 字符；`title` 默认“制度审核报告”，最多 200 字符，不含控制字符。额外字段、空值或错误类型返回 422。

支持 GFM 标题、段落、粗斜体、列表、引用、代码、链接、表格和无属性 `<br>` 换行；代码及转义中的标签原样保留。图片、带属性标签和其他原始 HTML 返回 422。输出为 A4、2.5 cm 页边距、宋体 / Times New Roman，支持重复表头和自动换行；复杂分页仍需 Word/WPS 验收。

使用 `pypandoc-binary==1.17` 自带 Pandoc，无需系统安装或运行时下载。转换在内存完成，不保存文件、不重做审核；成功返回附件文件名和 `Cache-Control: no-store`。包内程序不可用时导出返回 503，不影响审核启动。

| 配置 | 默认值与含义 |
| --- | --- |
| `DOCUMENT_EXPORT_TIMEOUT_SECONDS` | 30 秒；两次 Pandoc 调用共用，不含排队 |
| `DOCUMENT_EXPORT_CONCURRENCY` | 2；同进程共享，包含转换和样式处理 |
| `DOCUMENT_EXPORT_MAX_CHARS` | 200000，允许 1–200000，独立于上传上限 |
| `DOCUMENT_EXPORT_MAX_BODY_BYTES` | 1048576，实际读取时限制 JSON 字节数 |
| `DOCUMENT_EXPORT_MAX_OUTPUT_BYTES` | 10485760，每次 Pandoc 输出及最终文件上限 |

排队最多 5 秒。超时 504，繁忙或程序不可用 503，请求体超限 413，内容不支持或输出超限 422，其他转换失败 500。保留原 Markdown 后重试下载即可，详见[错误码](../docs/errors.md#word-导出)。

## Langfuse（可选）

用于调用追踪、远端 Prompt 和合成数据实验；不影响核心功能的启用。锁定 Python SDK 5.0.2，自托管服务按原部署要求使用 4.59.0+。

- 设置后端凭据与 `LANGFUSE_ENABLED=true`。默认 `LANGFUSE_CAPTURE_CONTENT=false`，仅上传标识、状态、用量和白名单元数据；开启正文采集才上传正文与图状态，凭据始终过滤。上报失败不改变业务结果。
- 会话每轮独立追踪，以 session_id 分组；健康、状态查询与 SSE 订阅不重复追踪。
- Token 用供应商 usage；美元费用按 Langfuse 模型价表估算，缺价格或用量为未知，不统计 RAGFlow 内部不可见费用。
- 人民币估算需精确匹配 `LANGFUSE_COST_MODEL`，并填输入、输出、缓存输入的 `LANGFUSE_*_CNY_PER_MILLION` 价格；写入 metadata 的 `estimated_cost_cny`，不替代美元 `cost_details`。服务不自动同步价格或汇率，历史费用不补算。

当前共 9 个 Prompt，覆盖摘要、意图、回答及审核。追踪和 `LANGFUSE_PROMPTS_ENABLED` 都开启时，按 `LANGFUSE_PROMPT_LABEL`（默认 production）读取远端模板，同一轮固定版本。普通请求读取失败回退本地模板，固定版本实验则失败；通过标签发布或回滚。

在 `backend/` 执行：

```powershell
# 查看差异；apply 只创建缺失模板，不覆盖冲突或移动已有标签
uv run python -m scripts.sync_langfuse_prompts --dry-run
uv run python -m scripts.sync_langfuse_prompts --apply --initial-label development

# 离线检查，不调用模型或远端
uv run python -m scripts.run_langfuse_experiments --dataset tests/fixtures/langfuse/conversation_cases.json --prompt-versions tests/fixtures/langfuse/prompt_versions.example.json --run-name conversation-v1 --dry-run

# 真实实验：消耗模型额度并写入 Langfuse
uv run python -m scripts.run_langfuse_experiments --dataset tests/fixtures/langfuse/standard_review_cases.json --prompt-versions tests/fixtures/langfuse/prompt_versions.example.json --run-name standard-v1 --dataset-name agent-platform/acceptance-standard --execute --sync-dataset
```

实验前将示例版本号替换成远端真实版本。`--sync-dataset` 仅补建缺失合成项，冲突时失败，不覆盖。默认并发 1，失败计入总数；执行真实注册表与图，使用独立 InMemorySaver 和合成材料，不读取用户会话。关闭追踪和 Prompt 开关可恢复本地模板，已上传数据仍保留。真实效果、计量和价格需另行验收。

## 开发检查

在 `backend/` 运行 `uv run ruff check app scripts tests` 和 `uv run pytest`。数据库用例须显式提供专用 `TEST_DATABASE_URL`，不能使用应用库；准备方法见[测试与维护](../docs/database.md#测试与维护)。

检查覆盖与人工验收边界统一见[质量门禁](../docs/ai-coding/quality-gates.md)。代码位置见[项目目录](../docs/ai-coding/project-structure.md)，分层约束见[架构规则](../docs/ai-coding/architecture-rules.md)。
