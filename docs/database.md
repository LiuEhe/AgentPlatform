# 数据库设计与初始化

当前使用 PostgreSQL 18、asyncpg 0.32.0。可执行结构以 [schema_v3.sql](../backend/database/schema_v3.sql) 为准。应用启动不读取或限制数据库结构版本号，仍确认内置admin，不隐式建库、建表或迁移。版本表保留当前初始化结构的记录。

## 文件职责

| 位置 | 职责 |
| --- | --- |
| [create_databases.sql](../backend/database/create_databases.sql) | 仅供新环境显式建应用库及测试库，已有数据库无需执行 |
| [schema_v3.sql](../backend/database/schema_v3.sql) | 当前DDL，由管理脚本与真实admin初始化在同一事务中执行 |
| [postgres_store.py](../backend/app/infrastructure/conversation/postgres_store.py) | 会话SQL、拥有者校验和DTO映射，继承BaseDatabase；不读写附件正文 |
| [local_file_store.py](../backend/app/infrastructure/documents/local_file_store.py) | 本地原件、解析正文、暂存、发布、读取和精确清理 |
| [active_runs.py](../backend/app/infrastructure/conversation/active_runs.py) | 当前进程活动任务、流式临时文本、锁和额度；不持有第二份持久历史 |

SQL 是 backend/database 下的部署资产，不属于 Python 运行时包。发布时单独携带，不打入 wheel。未引入迁移框架；密码计算使用锁定的pwdlib[argon2] 0.3.1。

## 连接与配置

本地地址 `127.0.0.1:5432`，用户 `postgres`。应用库 `agent_platform`；专用测试库 `agent_platform_test`。真实密码仅在被 Git 忽略的 backend/.env 中，本文与示例不记录密码。

| 配置项 | 用途 |
| --- | --- |
| DATABASE_URL | 应用完整连接串 |
| TEST_DATABASE_URL | 测试终端显式提供；只允许 agent_platform_test，不回退应用库 |
| DATABASE_POOL_MIN_SIZE / DATABASE_POOL_MAX_SIZE | 普通连接池大小，默认 1 / 5 |
| DATABASE_TIMEOUT_SECONDS | 建连、获取连接和命令超时，默认 5 秒 |
| DOCUMENTS_DIR | 附件根目录；未配置为 backend/documents，相对配置固定按 backend 解析 |

.env 注释列出主机、端口、用户和库用途；密码仅在连接串中，不另复制一份密码注释。保留字符须 URL 编码。

## 初始化

新环境先在postgres管理库执行 `backend/database/create_databases.sql`。在backend工作目录配置明确的DATABASE_URL与DOCUMENTS_DIR，再执行：

```powershell
uv run python -m scripts.manage_users initialize
```

命令隐藏输入并确认6–20字符的admin密码，在同一事务内执行schema_v3与真实admin插入。没有默认密码；重复初始化拒绝覆盖。不要单独执行v3 DDL后启动没有admin的服务。已有环境不要重复初始化；仓库只保留当前结构初始化和管理员密码恢复，不再提供旧版升级或续做入口。

### 备份与恢复

数据库与整个附件根（包括`.deletions`和`.staging`）必须作为同一恢复点保存。先停服务，核对目标库和DOCUMENTS_DIR，使用PostgreSQL18客户端备份；凭据使用受控配置或客户端密码提示，避免出现在命令行。

```powershell
pg_dump -h 127.0.0.1 -p 5432 -U postgres -d agent_platform -W -Fc -f <备份目录>/database.dump
tar -czf <备份目录>/documents.tar.gz -C <实际附件根> .
pg_restore --list <备份目录>/database.dump
tar -tzf <备份目录>/documents.tar.gz
```

恢复前在隔离库与临时目录演练；恢复时保持数据库、附件及删除凭据属于同一备份点。已有用户或私有会话的环境不能直接降级到无认证旧版本，优先前向修复。覆盖现有数据或恢复旧备份需另行确认数据损失，不运行初始化命令覆盖已有库。

### admin密码恢复

停服务、核对目标并取得运行权后执行 `uv run python -m scripts.manage_users reset-admin`。隐藏输入新密码，只修改内置admin密码并撤销其全部登录，不重新认领会话、不处理其他用户。此入口不暴露为HTTP API。

## 统一数据库资源与账号表

`infrastructure/database.py` 内部封装asyncpg 0.32.0，Database拥有唯一共享连接池与advisory运行权；BaseDatabase提供fetch/fetchrow/fetchval/execute及绑定同一连接的transaction。两个仓储继承基类，维护脚本和Python测试通过maintenance入口；驱动连接/池不对外暴露。写事务read_committed，用户锁之后以新语句复核登录，再操作会话；只读事务repeatable_read。

`users`：user_id UUID主键，username唯一且规范为字母开头3–32位小写字母/数字/下划线；display_name 1–50字符；password_hash非空Argon2编码；role为admin/user、status为active/disabled；must_change_password布尔值，created_at/updated_at为timestamptz。约束确保只有username=admin可为admin且不能停用，其他账号固定user。users_list(created_at DESC,user_id DESC)支持分页。

`auth_sessions`：auth_session_id UUID主键、user_id外键、token_hash唯一32字节SHA256摘要、csrf_token非空、created_at/expires_at及可空revoked_at。expires_at>created_at，revoked_at不得早于created_at，建立用户与过期时间索引。Cookie明文不入库；密码/重置/停用撤销全部相关登录，普通退出只撤销绑定登录。登录时小批清理过期记录，不清理业务历史。

公开注册创建active普通用户且must_change_password=false，不创建auth_sessions；管理员创建/重置设true。存量会话已归属真实admin。admin角色不绕过会话拥有者判断。

## 表结构

业务 UUID 由应用生成；时间均为非空 timestamptz，created_at/updated_at 默认 now()，下列可空时间例外。外键均 NO ACTION，无级联删除或自动过期；历史通过显式 DELETE 用例永久删除，不修改结构版本。

### agents：智能体元数据

| 字段 | 类型及约束 | 含义 |
| --- | --- | --- |
| agent_id | text PK | 稳定代码标识 |
| name / description | text NOT NULL | 展示名称及说明 |
| created_at / updated_at | timestamptz NOT NULL | 创建和更新记录 |

SQL 显式初始化 conversation_assistant（会话助手）与 institution_review（制度审核）。不存模型、密钥、Prompt 或可执行代码，不在应用启动时覆盖元数据。GET /api/v1/agents 与前端目录读取名称和描述；执行能力仍由现有代码注册表决定，数据库添加行不等于可执行 Agent。

### chat_sessions：会话

| 字段 | 类型及约束 | 含义 |
| --- | --- | --- |
| session_id | uuid PK | 会话标识 |
| user_id | uuid NOT NULL FK users | 不可变拥有者；所有子对象经会话继承归属 |
| agent_id | text NOT NULL FK agents | 入口 Agent，当前会话入口为 conversation_assistant |
| title | text NOT NULL | 首次用户提交生成标题 |
| last_sequence | bigint NOT NULL DEFAULT 0 CHECK >= 0 | 全会话最高消息序号 |
| continuation | jsonb NULL | 版本化待补参数据 {version:1,data:...} |
| created_at / updated_at | timestamptz NOT NULL | 创建与最近提交时间 |

索引 chat_sessions_list(user_id,agent_id,updated_at DESC,session_id DESC)，支持键集分页。不存消息数组或模型上下文缓存。

### runs：提交和后台执行

| 字段 | 类型及约束 | 含义 |
| --- | --- | --- |
| run_id | uuid PK | 执行标识 |
| session_id | uuid NOT NULL FK chat_sessions | 所属会话 |
| client_message_id | varchar(128) NOT NULL | 请求幂等标识 |
| status | text NOT NULL CHECK 枚举 | queued/running/succeeded/failed/cancelled |
| error_code / error_message | text NULL | 安全错误说明 |
| created_at | timestamptz NOT NULL | 提交时间 |
| started_at / finished_at | timestamptz NULL | 开始/终态时间 |

UNIQUE(session_id,run_id)、UNIQUE(session_id,client_message_id)。部分唯一索引 session_one_active_run(session_id) 限定 queued/running 时每会话只有一个活动运行。CHECK 保证终态当且仅当 finished_at 非空。请求正文和有序文件引用存在用户消息，不重复保存。

### messages：消息

| 字段 | 类型及约束 | 含义 |
| --- | --- | --- |
| message_id | uuid PK | 消息标识 |
| session_id | uuid NOT NULL FK chat_sessions | 所属会话 |
| run_id | uuid NOT NULL | 所属执行 |
| sequence | bigint NOT NULL CHECK > 0 | 会话内递增序号 |
| role | text NOT NULL CHECK user/assistant | 消息角色 |
| content | text NOT NULL | 完整消息正文 |
| created_at | timestamptz NOT NULL | 保存时间 |

UNIQUE(session_id,message_id)、UNIQUE(session_id,sequence)、UNIQUE(run_id,role)。复合 FK(session_id,run_id) 引用 runs(session_id,run_id)，禁止关联其他会话的运行。一轮一条用户消息及至多一条助手终态消息，失败/取消同样保存说明。

### files：文件元数据

| 字段 | 类型及约束 | 含义 |
| --- | --- | --- |
| file_id | uuid PK | 文件标识 |
| session_id | uuid NOT NULL FK chat_sessions | 所属会话 |
| original_name | text NOT NULL | 展示用原文件名，不参与路径拼接 |
| source_path | text NOT NULL UNIQUE CHECK 非空 | 原件相对路径 |
| content_path | text NOT NULL UNIQUE CHECK 非空 | Markdown 相对路径 |
| size_bytes | bigint NOT NULL CHECK > 0 | 原件字节数 |
| content_chars | integer NOT NULL CHECK >= 0 | 已解析正文字数 |
| created_at | timestamptz NOT NULL | 保存时间 |

UNIQUE(session_id,file_id)，索引 files_list(session_id,created_at,file_id)。没有 bytea、markdown 或正文内容列；容量通过元数据求和。已上传未发送的文件也归该会话。HTTP 只返回 file_id/original_name/size_bytes/content_chars/created_at，不返回内部路径。

### message_files：消息引用

session_id、message_id、file_id 均为 uuid NOT NULL；position 为 integer NOT NULL CHECK >= 0。PK(message_id,file_id)，UNIQUE(message_id,position)，索引 file_references(file_id)。复合外键 (session_id,message_id) 和 (session_id,file_id) 分别引用 messages 和 files，防止跨会话引用，position 保留附件顺序。

### agent_calls：成功子调用结果

call_id uuid PK；message_id uuid NOT NULL UNIQUE FK messages；agent_id text NOT NULL FK agents；agent_name text NOT NULL 为名称快照；invocation_id text NOT NULL；output_type text NOT NULL CHECK markdown/text/json；output text NOT NULL 保存完整结果。当前只保存已有成功子审核结果，失败由父运行错误表示，不新增通用工具日志或独立审核报告历史。

### chat_schema_version：结构版本

singleton boolean PRIMARY KEY CHECK(singleton)，version integer NOT NULL CHECK(version=3)。只允许 true 一个键，初始化写 (true,3)。这是基础设施版本表，不是业务实体。

## 文件目录、操作与备份

```text
backend/documents/
  .deletions/<session_id>.json
  .staging/<upload_id>/
  <agent_id>/<session_id>/<file_id>/
    source.docx
    content.md
```

原件和 UTF-8 解析正文各保存一份。上传只解析一次，后续模型输入从 content.md 读取；Agent 获得中立 TurnDocument，不能直接读文件或数据库。所有路径段由代码 Agent 标识及服务端 UUID 生成，数据库保存相对根目录的 POSIX 路径，变更根目录后保持相对结构即可；用户原文件名不用于物理目录。

使用已安装 Python 3.12.13 标准库 pathlib.Path.resolve/lstat、os.rename、shutil.rmtree；文件在同一根内暂存再通过目录 rename 发布，已有目标拒绝覆盖。路径边界检查拒绝绝对路径、盘符/UNC、反斜杠、上级引用、symlink/junction/reparse point。清理只针对本次生成目录，先核实解析目标仍在根内。缺文件、无效 UTF-8 或正文长度与元数据不一致返回 FILE_UNAVAILABLE，不以空材料继续调用。未给 documents 挂静态路由或新增下载入口，目录被 Git 忽略。

上传顺序为校验解析 → 暂存 → 发布 → 元数据事务。取消/关闭等待不可中止的解析及文件线程完成，再清理和释放额度。同会话上传和消息提交互斥，数据库再次校验活动运行及文件额度。

文件系统与 PostgreSQL 不组成分布式事务。数据库保存未确认时按 file_id 核实，并取得与原写入相同的会话行锁，等待原事务结束：已引用保留；明确无记录只清理本次发布目录；核实失败也保留并仅记录文件 ID。进程崩溃可能留下待核对孤立文件，不建立自动扫描清理平台。恢复和备份必须同时包含数据库与文件目录，只有数据库备份无法恢复正文。文件外置减少数据库体积，不会减少原件和正文占用的总磁盘空间。

## 事务与运行边界

- 提交事务原子保存 queued 运行、用户消息、有序文件引用及序号；先比较幂等内容，再检查忙碌和容量。
- 终态事务原子保存助手消息、子结果、续接和状态；已提交终态不被取消覆盖，提交成功后才发送 SSE done。
- 模型、解析和 SSE 不持有长事务。普通池默认 1–5，另有专用连接持 advisory lock，单库只允许一个应用进程；锁丢失拒绝新写入并要求重启。
- 启动将遗留 queued/running 收为 CONVERSATION_INTERRUPTED，不重做模型。提交 ACK 丢失后的重复请求若无本地任务，收为中断失败并返回原 run_id。
- 每会话最多 100 消息、8 文件，正文合计 100000 字符，消息及子结果合计 1000000 字符；提交时为容量失败的终态提示预留 10 字符。模型输入预算仍为 24000 序列化字符，历史子结果片段最多 4000 字符。
- HTTP 前缀为 /api/v1/sessions，字段 session_id/message_id/run_id/file_id，文件引用 file_ids；旧 conversations 路由没有别名。列表游标版本3，绑定user_id与agent_id，消息按 sequence 前后分页，last_sequence 不能代表客户端已收位置。

## 显式永久删除

`DELETE /api/v1/sessions/{session_id}` 由应用服务取得同会话操作锁，拒绝上传、活动运行及本地执行收尾中的目标。仓储通过会话行锁在单个事务依次删除 message_files/agent_calls、messages、files、runs、chat_sessions；不更改 agents 或外键。提交响应丢失时通过新的 read-committed 锁定查询等待原事务结束，确认无会话后才清理附件。

`.deletions` 凭据在数据库删除前以标准库原子替换落盘，包含version=2/user_id/agent_id/session_id。提交后清理对应会话目录，再移除凭据，全部完成才返回204。部分清理失败保留凭据并返回专用503；未知提交保留文件和凭据。启动只恢复凭据所指目标：数据库无会话则完成清理，仍有会话则保留材料并移除凭据。备份须同时包含数据库、附件与凭据；该机制不清理已有备份、Langfuse、模型供应商记录或用户下载副本。

## 私有会话边界

登录身份来自服务端Cookie会话，chat_sessions.user_id为不可变拥有者。子对象经会话继承归属；管理员不能绕过拥有者判断，文件物理路径不变。不提供共享、成员ACL、长期记忆或图断点恢复。模块职责见[项目架构目录](ai-coding/project-structure.md)，依赖约束见[架构规则](ai-coding/architecture-rules.md)。

## 测试与维护

测试显式使用 TEST_DATABASE_URL，仅允许 agent_platform_test；每项测试创建本次随机 history_test_<uuid> schema，执行schema_v3.sql并创建真实测试身份，只清理该 schema。文件测试使用 tmp_path，不读实际用户文件。CI 同样使用 PostgreSQL 18，覆盖真实事务、表约束、重启、所有权丢失、文件提交确认、取消及路径边界；模型和 RAG 使用受控替身，不代表真实模型效果已验收。

SQL、仓储、HTTP、前端、CI 和本文须同步更新；涉及结构、数据或文件清理先按 [治理流程](ai-coding/governance.md) 及 [风险规则](ai-coding/risk-management.md) 明确授权范围。
