import { ApiError, createApiError, getApiBaseUrl } from './client'
import type { AgentGraph } from '../features/institution-review/types'

export interface AgentMetadata { agent_id: string; name: string; description: string }

export async function listAgents(): Promise<AgentMetadata[]> {
  let response: Response
  try {
    response = await fetch(`${getApiBaseUrl()}/api/v1/agents`, { headers: { Accept: 'application/json' } })
  } catch {
    throw new ApiError({ status: 0, message: '无法连接智能体目录，请稍后重试。' })
  }
  if (!response.ok) throw await createApiError(response)
  return response.json() as Promise<AgentMetadata[]>
}

export async function getAgentGraph(agentId: string): Promise<AgentGraph> {
  let response: Response
  try {
    response = await fetch(
      `${getApiBaseUrl()}/api/v1/agents/${encodeURIComponent(agentId)}/graph`,
      { headers: { Accept: 'application/json' } },
    )
  } catch {
    throw new ApiError({
      status: 0,
      message: '无法连接智能体服务，请确认服务已启动后重试。',
    })
  }

  if (!response.ok) throw await createApiError(response)
  return response.json() as Promise<AgentGraph>
}
