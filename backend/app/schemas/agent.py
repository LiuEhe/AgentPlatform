"""智能体展示元数据，不包含运行权限或供应商配置。"""

from pydantic import BaseModel


class AgentMetadata(BaseModel):
    agent_id: str
    name: str
    description: str
