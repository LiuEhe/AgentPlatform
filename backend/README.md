# 智能体平台后端

基于 Python 3.12/3.13、FastAPI、LangChain、LangGraph 和 RAGFlow 的同步制度审核服务。首版接收 DOCX 制度草稿，使用公共 DOCX 转 Markdown 节点解析后，由制度审核流程按章、条代码拆分，输出四部分 Markdown 报告。不保存审核结果，也不依赖 Redis 或关系型数据库。

## 环境准备

需要 Python 3.12 或 3.13。

复制 `.env.example` 为 `.env`，填入模型服务和 RAGFlow 的配置：

- `LLM_MODEL`、`LLM_API_KEY`：OpenAI 兼容模型名称与密钥。
- `LLM_BASE_URL`：可选的 OpenAI 兼容服务地址；连接 OpenAI 官方服务时留空。
- `LLM_TIMEOUT_SECONDS`：模型请求超时时间，默认 180 秒，可配置范围为 30–600 秒；百炼兼容接口通过 `enable_thinking=false` 关闭思考模式。
- `RAGFLOW_BASE_URL`、`RAGFLOW_API_KEY`、`RAGFLOW_DATASET_ID`：RAGFlow 地址、API Key 和制度知识库 ID。
- `MAX_UPLOAD_BYTES`：单个上传文件大小上限，默认 20 MiB。
- `MAX_REVIEW_CHARS`：DOCX 转换为 Markdown 后的正文字符数上限。

## 安装与启动

在 `backend/` 目录下执行：

```powershell
uv sync
uv run uvicorn app.main:create_app --factory --reload
```

使用 Python 虚拟环境时，也可以在 `backend/` 目录下运行 `python -m pip install -e .`，然后执行 `uvicorn app.main:create_app --factory --reload`。

## 质量检查

使用 `uv` 安装开发依赖后，在 `backend/` 目录执行：

```powershell
uv sync --locked --group dev
uv run ruff check app tests
uv run pytest
```

GitHub Actions 会在 Pull Request 和推送到 `main` 时执行后端静态检查、测试，以及前端锁文件安装和生产构建。

## 接口

- `GET /health/live`：进程存活状态。
- `GET /health/ready`：模型及 RAGFlow 配置就绪状态。
- `POST /api/v1/reviews`：使用 `multipart/form-data` 上传一个 `.docx` 文件，同步返回 `text/markdown` 报告。

PowerShell 示例：

```powershell
curl.exe -X POST "http://127.0.0.1:8000/api/v1/reviews" -F "file=@制度草稿.docx"
```

审核流程由全文术语检查分支和逐条条款检索审查分支组成。条款拆分由代码完成；每条分别检索 RAGFlow 并由模型检查冲突或重复。最终 Markdown 包含简述、冲突检测、术语检测和修改建议四部分。文档读取能力位于公共 `app/nodes/`，便于其他流程复用。
