# AgentPlatform 前端

基于 Vue 3、TypeScript 和 Vite 的智能体工作空间。首版提供智能体主页，以及连接现有制度审核 API 的工作台。

## 当前功能

- `/`：智能体主页，展示当前可用的制度审核助手。
- `/agents/institution-review`：制度审核工作台，选择 `.docx` 文件后提交审核，查看 Markdown 报告。
- 未识别的智能体路由会展示返回主页的入口。
- 上传请求只显示请求级状态。后端暂不提供会话、节点级进度、流式消息或审核历史。

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

## 前端结构

```text
src/
├── api/                         # API 客户端、错误映射及审核接口
├── components/workbench/        # 工作台共享状态展示
├── features/institution-review/ # 制度审核上传、报告与类型
├── router/                      # 页面路由
├── views/                       # 智能体主页与工作台
├── App.vue                      # 顶部导航、主区域和页脚
├── main.ts                      # Vue 应用入口
└── style.css                    # 全局设计令牌和响应式样式
```

页面组合组件；制度审核细节留在对应 feature；API 层负责网络请求和错误转换。界面使用 Vue Composition API 局部状态，当前不引入全局状态管理。

## 接口与错误

工作台调用 `POST /api/v1/reviews`，通过 `FormData` 上传字段 `file`，成功后读取 `text/markdown`。前端校验扩展名和空文件；服务端仍负责文件类型和大小校验。

API 错误按后端的 `{ error: { code, message, request_id, details? } }` 结构转换。`413`、`415` 和 `503` 会显示相应提示；网络不可达或响应内容不是 JSON 时显示通用错误。审核报告使用 `marked` 转为 HTML，并在渲染前由 `DOMPurify` 清理。

模型密钥和 RAGFlow 凭据仅属于后端配置，不得写入 Vite 环境变量或前端代码。后续接入通用聊天或工作流前，应先与后端明确会话格式、流式协议、停止执行和历史恢复契约。
