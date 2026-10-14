<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import { ApiError } from '../api/client'
import { getAgentGraph } from '../api/agents'
import type { AgentGraph, AgentGraphEdge, AgentGraphNode } from '../features/institution-review/types'

const route = useRoute()
const agentId = computed(() => String(route.params.agentId ?? ''))
const isKnownAgent = computed(() => agentId.value === 'institution-review')
const graph = ref<AgentGraph | null>(null)
const loading = ref(false)
const errorMessage = ref('')
let requestVersion = 0

watch(agentId, async (slug) => {
  const version = ++requestVersion
  graph.value = null
  errorMessage.value = ''
  if (slug !== 'institution-review') {
    loading.value = false
    return
  }

  loading.value = true
  try {
    const result = await getAgentGraph('institution_review')
    if (version === requestVersion) graph.value = result
  } catch (error) {
    if (version === requestVersion) {
      errorMessage.value = error instanceof ApiError
        ? error.message
        : '流程图暂时无法加载，请稍后重试。'
    }
  } finally {
    if (version === requestVersion) loading.value = false
  }
}, { immediate: true })

const positions: Record<string, { x: number; y: number; width: number }> = {
  START: { x: 480, y: 70, width: 150 },
  split_clauses: { x: 270, y: 220, width: 220 },
  check_terminology: { x: 690, y: 220, width: 220 },
  review_clauses: { x: 270, y: 370, width: 220 },
  generate_report_sections: { x: 480, y: 520, width: 250 },
  generate_suggestions: { x: 480, y: 650, width: 250 },
  assemble_report: { x: 480, y: 780, width: 220 },
  END: { x: 480, y: 890, width: 150 },
}

function nodePosition(nodeId: string) {
  return positions[nodeId] ?? { x: 480, y: 70, width: 220 }
}

function edgePath(edge: AgentGraphEdge, sourceId: string) {
  const source = nodePosition(sourceId)
  const target = nodePosition(edge.target)
  const startY = source.y + (sourceId === 'START' || sourceId === 'END' ? 22 : 35)
  const endY = target.y - (edge.target === 'END' || edge.target === 'START' ? 22 : 35)
  const bend = Math.max(38, (endY - startY) * 0.48)
  return `M ${source.x} ${startY} C ${source.x} ${startY + bend}, ${target.x} ${endY - bend}, ${target.x} ${endY}`
}

const renderedEdges = computed(() => (graph.value?.edges ?? []).flatMap((edge, edgeIndex) =>
  edge.sources.map((sourceId, sourceIndex) => ({
    key: `${edgeIndex}-${sourceIndex}-${sourceId}-${edge.target}`,
    sourceId,
    target: edge.target,
    d: edgePath(edge, sourceId),
    branch: sourceId === 'check_terminology' ? 'sage' : 'violet',
  })),
))

function nodeClass(node: AgentGraphNode) {
  if (node.id === 'START' || node.id === 'END') return 'flow-node flow-node-terminal'
  if (node.id === 'check_terminology') return 'flow-node flow-node-sage'
  return 'flow-node'
}

function nodeLabel(nodeId: string) {
  return graph.value?.nodes.find((node) => node.id === nodeId)?.label ?? nodeId
}

function edgeDescription(edge: AgentGraphEdge) {
  return `${edge.sources.map(nodeLabel).join('、')} → ${nodeLabel(edge.target)}`
}
</script>

<template>
  <div v-if="!isKnownAgent" class="not-found-panel">
    <span class="not-found-mark" aria-hidden="true">?</span>
    <div class="eyebrow"><span class="eyebrow-line"></span> AGENT NOT FOUND</div>
    <h1>暂时找不到这位智能体</h1>
    <p>这个入口可能已调整，回到智能体主页看看当前可用的能力。</p>
    <RouterLink class="button button-primary" to="/">返回智能体主页 <span class="button-arrow" aria-hidden="true">↗</span></RouterLink>
  </div>

  <div v-else class="flow-page">
    <div class="breadcrumb">
      <RouterLink to="/agents">智能体广场</RouterLink><span aria-hidden="true">/</span>
      <RouterLink :to="`/agents/${agentId}`">制度审核助手</RouterLink><span aria-hidden="true">/</span>
      <span>流程结构</span>
    </div>

    <header class="flow-heading">
      <div>
        <div class="eyebrow"><span class="eyebrow-line"></span> AGENT WORKFLOW</div>
        <h1>{{ graph?.name ?? '制度审核助手' }}<span class="heading-period">.</span></h1>
        <p>查看流程节点与连接关系，了解文档如何经过条款与术语检查并汇总为报告。</p>
      </div>
      <RouterLink class="button button-quiet" :to="`/agents/${agentId}`">返回工作台 <span aria-hidden="true">↗</span></RouterLink>
    </header>

    <section class="flow-card" aria-labelledby="flow-structure-title">
      <div class="flow-card-heading">
        <div>
          <div class="aside-card-kicker">STRUCTURE OVERVIEW</div>
          <h2 id="flow-structure-title">流程结构</h2>
        </div>
        <span v-if="graph" class="flow-count">{{ graph.nodes.length }} 个节点 <i></i> {{ graph.edges.length }} 组连线</span>
      </div>

      <div v-if="loading" class="flow-message" role="status">正在读取流程结构…</div>
      <div v-else-if="errorMessage" class="flow-message flow-error" role="alert">
        <span class="flow-error-mark" aria-hidden="true">!</span>
        <div><strong>流程图暂时无法显示</strong><p>{{ errorMessage }}</p></div>
        <button class="button button-quiet" type="button" @click="$router.go(0)">重试</button>
      </div>

      <div v-else-if="graph" class="diagram-scroll" role="region" aria-label="制度审核智能体流程图" tabindex="0">
        <svg class="flow-diagram" viewBox="0 0 960 950" role="img" :aria-label="`${graph.name}流程图`" aria-describedby="flow-diagram-description">
          <defs>
            <marker id="flow-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
              <path d="M 0 0 L 10 5 L 0 10 z" fill="#aaa3bd" />
            </marker>
          </defs>
          <g class="edge-layer" aria-hidden="true">
            <path v-for="edge in renderedEdges" :key="edge.key" :d="edge.d" :class="['flow-edge', `flow-edge-${edge.branch}`]" marker-end="url(#flow-arrow)" />
          </g>
          <g v-if="graph.edges.some((edge) => edge.sources.length > 1)" class="join-note" aria-hidden="true">
            <rect x="395" y="438" width="170" height="30" rx="15" />
            <text x="480" y="458" text-anchor="middle">全部来源完成后</text>
          </g>
          <g v-for="node in graph.nodes" :key="node.id" :class="nodeClass(node)" :transform="`translate(${nodePosition(node.id).x}, ${nodePosition(node.id).y})`">
            <rect :x="-nodePosition(node.id).width / 2" y="-35" :width="nodePosition(node.id).width" height="70" rx="9" />
            <circle v-if="node.id !== 'START' && node.id !== 'END'" :cx="-nodePosition(node.id).width / 2 + 21" cy="0" r="4" />
            <text text-anchor="middle" y="5">{{ node.label }}</text>
          </g>
        </svg>
        <div id="flow-diagram-description" class="visually-hidden">
          <h3>流程节点</h3>
          <ol><li v-for="node in graph.nodes" :key="node.id">{{ node.label }}</li></ol>
          <h3>连线关系</h3>
          <ul><li v-for="(edge, index) in graph.edges" :key="index">{{ edgeDescription(edge) }}</li></ul>
        </div>
      </div>

      <div v-if="graph" class="flow-legend">
        <span><i class="legend-dot legend-dot-violet"></i>条款审查</span>
        <span><i class="legend-dot legend-dot-sage"></i>术语检查</span>
        <span class="legend-note">连线表示流程关系，不代表实时执行进度</span>
      </div>
    </section>
  </div>
</template>

<style scoped>
.flow-page { padding: 30px max(5.4vw, calc((100vw - 1240px) / 2)) 76px; }
.flow-heading { display: flex; justify-content: space-between; gap: 24px; align-items: end; padding: 32px 0 29px; border-bottom: 1px solid var(--line); }
.flow-heading h1 { margin: 9px 0 7px; color: #292638; font-size: clamp(27px, 4vw, 36px); font-weight: 500; letter-spacing: -1px; }
.flow-heading p { max-width: 610px; margin: 0; color: #827f8b; font-size: 12px; line-height: 1.8; }
.flow-card { margin-top: 24px; overflow: hidden; border: 1px solid #e8e5e0; border-radius: 7px; background: #fff; box-shadow: 0 4px 15px rgba(39, 35, 54, .025); }
.flow-card-heading { display: flex; justify-content: space-between; align-items: center; padding: 22px 25px 16px; border-bottom: 1px solid #f0eeeb; }
.flow-card-heading h2 { margin: 7px 0 0; color: #302d3d; font-size: 18px; font-weight: 500; }
.aside-card-kicker { color: #9b96a5; font-family: var(--mono); font-size: 9px; letter-spacing: 1.1px; }
.flow-count { display: flex; gap: 9px; align-items: center; color: #85818d; font-size: 10px; }
.flow-count i { width: 3px; height: 3px; border-radius: 50%; background: #bbb6c4; }
.diagram-scroll { overflow-x: auto; padding: 12px 22px 4px; overscroll-behavior-x: contain; }
.diagram-scroll:focus-visible { outline: 3px solid rgba(115, 86, 206, .34); outline-offset: -3px; }
.flow-diagram { display: block; width: min(100%, 900px); min-width: 680px; height: auto; margin: 0 auto; overflow: visible; }
.flow-edge { fill: none; stroke: #c1bbcf; stroke-width: 1.7; }
.flow-edge-violet { stroke: #ab9bd4; }
.flow-edge-sage { stroke: #a8c0aa; }
.flow-node rect { fill: #fff; stroke: #e5e1eb; stroke-width: 1.2; filter: drop-shadow(0 4px 8px rgba(45, 38, 70, .045)); }
.flow-node circle { fill: #9b86cf; }
.flow-node text { fill: #4c4858; font-size: 13px; font-family: inherit; }
.flow-node-sage circle { fill: #87a98d; }
.flow-node-terminal rect { fill: #f7f4fc; stroke: #ddd5ef; }
.flow-node-terminal text { fill: #67568f; font-size: 12px; }
.join-note rect { fill: #f7f6f2; stroke: #e8e4ec; }
.join-note text { fill: #797484; font-size: 10px; font-family: inherit; }
.flow-legend { display: flex; flex-wrap: wrap; gap: 17px; align-items: center; padding: 14px 25px 17px; border-top: 1px solid #f0eeeb; color: #7d7987; font-size: 10px; }
.flow-legend > span:not(.legend-note) { display: inline-flex; gap: 7px; align-items: center; }
.legend-dot { width: 7px; height: 7px; border-radius: 50%; background: #9b86cf; }
.legend-dot-sage { background: #87a98d; }
.legend-note { margin-left: auto; color: #a09da6; }
.flow-message { min-height: 290px; display: flex; justify-content: center; align-items: center; gap: 13px; padding: 30px; color: #777381; font-size: 12px; }
.flow-error { color: #746f7d; }
.flow-error-mark { width: 30px; height: 30px; display: grid; place-items: center; border-radius: 50%; color: #a64b55; background: #fbefef; font-weight: 600; }
.flow-error strong { color: #454151; font-size: 13px; font-weight: 500; }
.flow-error p { margin: 6px 0 0; color: #898592; }
.flow-error .button { margin-left: 12px; }
.flow-link { text-decoration: none; color: #655092; }
.flow-link:hover { border-color: #d6cdea; background: #faf8ff; }
@media (max-width: 680px) {
  .flow-page { padding: 20px 5vw 48px; }
  .flow-heading { align-items: start; flex-direction: column; padding: 25px 0 22px; }
  .flow-heading .button { align-self: start; }
  .flow-card-heading { padding-right: 17px; padding-left: 17px; }
  .diagram-scroll { padding-right: 8px; padding-left: 8px; }
  .flow-legend { gap: 11px; padding-right: 17px; padding-left: 17px; }
  .legend-note { width: 100%; margin-left: 0; }
}
</style>
