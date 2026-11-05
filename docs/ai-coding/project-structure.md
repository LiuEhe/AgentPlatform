# 项目架构目录

更新日期：2026-11-05。本文集中维护当前目录，省略缓存、依赖、运行数据和任务过程材料；其他文档只链接，不重复维护目录树。

## 当前目录

```text
AgentPlatform/
├── AGENTS.md                         # 协作规则与阅读入口
├── README.md                         # 功能、启动与文档导航
├── backend/
│   ├── app/
│   │   ├── api/                      # HTTP、身份依赖与上传接收
│   │   ├── core/                     # 配置、错误、日志、中立观测接口
│   │   ├── services/                 # 应用用例，文件名 *_service.py
│   │   ├── runtime/                  # 通用 Agent 注册与执行
│   │   ├── schemas/                  # 共享记录与接口契约
│   │   ├── agents/
│   │   │   ├── conversation_assistant/ # 会话图、节点、提示与审核调用
│   │   │   └── institution_review/   # 审核图、条款子图、节点与提示
│   │   ├── nodes/
│   │   │   ├── document/             # 公共 DOCX 解析与格式转换
│   │   │   └── llm/                  # 公共预算、摘要与 Prompt 契约
│   │   ├── infrastructure/
│   │   │   ├── database.py           # 连接池、运行权、查询与事务
│   │   │   ├── conversation/         # 历史仓储、官方检查点、活动资源
│   │   │   ├── identity/             # 账号、密码、尝试计数与头像
│   │   │   ├── documents/            # 原件、解析正文与删除凭据
│   │   │   ├── llm/                  # 模型客户端适配
│   │   │   ├── ragflow/              # 知识库适配
│   │   │   ├── langfuse/             # 追踪与 Prompt 适配
│   │   │   └── pandoc.py             # 文档转换进程
│   │   └── main.py                   # 资源装配与生命周期
│   ├── database/
│   │   ├── create_databases.sql      # 创建应用库与专用测试库
│   │   └── schema_v4.sql             # 新环境初始化结构
│   ├── scripts/                      # 初始化、密码恢复、Prompt 与实验
│   ├── tests/                        # pytest、受控模型、隔离数据库
│   ├── documents/                    # 运行时附件，不纳入 Git
│   ├── avatars/                      # 运行时头像，不纳入 Git
│   └── README.md                     # 后端配置、启动与接口
├── frontend/
│   ├── src/
│   │   ├── api/                      # HTTP/SSE 客户端
│   │   ├── features/
│   │   │   ├── auth/                 # 认证、资料、头像与用户管理
│   │   │   ├── conversation-assistant/ # 会话、草稿、附件与流式状态
│   │   │   └── institution-review/    # 审核上传、报告与 Word 下载
│   │   ├── components/               # 品牌与共享工作台组件
│   │   ├── views/                    # 页面组合
│   │   ├── router/                   # 路由与守卫
│   │   ├── App.vue                   # 公共外壳与助手 KeepAlive
│   │   ├── main.ts                   # 启动入口
│   │   └── style.css                 # 全局样式与设计变量
│   └── README.md                     # 页面、开发与交互
├── docs/
│   ├── database.md                   # 数据库操作与字段字典
│   ├── errors.md                     # 错误与恢复方式
│   └── ai-coding/
│       ├── project-structure.md      # 当前目录（本文）
│       ├── architecture-rules.md     # 职责与依赖边界
│       ├── governance.md             # 优先级与变更确认
│       ├── development-workflow.md   # 开发与交付
│       ├── context-management.md     # 长期文档与任务恢复
│       ├── quality-gates.md          # 检查与验收边界
│       └── risk-management.md        # 数据、安全与外部操作
└── .github/workflows/ci.yml           # 后端检查、前端回归子集与构建
```

## 关键实现位置

以下均为当前实现，职责边界以[架构规则](architecture-rules.md)为准。

| 要找什么 | 位置与调用关系 |
| --- | --- |
| 业务数据库 | `infrastructure/database.py` 提供 Database/BaseDatabase，身份与会话仓储共享池和事务；维护脚本及数据库测试也复用基类 |
| 账号与资料 | `api/auth.py、users.py` → `auth_service.py、user_service.py` → `infrastructure/identity/`；共享契约在 `schemas/identity.py` |
| 头像处理 | `identity/avatar_store.py` 接收可信用户 ID、文件名和字节，输出相对路径或图片字节；用户服务协调额度与提交，API 约束请求量 |
| 完整会话历史 | `conversation/postgres_store.py` 保存业务历史与归属；`conversation_service.py` 协调用例，`active_runs.py` 只管进程内活动资源 |
| 短期记忆资源 | `conversation/checkpoints.py` 接收配置/schema，提供官方 saver；应用、初始化脚本和删除用例使用，独立 Psycopg 池仅供官方 API |
| 记忆输入输出 | `schemas/conversation_turn.py` 定义当前轮、材料 reader、成功位置和 thread_id；服务与 Agent 适配器共用 |
| 摘要与图状态 | 公共 `nodes/llm/memory.py` 接收历史、策略和 Prompt，返回摘要及移除 ID；会话 Agent 的 `nodes/memory_summarize.py` 选择历史，`graph/state.py` 定义持久字段和本轮非持久字段 |
| 前端账号 | `features/auth/` 管表单和身份控制；`api/client.ts、auth.ts、users.ts` 管请求；`App.vue/router/` 处理私有页面清理与守卫 |
| 头像裁剪 | `AvatarCropper.vue` 用 dialog、Canvas、Pointer Events 将 File 转成确认 PNG 或取消事件，仅供 `ProfileForm.vue` 调用；`UserAvatar.vue` 读取受保护图片 |
| 数据库维护 | `scripts/manage_users.py` 负责当前结构初始化、检查点建表和 admin 密码恢复，不是旧版数据迁移器 |

表内后端路径相对 `backend/app/`（脚本相对 `backend/`），前端路径相对 `frontend/src/`。

当前已使用 PostgreSQL、官方会话 checkpointer 和本地文件；没有 ORM、Redis、消息队列或长期 Store。活动执行仍在单进程内，应用启动不按结构版本号迁移，旧版升级入口已移除。备份、初始化与恢复限制见[数据库说明](../database.md)。

## 维护方式

新增或迁移模块时，说明职责、输入输出、依赖与实际调用方；获准实施后再更新当前目录。正式说明引用源码、部署资产和治理文档，不依赖任务记录。

更新本文不授权源码重构、依赖安装、迁移、删除或安全配置变更，仍按[治理流程](governance.md)和[风险管理](risk-management.md)执行。
