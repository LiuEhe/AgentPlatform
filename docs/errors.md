# 错误码

本文列出当前已实现的错误码。客户端依据 HTTP 状态与 `code` 判断，使用 `message` 展示安全提示、`request_id` 定位问题；同一码的状态差异以具体入口为准。响应格式见 [core/errors.py](../backend/app/core/errors.py)：

```json
{"error":{"code":"CONVERSATION_NOT_FOUND","message":"会话不存在","request_id":"请求标识"}}
```

参数验证可附带 `details:[{field,message}]`，响应不得包含密钥、内部路径或异常原文。

| 场景 | 处理说明 |
| --- | --- |
| 异步运行 | 202 仅表示接收提交；查询 HTTP 200 仅表示查询成功，执行结果读取 RunView.status 与 error |
| 失败与取消 | 后台 AppError 也可保存为运行错误；cancelled 是正常终态，无需取消错误码；SSE 响应头发出后不能改 HTTP 状态或伪造成功 |
| 网络与重试 | 前端 status=0 表示本地网络异常；取消请求不等于取消运行；不自动重放操作，幂等重试保留原 client_message_id 与内容 |
| 删除结果 | 提交未知为 STORAGE_UNAVAILABLE；只有 CONVERSATION_DELETE_INCOMPLETE 确认数据库已删除；无会话且无凭据时 DELETE 返回 204 |
| 未知错误码 | 展示安全 message 与 request_id，保留已有内容，不猜测删除、登录或执行结果 |

## 通用与运行环境

| 错误码 | HTTP | 含义与处理 |
| --- | --- | --- |
| `VALIDATION_ERROR` | 422 | 请求参数无效，按 details 修正字段 |
| `INTERNAL_ERROR` | 500 | 未预期异常，保留 request_id 排查 |
| `SERVICE_NOT_READY` | 503 | 服务尚未就绪，检查状态与配置 |
| `MODEL_NOT_CONFIGURED` | 503 | 模型配置缺失或不支持，需部署端修复 |
| `STORAGE_UNAVAILABLE` | 503 | 存储不可用或提交结果未知，不能认定写入成功或记录不存在 |
| `STORAGE_IN_USE` | 503 | 同库已有应用进程，保持单工作进程 |
| `STORAGE_SCHEMA_INVALID` | 503 | 管理员未初始化或删除凭据格式无效，需维护处理 |

## 会话、文件引用与删除

| 错误码 | HTTP | 含义与处理 |
| --- | --- | --- |
| `INVALID_CONVERSATION_INPUT` | 422 | 消息、文件引用或分页参数无效 |
| `CONVERSATION_INPUT_TOO_LARGE` | 413 | 消息请求体超过 65536 字节，缩小请求 |
| `CONVERSATION_INPUT_TOO_LONG` | 422 | 超出模型上下文预算，缩短输入 |
| `CONVERSATION_NOT_FOUND` | 404 | 会话不存在或不属于当前用户 |
| `MATERIAL_NOT_FOUND` | 404 | 材料原文不存在、引用非用户消息或不属于指定会话 |
| `RUN_NOT_FOUND` | 404 | 运行不存在或不属于指定会话 |
| `MESSAGE_CONFLICT` | 409 | 同一 client_message_id 对应不同内容，不能覆盖旧请求 |
| `CONVERSATION_BUSY` | 409 / 503 | 409：会话正在操作或收尾；503：全局接纳额度不足，等待后重试 |
| `CONVERSATION_CAPACITY` | 413 | 会话容量或临时额度不足，减少输入、等待或新建会话 |
| `FILE_UNAVAILABLE` | 503 | 文件缺失、正文校验失败或路径/凭据无效，不能以空材料继续 |
| `CONVERSATION_DELETE_INCOMPLETE` | 503 | 数据库已删除，检查点、附件或凭据清理未完成；清除本地正文，保留原 ID 重试清理 |

## 文档解析与审核输入

| 错误码 | HTTP | 含义与处理 |
| --- | --- | --- |
| `UNSUPPORTED_DOCUMENT_TYPE` | 415 | 文件类型不支持，仅接受 DOCX |
| `EMPTY_DOCUMENT` | 422 | 上传文件为空 |
| `UPLOAD_TOO_LARGE` | 413 | 原件或解压后的内容/条目超过限制 |
| `INVALID_DOCX` | 422 | DOCX 损坏、格式无效或没有有效文字 |
| `REVIEW_CONTENT_TOO_LONG` | 422 / 413 | 正文过长；独立审核为 422，会话上传为 413 |
| `REVIEW_CONTENT_EMPTY` | 422 | 没有可审核的条款内容 |
| `INVALID_REVIEW_INPUT` | 422 | 审核模式或材料组合无效 |
| `STANDARD_DOCUMENT_REQUIRED` | 422 | 标准文档模式缺少标准材料 |

## Word 导出

| 错误码 | HTTP | 含义与处理 |
| --- | --- | --- |
| `INVALID_EXPORT_INPUT` | 422 | JSON、标题或 Markdown 无效，或正文超限 |
| `EXPORT_REQUEST_TOO_LARGE` | 413 | 导出请求体超限 |
| `EXPORT_CONTENT_UNSUPPORTED` | 422 | 包含图片或不支持的原始 HTML 等内容 |
| `EXPORT_OUTPUT_TOO_LARGE` | 422 | DOCX 结果超限，不截断输出 |
| `DOCUMENT_EXPORT_BUSY` | 503 | 导出额度暂满，保留报告后重试下载 |
| `DOCUMENT_EXPORT_UNAVAILABLE` | 503 | 转换程序或导出服务不可用 |
| `DOCUMENT_EXPORT_TIMEOUT` | 504 | 转换超时，保留报告后重试下载，无需重新审核 |
| `DOCUMENT_EXPORT_FAILED` | 500 | 转换失败，保留报告与 request_id |

## Agent、模型与知识库

| 错误码 | HTTP | 含义与处理 |
| --- | --- | --- |
| `INVALID_AGENT_ID` | 500 | 注册标识为空，需修复代码或部署配置 |
| `DUPLICATE_AGENT_ID` | 500 | 注册标识重复 |
| `AGENT_REGISTRATION_INVALID` | 500 | 注册入口或构建依赖无效 |
| `AGENT_NOT_FOUND` | 404 | 智能体不存在或未注册执行能力 |
| `AGENT_GRAPH_NOT_FOUND` | 404 | 智能体没有可展示的静态流程 |
| `INVALID_AGENT_INPUT` | 422 | Agent 业务输入无效 |
| `INVALID_AGENT_ACTION` | 422 / 502 | 422：缺少已验证动作参数；502：模型或流程产出不可执行动作 |
| `AGENT_OUTPUT_INVALID` | 502 | 结果结构缺失、不完整或不符合约定 |
| `AGENT_OUTPUT_TOO_LARGE` | 502 | 子结果超出展示上限，不截断输出 |
| `AGENT_EXECUTION_FAILED` | 502 | 未映射的 Agent 执行异常 |
| `GRAPH_CONFIGURATION_ERROR` | 500 | 审核图配置或分块内部状态不一致 |
| `CONVERSATION_INTENT_FAILED` | 502 | 意图识别失败 |
| `MODEL_ERROR` | 502 | 模型调用或输出格式失败 |
| `RAGFLOW_NOT_CONFIGURED` | 503 | 知识库模式配置缺失；标准文档模式单独判断 |
| `RAGFLOW_TIMEOUT` | 503 | 知识库检索超时 |
| `RAGFLOW_ERROR` | 502 | 检索请求或返回格式错误 |

## 运行结果中的错误码

以下错误出现在失败的 RunView 中，没有独立固定 HTTP 状态。

| 错误码 | 含义与处理 |
| --- | --- |
| `CONVERSATION_TIMEOUT` | 排队或执行超时，由用户决定是否重新提交 |
| `CONVERSATION_FAILED` | 未映射的后台执行失败 |
| `CONVERSATION_INTERRUPTED` | 重启或本地任务丢失导致中断，保留失败历史，不自动重做 |

## 账号与认证

| 错误码 | HTTP | 含义与处理 |
| --- | --- | --- |
| `AUTH_REQUIRED` | 401 | 未登录、登录失效或用户停用；清理私有状态并引导登录 |
| `INVALID_CREDENTIALS` | 401 | 统一登录失败提示，不区分账号不存在、密码错误或停用 |
| `FORBIDDEN` | 403 | 权限不足，提示无权限，不退出登录 |
| `PASSWORD_CHANGE_REQUIRED` | 403 | 临时密码须先修改，清理业务状态并进入改密页 |
| `CSRF_REJECTED` | 403 | 来源或 CSRF token 校验失败，拒绝操作 |
| `AUTH_CONTEXT_CHANGED` | 409 | 请求绑定身份与 Cookie 不一致，清理旧上下文并重新确认登录 |
| `USERNAME_EXISTS` | 409 | 用户名重复或被保留，修改用户名 |
| `BUILTIN_ADMIN_PROTECTED` | 409 | 内置管理员的受保护操作被拒绝 |
| `PASSWORD_INVALID` | 422 | 当前密码错误或新密码不符合规则，保留表单供修改 |
| `LOGIN_RATE_LIMITED` | 429 | 登录失败过多，按 Retry-After 等待后由用户重试 |
| `REGISTRATION_RATE_LIMITED` | 429 | 同一来源 IP 的 600 秒注册窗口超过 10 次有效尝试，按 Retry-After 等待 |
| `AUTH_BUSY` | 429 | 密码计算并发或等待容量已满，按 Retry-After 等待 |
| `AUTH_REQUEST_TOO_LARGE` | 413 | 认证或用户写请求超过 16384 字节 |
| `AVATAR_TOO_LARGE` | 413 | 头像文件超过2 MiB或multipart请求超过2 MiB+64 KiB |
| `AVATAR_TYPE_UNSUPPORTED` | 415 | 头像文件类型不支持，选择JPG、PNG或WebP |
| `AVATAR_INVALID` | 422 | 头像为空、损坏、多帧或像素尺寸超限 |
| `AVATAR_BUSY` | 429 | 同进程两个头像处理额度已满，稍后重试 |
| `AVATAR_NOT_FOUND` | 404 | 未设置头像或对应文件缺失，展示默认头像 |
| `AVATAR_UNAVAILABLE` | 503 | 头像文件读写故障，保留资料草稿并重试 |
| `USER_NOT_FOUND` | 404 | 管理员操作的目标用户不存在 |

## 维护

调整错误码、HTTP 状态或恢复行为时，同步相关行为检查与本文；内部数据库异常不作为 HTTP 错误码。实现入口见[会话服务](../backend/app/services/conversation_service.py)、[认证服务](../backend/app/services/auth_service.py)、[用户服务](../backend/app/services/user_service.py)、[审核服务](../backend/app/services/review_service.py)、[导出服务](../backend/app/services/document_export_service.py)和[运行时](../backend/app/runtime/agent_runtime.py)。
