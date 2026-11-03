# 错误码

- 核对日期：2026-11-02。
- 本文是错误响应与恢复行为的文档，不是新增运行时错误码注册表。
- 错误码取自当前源码，包含公开注册、账号管理和私有会话。模块边界见[项目架构目录](ai-coding/project-structure.md)与[架构规则](ai-coding/architecture-rules.md)。
- HTTP 状态以具体入口为准，不根据错误码名称推断，不在本次文档任务统一历史差异。

## 响应与处理原则

HTTP 错误由 [core/errors.py](../backend/app/core/errors.py) 输出：

```json
{"error":{"code":"CONVERSATION_NOT_FOUND","message":"会话不存在","request_id":"请求标识"}}
```

参数验证可附加 `details:[{field,message}]`。message 是面向用户的安全说明，允许随场景变化；客户端判断使用 status/code，故障定位使用 request_id，不匹配中文文案。不得返回密码、哈希、Cookie、认证头、内部文件路径或异常原文。

异步会话提交成功返回 202，不代表运行成功。后续 GET 运行和 SSE 的 RunView 中，`status=failed` 的 `error:{code,message}` 描述业务失败；HTTP 200 只代表查询成功。运行成功/失败/取消的判断必须读取 status。SSE 已发响应头后的失效不能改成 HTTP 401，也不能伪造业务 done。

前端断网的 `ApiError.status=0` 是本地客户端状态，不是服务端 HTTP 状态或错误码；AbortSignal 取消也不等于服务端运行已取消。

所有“重试”均由用户或既有明确策略发起。认证恢复后不自动重放消息、删除、审核、上传或导出；幂等提交保持原 client_message_id 和原请求内容，不能生成新 ID 假装重试。

## 现有：通用与运行环境

来源：[错误处理](../backend/app/core/errors.py)、[会话仓储](../backend/app/infrastructure/conversation/postgres_store.py)、[模型适配](../backend/app/infrastructure/llm/chat_model.py)。

| 错误码 | HTTP | 含义与处理 |
| --- | --- | --- |
| `VALIDATION_ERROR` | 422 | 请求模型验证失败，修正 details 指向的字段 |
| `INTERNAL_ERROR` | 500 | 未预期异常；显示安全提示并保留 request_id，不暴露内部栈 |
| `SERVICE_NOT_READY` | 503 | 目录、会话或模型用例尚未就绪，检查服务状态/配置 |
| `MODEL_NOT_CONFIGURED` | 503 | 模型供应商不支持或模型/API Key 缺失，由部署端修复 |
| `STORAGE_UNAVAILABLE` | 503 | 数据库、运行权或提交结果不能确认；不把它当作“无记录”或写入成功 |
| `STORAGE_IN_USE` | 503 | 同库已有运行进程，第二实例拒绝启动；保持单工作进程 |
| `STORAGE_SCHEMA_INVALID` | 503 | 内置管理员未初始化，或附件删除凭据格式无效、需要离线核实修复；按部署及维护流程处理 |

## 现有：会话、文件引用与删除

来源：[会话 API](../backend/app/api/conversations.py)、[会话用例](../backend/app/services/conversation_service.py)、[仓储](../backend/app/infrastructure/conversation/postgres_store.py)、[活动运行](../backend/app/infrastructure/conversation/active_runs.py)、[文件存储](../backend/app/infrastructure/documents/local_file_store.py)。

| 错误码 | HTTP | 含义与处理 |
| --- | --- | --- |
| `INVALID_CONVERSATION_INPUT` | 422 | 非法消息、文件引用、分页参数或游标；修正后重试 |
| `CONVERSATION_INPUT_TOO_LARGE` | 413 | JSON 消息请求体超过 65536 字节，缩小请求 |
| `CONVERSATION_INPUT_TOO_LONG` | 422 | 转义/序列化后超过模型上下文预算，缩短输入 |
| `CONVERSATION_NOT_FOUND` | 404 | 会话/持久记录不存在；未来还用于隐藏他人资源，不能据此推断其真实存在性 |
| `MATERIAL_NOT_FOUND` | 404 | 附件不存在或不属于指定会话，重新选择合法材料 |
| `RUN_NOT_FOUND` | 404 | 运行不存在或不匹配指定会话 |
| `MESSAGE_CONFLICT` | 409 | 相同 client_message_id 对应不同内容，不能覆盖旧请求 |
| `CONVERSATION_BUSY` | 409 / 503 | 409：同会话正在操作或收尾，等待/停止后重试；503：提交时全局接纳额度不足。不只按 code 决定行为 |
| `CONVERSATION_CAPACITY` | 413 | 会话持久容量或临时资源额度不足；按提示减少输入、等待资源或显式新建 |
| `FILE_UNAVAILABLE` | 503 | 文件丢失、正文校验失败、路径不安全或清理凭据无效；不使用空材料继续执行 |
| `CONVERSATION_DELETE_INCOMPLETE` | 503 | 数据库删除已确认，附件/凭据清理未完成；清除本地正文，保留同一 ID 的清理重试，不重建会话 |

未知删除提交结果仍是 STORAGE_UNAVAILABLE；不能把所有 503 都解释为“会话已经删除”。不存在且无凭据的合法 UUID 的 DELETE 幂等返回 204，不是错误。

## 现有：文档解析与审核输入

来源：[审核用例](../backend/app/services/review_service.py)、[公共解析](../backend/app/nodes/document/parse.py)、[会话上传错误映射](../backend/app/services/conversation_service.py)。

| 错误码 | HTTP | 含义与处理 |
| --- | --- | --- |
| `UNSUPPORTED_DOCUMENT_TYPE` | 415 | 只支持 DOCX，不能仅改扩展名规避真实解析 |
| `EMPTY_DOCUMENT` | 422 | 上传字节为空 |
| `UPLOAD_TOO_LARGE` | 413 | 原件过大，或会话公共解析发现解压内容/条目超过限制 |
| `INVALID_DOCX` | 422 | 文档损坏、不是可读取 DOCX 或没有有效文字 |
| `REVIEW_CONTENT_TOO_LONG` | 422 / 413 | 独立审核正文过长是 422；会话上传解析映射为 413，现状保留 |
| `REVIEW_CONTENT_EMPTY` | 422 | 文本没有可审核的条款内容 |
| `INVALID_REVIEW_INPUT` | 422 | 审核模式、草稿或标准材料组合无效 |
| `STANDARD_DOCUMENT_REQUIRED` | 422 | 标准文档模式缺少标准材料 |

## 现有：Word 导出

来源：[导出 API](../backend/app/api/document_exports.py)、[导出服务](../backend/app/services/document_export_service.py)、[Pandoc 适配](../backend/app/infrastructure/pandoc.py)。

| 错误码 | HTTP | 含义与处理 |
| --- | --- | --- |
| `INVALID_EXPORT_INPUT` | 422 | 非 JSON、标题/Markdown 无效或正文字数超限 |
| `EXPORT_REQUEST_TOO_LARGE` | 413 | 导出请求体超限 |
| `EXPORT_CONTENT_UNSUPPORTED` | 422 | 图片或不支持的原始 HTML 等内容被拒绝；合法换行沿用现有规则 |
| `EXPORT_OUTPUT_TOO_LARGE` | 422 | 转换结果超过大小上限，不截断 DOCX |
| `DOCUMENT_EXPORT_BUSY` | 503 | 同进程导出额度暂满，保留报告后重试下载 |
| `DOCUMENT_EXPORT_UNAVAILABLE` | 503 | 转换程序缺失、不可启动、服务关闭或尚未装配 |
| `DOCUMENT_EXPORT_TIMEOUT` | 504 | 转换超时，保留报告；重试下载不重新审核 |
| `DOCUMENT_EXPORT_FAILED` | 500 | 转换、AST 或 DOCX 处理失败，保留报告和 request_id |

## 现有：Agent、模型与知识库

来源：[运行时](../backend/app/runtime/agent_runtime.py)、[注册](../backend/app/agents/__init__.py)、[流程元数据](../backend/app/services/agent_graph_service.py)、[会话 Agent](../backend/app/agents/conversation_assistant/adapter.py)、[审核图](../backend/app/agents/institution_review/graph/chunk_review.py)、[RAGFlow](../backend/app/infrastructure/ragflow/client.py)。

| 错误码 | HTTP | 含义与处理 |
| --- | --- | --- |
| `INVALID_AGENT_ID` | 500 | 注册标识为空，属于部署/代码错误 |
| `DUPLICATE_AGENT_ID` | 500 | 注册标识重复，不能由用户反复提交解决 |
| `AGENT_REGISTRATION_INVALID` | 500 | 注册入口或构建依赖无效 |
| `AGENT_NOT_FOUND` | 404 | 智能体不存在或没有可执行注册项 |
| `AGENT_GRAPH_NOT_FOUND` | 404 | 该智能体没有可展示的静态流程 |
| `INVALID_AGENT_INPUT` | 422 | Agent 本轮业务输入无效 |
| `INVALID_AGENT_ACTION` | 422 / 502 | 缺少验证后的图动作参数为 422；模型/流程产出不可执行动作可为 502 |
| `AGENT_OUTPUT_INVALID` | 502 | 结果结构缺失、不完整或不是约定输出 |
| `AGENT_OUTPUT_TOO_LARGE` | 502 | 子结果超过可展示上限，不默默截断 |
| `AGENT_EXECUTION_FAILED` | 502 | 运行时捕获的未映射执行异常 |
| `GRAPH_CONFIGURATION_ERROR` | 500 | 审核图配置或分块内部状态不一致 |
| `CONVERSATION_INTENT_FAILED` | 502 | 本轮意图识别失败 |
| `MODEL_ERROR` | 502 | 模型调用或输出格式失败，不伪造成功回答 |
| `RAGFLOW_NOT_CONFIGURED` | 503 | 知识库模式配置缺失；标准文档模式仍按其独立条件判断 |
| `RAGFLOW_TIMEOUT` | 503 | 知识库检索超时；当前不是 504，不在文档任务修改 |
| `RAGFLOW_ERROR` | 502 | 检索请求或返回格式错误 |

## 现有：运行结果中的错误码

来源：[会话执行](../backend/app/services/conversation_service.py)、[中断恢复](../backend/app/infrastructure/conversation/postgres_store.py)。以下没有独立固定 HTTP 状态，出现在成功查询到的失败 RunView 中：

| 错误码 | 含义与处理 |
| --- | --- |
| `CONVERSATION_TIMEOUT` | 排队或执行超过限制，需要用户决定是否重新提交；不自动恢复原模型执行 |
| `CONVERSATION_FAILED` | 未映射的后台执行失败，显示安全错误说明 |
| `CONVERSATION_INTERRUPTED` | 服务重启或提交确认后发现本地执行已不存在；保留失败历史，不自动重做 |

后台 AppError 的 code/message 也可被保存为运行错误，例如 MODEL_ERROR、CONVERSATION_CAPACITY。`cancelled` 正常终态不要求附加一个虚构的取消错误码。

## 账号与认证

以下为已实现的HTTP错误及前端恢复行为。

| 错误码 | HTTP | 触发与前端行为 |
| --- | --- | --- |
| `AUTH_REQUIRED` | 401 | 登录缺少/过期/撤销或用户停用；失效认证代次、清理私有状态并引导登录 |
| `INVALID_CREDENTIALS` | 401 | 不存在、密码错误、停用统一登录失败；停留登录页，不泄露账号状态 |
| `FORBIDDEN` | 403 | 已登录但不是管理员等权限不足；提示无权限，不当作退出 |
| `PASSWORD_CHANGE_REQUIRED` | 403 | 临时密码登录禁止业务访问；清理业务状态、进入改密页 |
| `CSRF_REJECTED` | 403 | 来源或会话同步 token 不合法；拒绝操作，不自动重试 |
| `AUTH_CONTEXT_CHANGED` | 409 | Cookie 身份与请求绑定的公开 auth_session_id 不匹配；清理旧上下文，重新确认/登录，不重放 |
| `USERNAME_EXISTS` | 409 | 自助注册或管理员创建的规范化用户名重复/被保留；并发同名至多一个成功 |
| `BUILTIN_ADMIN_PROTECTED` | 409 | 试图通过管理接口停用/重置内置 admin 等受保护操作 |
| `PASSWORD_INVALID` | 422 | 当前密码错误、新旧密码相同或密码规则不满足；保留可修改表单，不退出 |
| `LOGIN_RATE_LIMITED` | 429 | 登录失败窗口超限；返回 Retry-After，倒计时后由用户重试 |
| `REGISTRATION_RATE_LIMITED` | 429 | 每来源IP滚动600秒注册有效尝试超过10次，哈希/写入前拒绝，返回Retry-After；不自动重试 |
| `AUTH_BUSY` | 429 | 密码计算并发或等待容量已满；返回 Retry-After，不自动提交 |
| `AUTH_REQUEST_TOO_LARGE` | 413 | 新认证/用户 JSON 写请求超过 16384 字节，完整解析前拒绝 |
| `USER_NOT_FOUND` | 404 | 管理员操作的用户不存在；先检查调用方权限，不向普通用户泄漏目标信息 |

用户体系继续复用 VALIDATION_ERROR、STORAGE_UNAVAILABLE 和现有资源 404，不引入“他人会话存在但无权读取”的独立错误码。API 返回认证错误不发送 Set-Cookie；只有登录成功响应设置 Cookie，避免旧响应清掉新登录。

注册接口是公开入口，来源/JSON校验失败使用CSRF_REJECTED/VALIDATION_ERROR，不要求旧会话token；额外role/status/user_id字段422。201注册成功只返回UserView，不建立登录，不触发账号切换。注册名称可用性由明确的409反馈，不返回密码/哈希。

BaseDatabase的DatabaseConstraintError只在Python基础设施内部传递sqlstate/constraint_name，不是新增HTTP错误码。仓储仅把users_username_key的23505映射USERNAME_EXISTS；连接/超时/失联仍为STORAGE_UNAVAILABLE，未知提交结果不能转成成功或用户名重复。驱动异常正文不返回客户端。

## 维护规则

1. 修改错误码、状态、对外 message 或恢复行为时，同步 API 行为检查和本文；拟新增项实现后才移入现有分组。
2. 一个 code 当前对应多个状态时先按事实列出，规范化须另有需求/契约批准。
3. 错误码新增不等于授权新的自动重试、管理员越权、持久任务恢复或数据清理行为。
4. 未知错误码显示安全 message 和 request_id，保留已有内容；不据未知错误猜测已经删除、已经退出或执行成功。
