# 项目架构目录

- 更新日期：2026-11-02。
- 本文件集中维护项目目录；[AGENTS.md](../../AGENTS.md)是阅读入口，新增或迁移模块前先阅读本文和[架构规则](architecture-rules.md)。
- 当前目录按源码核对，包含账号、会话归属和统一数据库基类；仓库仅保留当前结构初始化与管理员密码恢复。

## 当前目录

以下为主要源码、部署资产与治理文档的目录摘要，省略缓存、依赖和任务过程材料。

```text
Agent/
├── AGENTS.md                             # 协作规则与按场景阅读入口
├── README.md                             # 当前能力、限制和启动入口
├── backend/
│   ├── app/
│   │   ├── api/                          # FastAPI会话、审核、导出、目录、流程、健康接口
│   │   ├── core/                         # 配置、错误响应、日志与中立观测接口
│   │   ├── services/                     # 应用用例，模块按 *_service.py 命名
│   │   ├── infrastructure/
│   │   │   ├── database.py               # 统一查询/事务基类、共享连接池与运行权
│   │   │   ├── identity/                # 账号仓储、Argon2计算与有界尝试计数
│   │   │   ├── conversation/             # PostgreSQL历史和进程内活动资源
│   │   │   ├── documents/                # 本地原件、解析正文与删除凭据
│   │   │   ├── llm/                      # 模型客户端创建与适配
│   │   │   ├── ragflow/                  # 外部知识库适配
│   │   │   ├── langfuse/                 # 追踪与Prompt适配
│   │   │   └── pandoc.py                 # 文档转换进程适配
│   │   ├── agents/
│   │   │   ├── conversation_assistant/   # 会话Agent的适配、图、节点、提示与审核工具
│   │   │   └── institution_review/       # 制度审核Agent及Send条款子图
│   │   ├── nodes/
│   │   │   ├── document/                 # 公共DOCX解析与格式转换
│   │   │   └── llm/                      # 公共上下文预算、裁剪与Prompt契约
│   │   ├── runtime/                      # 通用注册、调用上下文与执行
│   │   ├── schemas/                      # 应用中立记录与HTTP契约
│   │   └── main.py                       # 资源与应用服务装配、生命周期
│   ├── database/
│   │   ├── create_databases.sql          # 显式新建应用库与专用测试库
│   │   └── schema_v3.sql                 # 当前结构，由维护脚本在事务内执行
│   ├── scripts/                          # 显式运维和实验入口
│   ├── tests/                            # pytest、受控模型与真实隔离数据库回归
│   ├── documents/                        # 运行时附件根，不纳入Git
│   └── README.md                         # 后端配置、启动与接口说明
├── frontend/
│   ├── src/
│   │   ├── api/                          # HTTP与SSE客户端
│   │   ├── features/
│   │   │   ├── auth/                     # 认证状态、账号表单和用户管理
│   │   │   ├── conversation-assistant/   # 会话交互、快照、草稿、文件与流式状态
│   │   │   └── institution-review/       # 审核上传、报告与Word下载
│   │   ├── components/                   # 实际共享的品牌与工作台组件
│   │   ├── views/                        # 路由页组合
│   │   ├── router/                       # Vue Router
│   │   ├── App.vue                       # 公共外壳与会话KeepAlive
│   │   ├── main.ts                       # 前端启动
│   │   └── style.css                     # 设计tokens和全局样式
│   └── README.md                         # 前端运行、交互与检查说明
├── docs/
│   ├── database.md                       # 当前数据库与文件持久化说明
│   ├── errors.md                         # 接口错误码
│   └── ai-coding/
│       ├── project-structure.md          # 本文件：项目架构目录
│       ├── architecture-rules.md         # 当前调用关系、职责和依赖边界
│       ├── governance.md                 # 治理优先级与变更机制
│       ├── development-workflow.md       # 开发、验证与交付流程
│       ├── context-management.md         # 长期与任务上下文
│       ├── quality-gates.md              # 检查能力与验收边界
│       └── risk-management.md            # 数据、依赖、配置与外部操作风险
└── .github/workflows/ci.yml               # 后端检查/测试与前端构建
```

当前使用 PostgreSQL，账号、登录与会话拥有者保存在数据库，附件正文存本地文件；活动执行/SSE临时文本仍在单进程内存。应用启动不读取或限制数据库结构版本号。同库只允许一个应用实例。没有引入ORM、Redis、消息队列或图持久检查点。新环境显式初始化当前结构，已有库不重复初始化；旧版升级入口已移除。

## 账号与数据库模块职责

以下模块已实现，均位于现有一级模块内。

| 位置 | 职责与实际调用方 |
| --- | --- |
| `backend/app/infrastructure/database.py` | BaseDatabase封装查询、执行与绑定同一连接的事务；Database拥有共享池、运行权和生命周期。只有该模块直接使用asyncpg，仓储继承基类，维护脚本和Python数据库测试引用基类 |
| `backend/app/infrastructure/conversation/postgres_store.py` | 会话仓储继承BaseDatabase，增加可信拥有者过滤；业务SQL、DTO映射和所有权判断保留在仓储 |
| `backend/app/infrastructure/identity/postgres_store.py` | 身份仓储继承BaseDatabase，维护users/auth_sessions、注册与撤销事务；账号服务和同事务授权回调使用 |
| `backend/app/infrastructure/identity/passwords.py` | 复用密码库与有界线程计算；账号服务和显式管理脚本使用，不自行实现密码算法 |
| `backend/app/infrastructure/identity/auth_limits.py` | 有界登录失败与注册尝试计数；AuthService使用 |
| `backend/app/services/auth_service.py` | 公开注册、登录、身份查询、退出、改密及尝试策略；认证API使用 |
| `backend/app/services/user_service.py` | 本人资料、管理员创建/启停/重置普通用户；用户API使用 |
| `backend/app/api/auth.py`、`users.py` | HTTP、Cookie、来源/CSRF/上下文与身份依赖；业务路由复用，业务规则不进入Agent |
| `backend/app/schemas/identity.py` | 中立账号/身份记录与公开请求响应；内部密码哈希不进入公开View |
| `backend/database/schema_v3.sql` | 新环境当前结构初始化资产；不在应用启动时执行 |
| `backend/scripts/manage_users.py` | 当前结构初始化与admin密码恢复；全部Python数据库读写通过BaseDatabase，密码隐藏输入 |
| `frontend/src/features/auth/` | 注册/登录/资料/改密/用户管理表单，以及认证代次、状态清理和跨标签页重新核验 |
| `frontend/src/api/auth.ts`、`users.ts` | 注册、认证、个人与管理员HTTP契约，复用统一客户端 |
| `frontend/src/views/`、`router/`、`App.vue` | 新增页面组合与守卫，身份变化时整体销毁私有KeepAlive缓存 |

注册只创建启用的普通用户，不签发登录、不替换原Cookie；管理员创建/重置的临时密码仍要求改密。chat_sessions.user_id是不可变拥有者，子对象经会话继承；admin角色不绕过他人正文权限。原会话和稳定附件路径保留。

两个仓储必须共享同一Database资源，跨仓储授权和写入使用同一BaseDatabase事务对象；不能按子类各建池，不能在事务中另取连接，也不能保留driver旁路。用户/会话策略留在仓储与服务，Agent/runtime不依赖账号或存储。详细约束见[架构规则](architecture-rules.md)，持久化见[数据库说明](../database.md)，对外失败语义见[错误码](../errors.md)。

## 维护方式

- 项目目录在本文集中维护，README和协作入口只链接，不重复维护完整目录树。
- 新增或迁移模块时，同步职责、输入输出、依赖和实际调用方；实施后才将对应条目从拟变更移入当前目录。
- 正式架构与运行文档应可独立阅读，只引用源码、部署资产及治理文档；任务设计与执行记录不作为长期规则的依赖入口。
- 更新本文不等于授权源码重构、依赖安装、迁移或安全配置变更，具体操作仍按[治理流程](governance.md)与[风险规则](risk-management.md)执行。
