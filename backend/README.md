# 智能体平台后端

基于 Python 3.12、FastAPI、LangChain、LangGraph 和 RAGFlow 的同步制度审核服务。首版只处理文本，不保存审核结果，也不依赖 Redis 或关系型数据库。

## 环境准备

复制 `.env.example` 为 `.env`，填入模型服务和 RAGFlow 的配置：

- `LLM_MODEL`、`LLM_API_KEY`：OpenAI 兼容模型名称与密钥。
- `LLM_BASE_URL`：可选的 OpenAI 兼容服务地址；连接 OpenAI 官方服务时留空。
- `RAGFLOW_BASE_URL`、`RAGFLOW_API_KEY`、`RAGFLOW_DATASET_ID`：RAGFlow 地址、API Key 和制度知识库 ID。
- `MAX_REVIEW_CHARS`：单次审核正文最大字符数。

## 安装与启动

在 `backend/` 目录下执行：

```powershell
uv sync
uv run uvicorn app.main:create_app --factory --reload
```

使用 Python 虚拟环境时，也可以在 `backend/` 目录下运行 `python -m pip install -e .`，然后执行 `uvicorn app.main:create_app --factory --reload`。

## 接口

- `GET /health/live`：进程存活状态。
- `GET /health/ready`：模型及 RAGFlow 配置就绪状态。
- `POST /api/v1/reviews`：同步审核制度文本并返回结果。

审核请求示例：

```json
{
  "title": "制度标题",
  "content": "需要审核的制度正文"
}
```

审核链路会检索 RAGFlow 知识库，拆分条款，并执行术语、冲突、重复和合规检查，最后汇总发现项和修改建议。结果只在本次响应中返回。
