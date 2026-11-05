# 数据库设计与初始化

项目使用 PostgreSQL 18。数据库保存账号、登录和完整会话历史；附件与头像保存在本地目录。应用启动只检查，不自动建表或迁移。

首次部署读“连接与配置”和“初始化”；日常运维读“存储与维护”；查字段时跳到[表结构](#表结构)。业务结构以 [schema_v4.sql](../backend/database/schema_v4.sql) 为准，官方记忆表由 LangGraph 库维护。

## 连接与配置

本地默认地址为 `127.0.0.1:5432`，用户 `postgres`；应用库 `agent_platform`，专用测试库 `agent_platform_test`。按实际环境调整，连接串密码中的保留字符需 URL 编码。

| 配置 | 用途与默认值 |
| --- | --- |
| `DATABASE_URL` | 应用连接串，放在被 Git 忽略的 `backend/.env` |
| `TEST_DATABASE_URL` | 测试终端显式提供，只允许 `agent_platform_test`，不回退应用库 |
| `DATABASE_POOL_MIN_SIZE/MAX_SIZE` | 业务池和检查点池各默认 1 / 5；另有一个独立运行权连接，总连接预算需一起计算 |
| `DATABASE_TIMEOUT_SECONDS` | 数据库操作超时，默认 5 秒 |
| `DOCUMENTS_DIR` | 附件根目录，默认 `backend/documents` |
| `AVATARS_DIR` | 头像根目录，默认 `backend/avatars` |

两个文件目录的相对路径均按 `backend/` 解析。

## 初始化

**仅用于新环境。** 已有业务表不能重复初始化；当前结构为 v4，没有旧版数据升级或兼容入口。

1. 在 PostgreSQL 的 `postgres` 管理库执行 [create_databases.sql](../backend/database/create_databases.sql)，创建应用库和测试库。
2. 配置 `backend/.env`，确认 `DATABASE_URL` 指向目标应用库。
3. 在 `backend/` 执行：

```powershell
uv run python -m scripts.manage_users initialize
```

按隐藏输入提示设置并确认管理员密码，长度 6–20 字符。完成后按[后端说明](../backend/README.md#安装与启动)启动；Windows 须保留 Selector loop 参数。

推荐用管理命令完成初始化。直接执行 `schema_v4.sql` 会写入开发/测试默认管理员账号；管理命令会将其替换为现场输入的密码，且一并创建官方检查点表。

初始化先执行官方 `setup()`，再用业务事务建表并设置密码。两步并非一个原子事务：若失败后只残留官方表，可重试；已有业务表或未知表时拒绝初始化。旧环境需另建空库，或经明确批准后重建，不能直接覆盖原数据。

### 补建官方检查点表

已直接执行 `schema_v4.sql`、启动提示“检查点结构尚未初始化”时，先停后端，再在 `backend/` 执行：

```powershell
uv run python -m scripts.manage_users setup-checkpoints
```

只调用官方 `setup()` 补建或更新检查点表，可重复执行，保留业务表和管理员密码。这不是用户资料字段迁移命令。

### admin密码恢复

停服务、核对目标库后，在 `backend/` 执行：

```powershell
uv run python -m scripts.manage_users reset-admin
```

命令修改内置 admin 密码、清除强制改密标记并撤销其全部登录，不改变会话归属。

如果已有业务表但缺少 admin，不能重复 initialize。仅在确认目标库确实没有该记录、后端保持停止时，执行：

```sql
INSERT INTO users (
    user_id, username, display_name, password_hash,
    role, status, must_change_password
)
VALUES (
    gen_random_uuid(), 'admin', '管理员', 'RESET_REQUIRED',
    'admin', 'active', true
);
```

`RESET_REQUIRED` 只是占位值，不能登录。**插入后立即运行 reset-admin 设置真实密码，再启动服务。** admin 已存在时只用密码恢复命令，不执行插入。实现见 [manage_users.py](../backend/scripts/manage_users.py)。

## 存储与维护

| 存在哪里 | 内容 | 实现 |
| --- | --- | --- |
| 业务表 | 用户、登录、会话、消息、执行状态、完整审核结果与附件引用 | [身份仓储](../backend/app/infrastructure/identity/postgres_store.py)、[会话仓储](../backend/app/infrastructure/conversation/postgres_store.py) |
| 官方检查点表 | 图的短期消息、摘要、待补参数 | [检查点资源](../backend/app/infrastructure/conversation/checkpoints.py) |
| 附件目录 | `<DOCUMENTS_DIR>/<agent_id>/<session_id>/<file_id>/source.docx` 和 `content.md` | [文件存储](../backend/app/infrastructure/documents/local_file_store.py) |
| 头像目录 | `<AVATARS_DIR>/<user_id>/<uuid>.png`，通过受保护接口读取 | [头像存储](../backend/app/infrastructure/identity/avatar_store.py) |
| 进程内存 | 活动任务、通知、SSE 临时文本与锁 | [活动资源](../backend/app/infrastructure/conversation/active_runs.py) |

- **运行**：同库只允许一个应用进程；重启把未完成任务标记中断，不自动重做。历史与检查点持久化不表示任务可恢复。
- **事务**：身份与会话仓储共享 asyncpg 池，通过 [Database/BaseDatabase](../backend/app/infrastructure/database.py) 使用同一事务完成授权与写入。模型调用期间不持有业务事务。
- **删除**：会话接口先确认业务记录已删，再清理官方 thread 检查点、附件和凭据。清理未完保留凭据供重试；提交结果未知时保留文件待核实。只返回空 204 才算全部完成，不会清理备份或用户下载副本。
- **备份**：停服务后，按同一备份点保存数据库、整个附件根目录（含 `.staging`、`.deletions`）和头像目录。恢复先在隔离环境演练，覆盖现有数据另行确认。

失败语义见[错误码](errors.md)，数据操作遵守[风险管理](ai-coding/risk-management.md)。

## 测试与维护

数据库测试须在运行测试的终端显式设置 `TEST_DATABASE_URL`，库名必须为 `agent_platform_test`。未设置时相关测试失败，不会跳过或回退应用库。

测试为每项用例创建 `history_test_<uuid>` schema，以当前初始化流程准备表和测试身份，结束只清理本次 schema；文件用临时目录，不操作真实用户文件。完成上述建库后，在配置好测试连接串的终端、`backend/` 目录运行 `uv run pytest`。

结构变化须同步 SQL、实现、测试和本文。命令、已知检查缺口与验收边界见[质量门禁](ai-coding/quality-gates.md)。

## 官方短期记忆表

锁定 `langgraph-checkpoint-postgres==3.2.0`、`langgraph-checkpoint==4.3.0`、Psycopg 3.2.12 / pool 3.2.7，见 [uv.lock](../backend/uv.lock)。

官方 `AsyncPostgresSaver.setup()` 在相同 schema 维护以下表。字段和索引以安装包 `BasePostgresSaver.MIGRATIONS` 为准，项目不复制 DDL：

| 表 | 用途 |
| --- | --- |
| `checkpoint_migrations` | 官方结构版本 |
| `checkpoints` | 图检查点元数据和状态版本 |
| `checkpoint_blobs` | 状态通道值 |
| `checkpoint_writes` | 节点待写记录 |

官方 saver 使用独立 Psycopg 池，与业务池同库同 schema。多个助手共享 saver，thread_id 由可信 Agent ID 与规范会话 UUID 组成，各图状态和策略独立。

检查点先持久化，业务事务再同时提交助手消息、完整子结果、成功状态及 `memory_checkpoint_id`。失败、取消、中断或容量拒绝不推进指针，下轮从已成功位置继续。检查点不替代完整历史和附件；删除使用官方 `adelete_thread`，不手写删表 SQL。

## 表结构

以下是按需查阅的字段字典。UUID 由应用生成；`timestamptz` 表示带时区的时间，`now()` 为数据库当前时间。外键不级联删除，业务历史不自动过期。

### users：用户账号

保存用户资料和密码哈希。仅内置 `admin` 为管理员且必须保持启用，其他账号角色均为普通用户。

| 字段 | 类型 | 可空 | 含义与约束 |
| --- | --- | --- | --- |
| `user_id` | uuid | 否 | 用户标识，主键 |
| `username` | text | 否 | 唯一用户名；3–32 位小写字母、数字或下划线，须以字母开头 |
| `display_name` | text | 否 | 展示名称，1–50 字符 |
| `password_hash` | text | 否 | 非空的 Argon2 密码哈希，不保存明文密码 |
| `role` | text | 否 | 角色：`admin`（管理员）或 `user`（普通用户） |
| `status` | text | 否 | 账号状态：`active`（启用）或 `disabled`（停用） |
| `must_change_password` | boolean | 否 | 是否须先修改临时密码；公开注册为 false，管理员创建或重置普通用户密码时为 true |
| `avatar_path` | text | 是 | 服务端生成的头像相对路径；非空时不能是空白字符串，不在 API 中返回 |
| `email` | text | 是 | 联系邮箱，最多 254 字符；仅资料用途，不作为登录凭据，不要求唯一 |
| `gender` | text | 是 | `male`、`female`、`other`、`undisclosed`；空值表示未填写 |
| `birthday` | date | 是 | 生日；应用校验真实日期且不晚于 UTC+08:00 的当天，不存年龄 |
| `phone_number` | text | 是 | 联系手机号，最多 32 字符；允许国家区号，不要求唯一 |
| `address` | text | 是 | 联系地址，最多 500 字符 |
| `bio` | text | 是 | 个性签名，最多 200 字符 |
| `created_at` | timestamptz | 否 | 创建时间，默认 `now()` |
| `updated_at` | timestamptz | 否 | 最近更新时间，默认 `now()`，后续由应用更新 |

### auth_sessions：登录会话

保存登录有效期和撤销状态，用于验证 Cookie 登录；与下面的业务聊天会话分别存储。

| 字段 | 类型 | 可空 | 含义与约束 |
| --- | --- | --- | --- |
| `auth_session_id` | uuid | 否 | 登录会话标识，主键 |
| `user_id` | uuid | 否 | 登录用户，外键指向 `users.user_id` |
| `token_hash` | bytea | 否 | 登录 token 的 SHA-256 摘要，唯一且固定 32 字节；Cookie 中的原始 token 不入库 |
| `csrf_token` | text | 否 | 防止跨站请求伪造的校验 token，非空 |
| `created_at` | timestamptz | 否 | 登录创建时间，默认 `now()` |
| `expires_at` | timestamptz | 否 | 到期时间，必须晚于创建时间 |
| `revoked_at` | timestamptz | 是 | 撤销时间；为空表示未主动撤销，仍须检查到期时间和用户状态；非空时不得早于创建时间 |

### agents：智能体元数据

保存目录展示信息，预置 `conversation_assistant`（会话助手）和 `institution_review`（制度审核）。执行能力由代码注册表决定，增加数据库记录不会自动增加执行能力。

| 字段 | 类型 | 可空 | 含义与约束 |
| --- | --- | --- | --- |
| `agent_id` | text | 否 | 稳定的智能体代码标识，主键 |
| `name` | text | 否 | 展示名称 |
| `description` | text | 否 | 智能体说明 |
| `created_at` | timestamptz | 否 | 创建时间，默认 `now()` |
| `updated_at` | timestamptz | 否 | 元数据更新时间，默认 `now()` |

### chat_sessions：业务会话

保存聊天会话的归属、标题和已成功提交的短期记忆位置；待补齐参数归 Agent 检查点状态。拥有者创建后不变，管理员也不能访问他人会话。

| 字段 | 类型 | 可空 | 含义与约束 |
| --- | --- | --- | --- |
| `session_id` | uuid | 否 | 业务会话标识，主键 |
| `user_id` | uuid | 否 | 会话拥有者，外键指向 `users.user_id` |
| `agent_id` | text | 否 | 入口智能体，外键指向 `agents.agent_id` |
| `title` | text | 否 | 会话标题，首次用户提交时生成 |
| `last_sequence` | bigint | 否 | 会话内已保存消息的最高序号，默认 0，不能为负数 |
| `memory_checkpoint_id` | text | 是 | 最后业务提交成功的官方 checkpoint_id；空值表示尚无成功轮次，非空值不能为空串 |
| `created_at` | timestamptz | 否 | 创建时间，默认 `now()` |
| `updated_at` | timestamptz | 否 | 最近提交时间，默认 `now()`，用于会话列表排序 |

### runs：提交与执行记录

一条记录对应一次消息提交，保存排队、执行和终态结果。`(session_id, client_message_id)` 唯一，用于重复请求识别；每会话最多一个 queued 或 running 任务。

| 字段 | 类型 | 可空 | 含义与约束 |
| --- | --- | --- | --- |
| `run_id` | uuid | 否 | 执行标识，主键 |
| `session_id` | uuid | 否 | 所属业务会话，外键指向 `chat_sessions.session_id` |
| `client_message_id` | varchar(128) | 否 | 客户端生成的请求标识，重试同一请求时保持不变 |
| `status` | text | 否 | 执行状态：`queued`（排队）、`running`（执行）、`succeeded`（成功）、`failed`（失败）、`cancelled`（取消） |
| `error_code` | text | 是 | 失败错误码，见[错误码说明](errors.md) |
| `error_message` | text | 是 | 面向用户的安全错误说明 |
| `created_at` | timestamptz | 否 | 提交时间，默认 `now()` |
| `started_at` | timestamptz | 是 | 实际开始执行的时间 |
| `finished_at` | timestamptz | 是 | 终态时间；当且仅当状态为成功、失败或取消时非空 |

### messages：消息正文

保存完整用户消息和助手消息。`(session_id, sequence)` 唯一，保证会话内顺序；`(run_id, role)` 唯一，每轮一条用户消息、至多一条助手终态消息。

| 字段 | 类型 | 可空 | 含义与约束 |
| --- | --- | --- | --- |
| `message_id` | uuid | 否 | 消息标识，主键 |
| `session_id` | uuid | 否 | 所属业务会话，外键指向 `chat_sessions.session_id` |
| `run_id` | uuid | 否 | 所属执行；与 `session_id` 组成复合外键，指向同一会话下的 `runs` 记录 |
| `sequence` | bigint | 否 | 会话内递增序号，必须大于 0 |
| `role` | text | 否 | 消息角色：`user`（用户）或 `assistant`（助手） |
| `content` | text | 否 | 完整正文；失败或取消时也可保存终态说明 |
| `created_at` | timestamptz | 否 | 消息保存时间，默认 `now()` |

### files：附件元数据

仅保存文件信息和相对路径，原件与解析正文保存在本地文件目录。已上传但未发送的文件也归属于会话。

| 字段 | 类型 | 可空 | 含义与约束 |
| --- | --- | --- | --- |
| `file_id` | uuid | 否 | 文件标识，主键 |
| `session_id` | uuid | 否 | 所属业务会话，外键指向 `chat_sessions.session_id` |
| `original_name` | text | 否 | 展示用原文件名，不用于拼接物理路径 |
| `source_path` | text | 否 | 原始 DOCX 相对附件根目录的路径，唯一且非空 |
| `content_path` | text | 否 | 解析 Markdown 相对附件根目录的路径，唯一且非空 |
| `size_bytes` | bigint | 否 | 原件字节数，必须大于 0 |
| `content_chars` | integer | 否 | 解析正文字数，不能为负数 |
| `created_at` | timestamptz | 否 | 文件保存时间，默认 `now()` |

### message_files：消息附件引用

把消息与附件关联，并保留引用顺序。`(message_id, file_id)` 为联合主键，`(message_id, position)` 唯一；复合外键保证消息和附件属于同一会话。

| 字段 | 类型 | 可空 | 含义与约束 |
| --- | --- | --- | --- |
| `session_id` | uuid | 否 | 消息和附件共同所属的业务会话，参与两组复合外键 |
| `message_id` | uuid | 否 | 消息标识；与 `session_id` 共同引用 `messages` |
| `file_id` | uuid | 否 | 文件标识；与 `session_id` 共同引用 `files` |
| `position` | integer | 否 | 附件在该消息中的排列位置，从 0 开始 |

### agent_calls：成功子调用结果

保存助手调用其他 Agent 后的完整成功结果。当前用于制度审核子调用；失败由父运行记录表示。

| 字段 | 类型 | 可空 | 含义与约束 |
| --- | --- | --- | --- |
| `call_id` | uuid | 否 | 子调用结果记录标识，主键 |
| `message_id` | uuid | 否 | 展示该结果的消息，唯一，外键指向 `messages.message_id` |
| `agent_id` | text | 否 | 被调用智能体，外键指向 `agents.agent_id` |
| `agent_name` | text | 否 | 调用时的智能体名称快照 |
| `invocation_id` | text | 否 | 运行时返回的调用标识，用于关联此次执行 |
| `output_type` | text | 否 | 输出格式：`markdown`、`text` 或 `json` |
| `output` | text | 否 | 完整输出内容 |

### chat_schema_version：初始化结构版本

记录初始化结构版本；应用启动不读取或限制版本号，也不据此自动迁移。

| 字段 | 类型 | 可空 | 含义与约束 |
| --- | --- | --- | --- |
| `singleton` | boolean | 否 | 主键且只能为 true，保证最多一条记录 |
| `version` | integer | 否 | 初始化版本号，当前约束为 4，初始化写入 4 |
