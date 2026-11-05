# 数据库设计与初始化

项目使用 PostgreSQL 18、asyncpg 0.32.0，保存账号、登录会话和业务历史；上传原件与解析正文保存在本地文件目录。业务字段、类型、约束和索引以 [schema_v4.sql](../backend/database/schema_v4.sql) 为准；官方检查点表由其库维护。

## 表结构

以下按数据库表说明全部字段。UUID 由应用生成；`timestamptz` 表示带时区的时间，`now()` 为数据库当前时间。外键不级联删除，业务历史不自动过期。

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

## 官方短期记忆表

使用 `langgraph-checkpoint-postgres==3.2.0`、`langgraph-checkpoint==4.3.0` 和 Psycopg 3.2.12 / pool 3.2.7。官方 `AsyncPostgresSaver.setup()` 在相同 schema 创建并维护以下表，字段、主键与索引直接以安装版本的 `langgraph.checkpoint.postgres.base.BasePostgresSaver.MIGRATIONS` 为准，项目不复制 DDL：

| 官方表 | 用途 |
| --- | --- |
| `checkpoint_migrations` | 官方 schema 迁移版本 |
| `checkpoints` | 图检查点元数据和状态版本 |
| `checkpoint_blobs` | 状态通道值 |
| `checkpoint_writes` | 节点待写入记录 |

资源适配见 [checkpoints.py](../backend/app/infrastructure/conversation/checkpoints.py)，官方能力见 [LangGraph 持久化](https://docs.langchain.com/oss/python/langgraph/persistence)。同一 saver 由多个会话图复用；thread_id 用可信会话记录的 Agent ID 与规范 UUID 组成，Agent 图定义自己的状态和策略。检查点不替代完整消息、附件及报告归档。

官方 saver 使用独立 Psycopg 连接池，业务与身份继续共享 asyncpg 池；两种驱动遵循相同数据库、schema、运行权和关闭顺序。图执行及摘要时不持有业务事务。官方检查点先持久化，业务事务随后同时提交助手消息、完整子结果、运行成功状态与 `memory_checkpoint_id`；失败、取消、中断或容量拒绝不推进指针，下轮只从已提交位置执行。删除通过官方 `adelete_thread`，不手写删表 SQL。

## 连接与配置

本地数据库地址为 `127.0.0.1:5432`，用户为 `postgres`；应用库为 `agent_platform`，测试库为 `agent_platform_test`。连接串放在被 Git 忽略的 `backend/.env` 中，密码中的保留字符须 URL 编码。

| 配置项 | 用途与默认值 |
| --- | --- |
| `DATABASE_URL` | 应用数据库连接串 |
| `TEST_DATABASE_URL` | 测试终端显式提供，仅允许连接 `agent_platform_test` |
| `DATABASE_POOL_MIN_SIZE` / `DATABASE_POOL_MAX_SIZE` | 业务池和检查点池各自的大小，默认 1 / 5（总连接额度需计两池） |
| `DATABASE_TIMEOUT_SECONDS` | 数据库操作超时，默认 5 秒 |
| `DOCUMENTS_DIR` | 附件根目录，默认 `backend/documents`；相对路径按 `backend` 解析 |
| `AVATARS_DIR` | 用户头像根目录，默认 `backend/avatars`；相对路径按 `backend` 解析，与数据库共同备份 |

## 初始化

仅新环境执行：先在 `postgres` 管理库运行 [create_databases.sql](../backend/database/create_databases.sql)，再配置 `backend/.env`，在 `backend/` 目录执行：

```powershell
uv run python -m scripts.manage_users initialize
```

直接执行 `schema_v4.sql` 建表后，会自动插入开发/测试账号 `admin / 123456`，密码以 Argon2id 哈希保存。使用上述管理命令时，隐藏输入并确认 6–20 字符的管理员密码；命令先执行官方 `setup()`，再在同一业务事务中执行 SQL，并将默认管理员密码替换为输入值，不重复插入账号。官方 setup 使用 autocommit，不能与业务事务宣称原子：若业务初始化失败，仅残留官方表时可重试 initialize；出现已有业务表或其他未知表时拒绝初始化。应用启动只检查管理员及官方表是否存在，不调用 setup 或自动迁移。

本次仅支持空环境初始化，不提供 v3 数据迁移或兼容分支；现有测试环境请另建空数据库或在明确确认清理范围后重建，不能在旧表上重复初始化。此代码变更不会自动清空现有库。Windows 启动须使用后端 README 中的 Selector loop 参数，官方异步驱动不支持 Proactor。

### 现有 v4 库补充用户资料列

如果已直接执行 `schema_v4.sql`，但启动报“检查点结构尚未初始化”，先停止后端，再在 `backend/` 运行 `uv run python -m scripts.manage_users setup-checkpoints`。该命令仅调用官方 `setup()` 补建或更新检查点表，可重复执行，保留业务表和管理员密码。

### admin密码恢复

停服务并核对目标库后，在 `backend/` 执行 `uv run python -m scripts.manage_users reset-admin`。命令修改内置管理员密码并撤销其全部登录，不改变会话归属。实现见 [manage_users.py](../backend/scripts/manage_users.py)。

如果数据库已初始化但 `users` 表中缺少 `admin` 记录，`initialize` 会因已有业务表而拒绝重复初始化。仅在确认连接的是目标应用库且没有 `admin` 记录后，保持后端停止，在该数据库执行以下 SQL：

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

`RESET_REQUIRED` 是临时占位值，不是可用于登录的密码哈希。插入后不要启动后端；立即在 `backend/` 运行 `uv run python -m scripts.manage_users reset-admin`，按提示设置真实密码。该命令会写入应用使用的密码哈希并清除 `must_change_password` 标记；完成后再启动服务。若 `admin` 记录已存在，不执行上述插入，直接使用密码恢复命令。

## 存储与维护

| 项目 | 说明 |
| --- | --- |
| 数据库访问 | [IdentityStore](../backend/app/infrastructure/identity/postgres_store.py) 负责用户与登录记录，[PostgresConversationStore](../backend/app/infrastructure/conversation/postgres_store.py) 负责业务会话历史；两者复用同一个连接池，统一由 [Database](../backend/app/infrastructure/database.py) 管理连接 |
| 事务一致性 | 身份校验与会话写入需要一起完成时，使用同一数据库连接和事务，成功时一起提交，失败时一起回滚 |
| 运行方式 | 同库仅允许一个应用进程；重启将未完成任务标为中断，不自动重做 |
| 附件位置 | `<DOCUMENTS_DIR>/<agent_id>/<session_id>/<file_id>/` 下保存 `source.docx` 和 `content.md` |
| 用户头像 | `<AVATARS_DIR>/<user_id>/<uuid>.png`；头像经有权限的接口读取，不开放静态目录；备份和恢复须包含此目录 |
| 文件操作 | 暂存目录为 `.staging`，删除凭据目录为 `.deletions`；数据库提交未知时保留文件待核实 |
| 永久删除 | 通过会话删除接口依次清理业务历史、对应 thread 检查点和附件；检查点或附件清理失败保留凭据可重试，不清理备份或用户下载副本 |
| 备份恢复 | 停服务后共同备份数据库与整个附件根目录（含 `.staging`、`.deletions`），恢复时使用同一备份点；先在隔离环境演练，覆盖已有数据须另行确认 |

会话与附件操作分别见 [postgres_store.py](../backend/app/infrastructure/conversation/postgres_store.py) 和 [local_file_store.py](../backend/app/infrastructure/documents/local_file_store.py)，失败响应见[错误码](errors.md)。

头像文件操作见 [avatar_store.py](../backend/app/infrastructure/identity/avatar_store.py)。

## 测试与维护

数据库测试显式使用 `TEST_DATABASE_URL`，不回退应用库；每项测试创建随机 `history_test_<uuid>` schema，通过当前初始化流程准备结构与身份，只清理本次 schema。文件测试使用临时目录，不操作实际用户文件。

结构变化时同步更新 SQL、相关实现、测试和本文；检查要求见[质量门禁](ai-coding/quality-gates.md)，数据操作遵守[风险规则](ai-coding/risk-management.md)。
