# AgentPlatform

AgentPlatform 是一个智能体应用平台，目前提供**会话助手**和 **DOCX 制度审核**，使用 Vue 前端、FastAPI 后端和 PostgreSQL 数据库。

## 能做什么

| 功能 | 使用方式 |
| --- | --- |
| 会话助手 | 聊天、粘贴正文或上传 DOCX；需要审核且材料齐全时，助手调用制度审核 |
| 制度审核 | 上传草稿，选择“与标准文档对比”或“查知识库”，生成带条款定位的 Markdown 报告 |
| 历史与账号 | 注册、登录、管理个人资料，保存或永久删除自己的会话；管理员可管理账号 |
| Word 下载 | 将 Markdown 报告导出为 DOCX，可单独重试下载 |
| 调用追踪（可选） | 接入 Langfuse 查看调用链、Token 用量和 Prompt 版本；默认不上传正文 |

标准文档审核只需聊天模型；知识库审核还需 RAGFlow。当前只支持单工作进程，同库第二实例会拒绝启动。重启后未完成的任务标记为中断，不自动重做。长期记忆、Redis 和 MCP 尚未接入。

## 本地启动

需要 Python 3.12 / 3.13、PostgreSQL 18、[uv](https://docs.astral.sh/uv/)、Node.js 20.19+ 或 22.12+、pnpm。

**1. 准备后端。** 在项目根目录打开终端：

```powershell
cd backend
Copy-Item .env.example .env  # 仅首次执行，已有配置时跳过
uv sync --locked
```

填写 `backend/.env` 中的 `DATABASE_URL`、`LLM_MODEL`、`LLM_API_KEY`；使用兼容模型服务时填写 `LLM_BASE_URL`。知识库审核另填 `RAGFLOW_*`。

**2. 初始化数据库。** 按[数据库初始化说明](docs/database.md#初始化)创建数据库并执行初始化；仅新环境执行。应用启动不会自动建表或迁移。

**3. 启动后端。** 仍在 `backend/`：

```powershell
uv run uvicorn app.main:create_app --factory --reload --loop app.infrastructure.conversation.checkpoints:event_loop_factory
```

保留 `--loop` 参数：它在 Windows 下选择 PostgreSQL 异步驱动需要的事件循环，其他系统也可使用。

**4. 启动前端。** 在项目根目录另开终端：

```powershell
cd frontend
Copy-Item .env.example .env.local  # 仅首次执行，已有配置时跳过
pnpm install --frozen-lockfile
pnpm dev
```

打开终端显示的前端地址，默认是 `http://localhost:5173`。开发服务器将 `/api` 转发到 `http://127.0.0.1:8000`。首次使用可注册账号，再登录。

## 项目怎样工作

前端页面 → HTTP 接口 → 应用服务 → AgentRuntime → 对应 Agent 的 LangGraph 流程。

会话助手可以通过同一运行时调用制度审核。PostgreSQL 保存账号、完整历史和短期记忆，本地目录保存附件与头像；Word 导出由 Pandoc 完成。

主要技术：Python / FastAPI、LangChain / LangGraph、Vue 3 / TypeScript / Vite、PostgreSQL、OpenAI 兼容模型、RAGFlow。

## 按需要阅读

| 想了解什么 | 看哪里 |
| --- | --- |
| 后端配置、接口、审核流程、Word 导出、Langfuse | [后端说明](backend/README.md) |
| 页面入口、聊天和文件操作、前端开发 | [前端说明](frontend/README.md) |
| 建库、管理员密码恢复、备份、表字段 | [数据库说明](docs/database.md) |
| 出错原因和恢复方式 | [错误码](docs/errors.md) |
| 代码放在哪里 | [项目架构目录](docs/ai-coding/project-structure.md) |
| 修改项目时遵守什么 | [AGENTS.md](AGENTS.md) |
| 运行哪些检查、哪些仍需人工验收 | [质量门禁](docs/ai-coding/quality-gates.md) |

后端启动后可在 `http://127.0.0.1:8000/docs` 查看接口。健康检查为 `/health/live` 和 `/health/ready`；后者只检查模型配置与运行时，不验证外部网络或账户额度。
