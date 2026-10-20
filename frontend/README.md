# AgentPlatform 前端

基于 Vue 3、TypeScript 和 Vite 的智能体工作空间。首版提供智能体主页，以及连接现有制度审核 API 的工作台。

## 当前功能

- `/`：平台首页，介绍平台并提供进入智能体广场的入口。
- `/agents`：智能体广场，浏览会话助手与制度审核助手。
- `/agents/conversation-assistant`：聊天工作台；无附件可发送，支持多轮对话、可选 DOCX、粘贴正文和现有制度审核结果展示。明确审核需求才调用子智能体，普通聊天和制度问答直接回答。

- `/agents/institution-review`：制度审核工作台，选择知识库审核，或上传草稿与标准两份 DOCX 直接对比，查看 Markdown 报告并下载 Word。切回知识库模式会清空标准文件选择。
- `/agents/institution-review/flow`：从工作台进入流程结构图，展示后端提供的静态节点和有向连线。
- 未识别的智能体路由会展示返回主页的入口。
- 流程图只展示结构，不显示节点执行状态或实时进度。会话使用异步运行与状态轮询，不提供逐字流式输出或长期历史。

会话页采用独立的暖白聊天布局：顶部简洁品牌与新建入口、居中欢迎文案、底部宽输入框，收起平台通用导航和页脚。点击左上角 Agent 返回智能体广场；其他平台页面继续使用原外壳。

会话页底部输入区中 Enter 发送、Shift+Enter 换行，中文输入法确认候选词不发送；附件为可选补充。支持停止、重试查询、新建对话及有效会话的刷新恢复。`sessionStorage` 仅保存会话/客户端消息 ID，不持久化用户正文；会话随服务重启或过期失效。发送响应丢失时重试复用同一客户端消息 ID，避免重复执行。切换会话或离开页面后忽略旧请求结果。

## 环境准备与启动

需要 Node.js 20.19+ 或 22.12+，以及 pnpm。

在 `frontend/` 目录执行：

```powershell
Copy-Item .env.example .env.local
pnpm install
pnpm dev
```

`pnpm install` 会解析新增的路由和 Markdown 渲染依赖并同步 `pnpm-lock.yaml`。本地启动后，Vite 默认将 `/api` 请求代理到 `http://127.0.0.1:8000`。启动后端的方法见 `../backend/README.md`。

若后端地址不同，可在 `.env.local` 中设置：

```dotenv
VITE_API_BASE_URL=http://localhost:8000
```

配置该变量后，前端请求会直接发往指定地址；跨域时需由后端允许当前前端来源。前缀不要以 `/` 结尾。

可用脚本：

| 命令 | 用途 |
| --- | --- |
| `pnpm dev` | 启动 Vite 开发服务器 |
| `pnpm build` | 类型检查并构建生产产物 |
| `pnpm preview` | 本地预览生产构建 |

会话重试回归使用 Node 内置测试与现有 TypeScript/Vue，不增加测试框架：

```powershell
node --test src/features/conversation-assistant/useConversation.test.cjs
```

## 前端结构

```text
src/
├── api/                         # API 客户端、错误映射及审核接口
├── components/workbench/        # 工作台共享状态展示
├── features/institution-review/ # 制度审核上传、报告与类型
├── router/                      # 页面路由
├── views/                       # 平台首页、智能体广场与工作台
├── App.vue                      # 顶部导航、主区域和页脚
├── main.ts                      # Vue 应用入口
└── style.css                    # 全局设计令牌和响应式样式
```

页面组合组件；制度审核细节留在对应 feature；API 层负责网络请求和错误转换。界面使用 Vue Composition API 局部状态，当前不引入全局状态管理。

## 接口与错误

工作台调用 `POST /api/v1/reviews`，通过 `FormData` 上传草稿 `file` 和 `review_mode`。`knowledge_base` 为默认方式；`standard_document` 还需标准 `standard_file`，不会调用知识库检索或 embedding。标准模式缺少任一文件时不能提交；提交期间禁用方式和文件输入。成功后读取 `text/markdown`。

标准模式由后端将超过 30 个草稿块合并为最多 30 个相邻条款组，保留原始条款定位。前端无需手工切块。流程图仍展示同一审核图的静态结构。前端分别校验两个文件的扩展名和空内容；服务端负责实际解析及大小限制。

API 错误按后端的 `{ error: { code, message, request_id, details? } }` 结构转换。`413`、`415` 和 `503` 会显示相应提示；网络不可达或响应内容不是 JSON 时显示通用错误。审核报告使用 `marked` 转为 HTML，并在渲染前由 `DOMPurify` 清理。

报告生成后，点击标题右侧“下载 Word”，会将当前完整 Markdown 提交至 `POST /api/v1/documents/export/docx`，下载为“制度审核报告.docx”，不重新审核。生成期间按钮禁用；失败在报告区域提示，报告保留并可重试。切换报告或离开页面会取消旧导出请求。下载不依赖前端读取跨域附件响应头，不需要修改后端 CORS 配置。

模型密钥和 RAGFlow 凭据仅属于后端配置，不得写入 Vite 环境变量或前端代码。会话相关代码位于 `features/conversation-assistant/` 和 `api/conversations.ts`；本次不新增业务工作流、报告版本或会话下载功能。
