# 智能体平台后端

基于 Python 3.12/3.13、FastAPI、LangChain、LangGraph 和 RAGFlow 的制度审核与会话服务。独立审核接口同步返回报告；会话助手通过意图识别决定普通回答、追问或调用现有制度审核，异步运行并通过查询接口返回状态与真实输出。不依赖 Redis 或关系型数据库。

## 临时会话助手

上传为可选步骤：无文件直接发消息，也可上传 DOCX 或将正文粘贴为用户消息。普通聊天、制度概念解释和摘要仅调用聊天模型，明确制度审核意图且参数齐全才执行子智能体。缺少审核方式、草稿或标准角色时先追问，用户转移话题时清除待补齐任务。只接入 `institution_review`，不新增工作汇总、报告生成 Agent。

`conversation_assistant/graph/` 使用 LangGraph 表达材料准备、上下文选择、结构化意图识别、参数门控及回复/子调用分支。`ConversationService` 只负责会话用例、任务生命周期和 HTTP 映射；`infrastructure/conversation/in_memory_store.py` 保存中立会话记录。业务图状态与存储分开，未接入 checkpointer。

上传阶段调用 `nodes/document/parse.py` 并复用既有 DOCX 转换器，聊天不重复解析。通用输入预算由 `nodes/llm/context.py` 处理，材料选择策略留在会话 Agent；模型上下文最多 24000 个序列化字符，历史审核结果仅带最多 4000 字符片段，审核始终使用独立保留的完整原文。父子调用通过同一个 `AgentRuntime`，制度审核图在启动时构建并复用。

以下路径沿用 `api_prefix`（默认 `/api/v1`）：

| 方法与路径 | 行为 |
| --- | --- |
| `POST /api/v1/conversations` | 创建临时会话，返回 201 |
| `GET /api/v1/conversations/{id}?after_sequence=0` | 读取消息和文档元数据，支持按消息序号增量获取 |
| `POST /api/v1/conversations/{id}/documents` | multipart 字段 `file` 上传一份 DOCX，返回文档 ID；不自动触发审核 |
| `POST /api/v1/conversations/{id}/messages` | JSON `{client_message_id, content, document_ids: []}`，返回 202 及运行 ID |
| `GET /api/v1/conversations/{id}/runs/{run_id}` | 查询 queued/running/succeeded/failed/cancelled 及结果 |
| `POST /api/v1/conversations/{id}/runs/{run_id}/cancel` | 停止任务；终态请求幂等 |

相同 `client_message_id` 与相同内容复用原运行；同 ID 异内容返回 409。失败运行仍以 HTTP 200 返回运行资源，并在 `error` 中保存安全错误；只有请求本身无效时使用 HTTP 错误。无模型配置时可管理会话及材料，消息执行返回 503。知识库配置只影响知识库审核。

会话使用单进程内存，空闲默认 7200 秒、最长 28800 秒；轮询不续期，服务重启清空。每会话最多 8 文档/100 消息，用户消息 12000 字符，材料累计 100000 字符，输出单次最多 200000 字符。进程默认 3 个运行、6 个等待，排队 30 秒、运行 600 秒超时。配置为 `CONVERSATION_IDLE_SECONDS`、`CONVERSATION_LIFETIME_SECONDS`、`CONVERSATION_MAX_SESSIONS`（100）、`CONVERSATION_MAX_BYTES`（134217728）、`CONVERSATION_CONCURRENCY`、`CONVERSATION_QUEUE_SIZE`、`CONVERSATION_RUN_TIMEOUT_SECONDS`、`CONVERSATION_QUEUE_TIMEOUT_SECONDS`。字节预算仅限制业务载荷，不等于进程 RSS 上限。

会话任务与 DOCX 解析并发受控，应用关闭先回收任务再关闭外部客户端。原始上传文件不落盘，正文仅保存在会话内。请使用单工作进程；本次没有用户认证、跨进程恢复或多用户权限隔离。

## 环境准备

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

未发现问题默认通过，通过条款不进入报告问题汇总上下文；模型和检索调用失败仍返回错误。标准发现需有组内真实条款序号及可在标准中定位的原文摘录。最终 Markdown 保持简述、冲突检测、术语检测和修改建议四部分。文档读取复用公共 `app/nodes/`。

后端测试使用假模型与检索器，覆盖分组、跨请求并发额度、取消清理、完整审核图与 ASGI 双文件入口，不消耗真实账户额度。真实模型准确率、上下文适配及吞吐需另行验收，知识库联调需可用的检索服务与额度。

## Markdown 导出 Word

请求为 `application/json`，例如 `{"markdown":"## 一. 简述\n\n审核内容……","title":"制度审核报告"}`。`markdown` 必填且非空白，最多 200000 字符；`title` 默认“制度审核报告”，最多 200 字符且不能含控制字符。额外字段、空值和错误类型返回 422。服务转换请求中的内容，不证明其来自某次原始审核。

可先将 JSON 请求保存为 UTF-8 的 `request.json`，再执行：

```powershell
curl.exe -X POST "http://127.0.0.1:8000/api/v1/documents/export/docx" -H "Content-Type: application/json" --data-binary "@request.json" --output "制度审核报告.docx"
```

成功响应为 `application/vnd.openxmlformats-officedocument.wordprocessingml.document`，包含附件文件名和 `Cache-Control: no-store`。服务通过内存返回文件，不保存审核结果或附件。前端报告页通过“下载 Word”按钮调用此接口。`DocumentExportService.export_docx()` 同时可由后续 Python 业务工具复用，返回文件字节、文件名和 MIME 类型；Chat 和 MCP 尚未接入。

支持 GFM 标题、段落、粗斜体、列表、引用、分隔线、代码、常规链接及管道表格。真实图片和原始 HTML 返回 422，代码中的同样文字保留。Word 使用 A4、2.5 cm 页边距、宋体/Times New Roman 正文、重复表头和自动换行；字体不嵌入，复杂排版需在目标 Word/WPS 环境验收。

| 环境配置 | 默认值 | 范围与含义 |
| --- | --- | --- |
| `DOCUMENT_EXPORT_TIMEOUT_SECONDS` | 30 | 正数；两次 Pandoc 调用共享预算，不含排队 |
| `DOCUMENT_EXPORT_CONCURRENCY` | 2 | 正整数；同进程所有导出共享，包含转换及样式处理 |
| `DOCUMENT_EXPORT_MAX_CHARS` | 200000 | 1–200000；独立于上传文档字符上限 |
| `DOCUMENT_EXPORT_MAX_BODY_BYTES` | 1048576 | 正整数；JSON 请求体字节上限，实际读取时执行 |
| `DOCUMENT_EXPORT_MAX_OUTPUT_BYTES` | 10485760 | 正整数；每次 Pandoc 输出及最终文件大小上限 |

排队最多 5 秒；多工作进程分别计算并发额度。超时返回 504，繁忙或引擎不可用返回 503，请求体超限返回 413，内容不支持或文件超限返回 422，其他转换失败返回 500。失败响应使用现有统一错误结构，不包含文档、机器路径或原始进程诊断。原 Markdown 可独立重试导出。
