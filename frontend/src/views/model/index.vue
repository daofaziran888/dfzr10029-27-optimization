<template>
  <section class="page" data-module="model">
    <header class="page-head">
      <div><h2>分析模型</h2><p class="page-desc">维护模型配置，围绕模型编号、模型名称、模型类型、训练数据集做登记、筛选与状态流转。</p></div>
      <div class="page-actions">
        <label class="group-picker">
          <span>当前用户组</span>
          <select v-model="currentGroup" data-testid="group-select" @change="reloadDeployable">
            <option v-for="group in userGroups" :key="group" :value="group">{{ group }}</option>
          </select>
        </label>
        <button class="btn primary" type="button" data-testid="open-create" @click="openCreate">登记模型配置</button>
        <button class="btn" type="button" data-testid="export" @click="exportRows">导出关系清单</button>
      </div>
    </header>
    <div class="dag-wrap" ref="dagRef">
      <svg class="dag-svg" :viewBox="`0 0 ${svgW} ${svgH}`">
        <defs><marker id="arrowhead" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto"><path d="M0,0 L8,3 L0,6" fill="#94a3b8"/></marker></defs>
        <g v-for="edge in graph.edges" :key="edge.from+edge.to">
          <line class="dag-edge" :x1="nodePos[edge.from]?.x||0" :y1="nodePos[edge.from]?.y||0" :x2="nodePos[edge.to]?.x||0" :y2="nodePos[edge.to]?.y||0"/>
          <text :x="(nodePos[edge.from]?.x+nodePos[edge.to]?.x)/2" :y="(nodePos[edge.from]?.y+nodePos[edge.to]?.y)/2 - 6" font-size="10" fill="#64748b" text-anchor="middle">{{ edge.label }}</text>
        </g>
        <g v-for="node in graph.nodes" :key="node.id" :class="['dag-node', {selected: selectedNode?.id===node.id}]" @click="selectNode(node)" @mousedown="startDrag($event, node)">
          <rect :x="nodePos[node.id]?.x - 60" :y="nodePos[node.id]?.y - 20" width="120" height="40" rx="6" :fill="nodeColor(node.status)"/>
          <text :x="nodePos[node.id]?.x" :y="nodePos[node.id]?.y + 4" text-anchor="middle">{{ node.name || node.label }}</text>
        </g>
      </svg>
    </div>
    <div v-if="selectedNode" class="dag-detail" data-testid="dag-detail">
      <dl><dt>编号</dt><dd>{{ selectedNode.id }}</dd></dl>
      <dl><dt>名称</dt><dd>{{ selectedNode.name || selectedNode.label }}</dd></dl>
      <dl v-for="f in detailFields" :key="f"><dt>{{ f }}</dt><dd>{{ selectedNode[f] ?? '—' }}</dd></dl>
      <div style="grid-column:1/-1; margin-top:8px; display:flex; gap:6px;">
        <button v-for="action in actions" :key="action" class="btn" :data-testid="`action-${selectedNode.id}-${action}`" @click="runAction(action, selectedNode)">{{ action }}</button>
      </div>
    </div>

    <section class="deploy-panel">
      <h3>按用户组授权的可部署版本</h3>
      <p class="page-desc">只展示当前用户组可部署的模型版本；特征快照范围按训练数据集归属脱敏，越权组看不到特征数据来自哪个训练集。</p>
      <table class="data-table" data-testid="deployable-table">
        <thead>
          <tr>
            <th>模型版本</th><th>模型名称</th><th>模型类型</th><th>训练数据集</th>
            <th>授权来源</th><th>特征快照范围</th><th>核对结果</th><th>授权状态</th><th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in deployable" :key="String(item.授权编号)" :data-testid="`deployable-${item.授权编号}`">
            <td>{{ item.模型版本 }}</td>
            <td>{{ item.模型名称 }}</td>
            <td>{{ item.模型类型 }}</td>
            <td>{{ item.训练数据集 }}</td>
            <td>{{ item.授权来源 }}</td>
            <td>{{ item.特征快照范围 }}</td>
            <td>{{ item.核对结果 }}</td>
            <td>{{ item.授权状态 }}</td>
            <td><button class="link" type="button" :data-testid="`deploy-detail-${item.授权编号}`" @click="showDeployment(item)">部署详情</button></td>
          </tr>
          <tr v-if="!deployable.length">
            <td colspan="9" class="empty-state">当前用户组暂无可部署的模型版本</td>
          </tr>
        </tbody>
      </table>
      <div v-if="deployment" class="deployment-detail" data-testid="deployment-detail">
        <dl><dt>模型版本</dt><dd>{{ deployment.模型版本 }}</dd></dl>
        <dl><dt>授权来源</dt><dd>{{ deployment.授权来源 }}</dd></dl>
        <dl><dt>特征快照范围</dt><dd>{{ deployment.特征快照范围 }}</dd></dl>
        <dl><dt>训练数据集</dt><dd>{{ deployment.训练数据集 }}</dd></dl>
        <dl><dt>核对结果</dt><dd>{{ deployment.核对结果 }}</dd></dl>
        <div class="source-records">
          <h4>来源记录</h4>
          <p>模型来源：{{ deployment.来源记录.模型来源.模型编号 }}（创建用户组：{{ deployment.来源记录.模型来源.创建用户组 || '—' }}）</p>
          <p>快照来源：{{ snapshotSourceText }}</p>
          <p>用户组来源：{{ deployment.来源记录.用户组来源.组名称 }}（{{ deployment.来源记录.用户组来源.组编号 || '—' }}）</p>
          <p>授权记录来源：{{ deployment.来源记录.授权记录来源.授权编号 }} · {{ deployment.来源记录.授权记录来源.模型版本 }} · {{ deployment.来源记录.授权记录来源.记录状态 }}</p>
        </div>
      </div>
      <p v-if="deployDenied" class="error-text" data-testid="deployment-denied">{{ deployDenied }}</p>
    </section>

    <div v-if="showCreate" class="modal-backdrop" data-testid="create-modal">
      <form class="modal" @submit.prevent="submitCreate"><h3>登记模型配置</h3>
        <label v-for="field in columns.slice(0,3)" :key="field" class="create-field"><span>{{ field }}</span><input v-model="createValues[field]" :placeholder="`请输入${field}`" required /></label>
        <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:12px">
          <button class="btn" type="button" @click="showCreate=false">取消</button>
          <button class="btn primary" type="submit" data-testid="submit-create">提交</button>
        </div>
      </form>
    </div>
    <footer class="page-foot">
      <span>{{ graph.nodes.length }} 个节点 · {{ deployable.length }} 个可部署版本</span>
      <span v-if="actionMessage">{{ actionMessage }}</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>
<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { request } from '@/api/client'
const ENDPOINT = '/api/model'
const columns = ["模型编号", "模型名称", "模型类型", "训练数据集", "特征字段", "目标字段", "评估指标", "模型状态", "创建用户组"]
const actions = ["提交训练", "启动评估", "部署模型"]
const statuses = ["草稿", "已训练", "评估中", "已部署", "已下线"]
const STATUS_COLORS: Record<string,string> = { '草稿':'#e2e8f0','待校验':'#fef3c7','已启用':'#d1fae5','已停用':'#fee2e2' }
const nodeColor = (s: string) => STATUS_COLORS[s] || '#e2e8f0'
const graph = reactive<{nodes: any[], edges: any[]}>({ nodes: [], edges: [] })
const nodePos = ref<Record<number,{x:number;y:number}>>({})
const selectedNode = ref<any>(null)
const detailFields = computed(() => columns.filter((f: string) => !['id','name','label','status'].includes(f)))
const svgW = ref(800); const svgH = ref(400)
const errorMessage = ref('')
const actionMessage = ref('')
const creating = ref(false); const showCreate = ref(false)
const createValues = ref<Record<string,string>>({})
const userGroups = ref<string[]>([])
const currentGroup = ref('')
const deployable = ref<any[]>([])
const deployment = ref<any>(null)
const deployDenied = ref('')
const snapshotSourceText = computed(() => {
  const sources = deployment.value?.来源记录?.快照来源 ?? []
  if (!sources.length) return '无权读取特征快照来源'
  return sources.map((s: any) => `${s.快照编号}（${s.数据集名称} · ${s.快照时间}）`).join('、')
})
let dragNode: any = null; const dagRef = ref<HTMLElement|null>(null)
function layout(nodes: any[]) {
  const w = 800; const h = Math.max(400, nodes.length * 80)
  svgW.value = w; svgH.value = h
  const pos: Record<number,{x:number;y:number}> = {}
  nodes.forEach((n,i) => { pos[n.id] = { x: 120 + (i % 5) * 150, y: 50 + Math.floor(i / 5) * 80 } })
  nodePos.value = pos
}
function selectNode(node: any) { selectedNode.value = selectedNode.value?.id === node.id ? null : node }
function startDrag(e: MouseEvent, node: any) { dragNode = node; const onMove = (ev: MouseEvent) => { if(!dragNode) return; nodePos.value[node.id] = { x: ev.offsetX, y: ev.offsetY } }; const onUp = () => { dragNode = null; document.removeEventListener('mousemove', onMove); document.removeEventListener('mouseup', onUp) }; document.addEventListener('mousemove', onMove); document.addEventListener('mouseup', onUp) }
async function reload() {
  try { const res = await request(ENDPOINT); const data = await res.json(); graph.nodes = data.nodes || []; graph.edges = data.edges || []; layout(graph.nodes) } catch(e) { errorMessage.value = '加载失败' }
}
async function reloadGroups() {
  try {
    const res = await request('/api/user_group?size=200')
    const data = await res.json()
    userGroups.value = (data.items || []).map((row: any) => String(row.组名称 || '')).filter(Boolean)
    if (!currentGroup.value && userGroups.value.length) currentGroup.value = userGroups.value[0]
  } catch(e) { errorMessage.value = '用户组列表读取失败' }
}
async function reloadDeployable() {
  deployment.value = null; deployDenied.value = ''
  if (!currentGroup.value) { deployable.value = []; return }
  try {
    const query = new URLSearchParams({ group: currentGroup.value }).toString()
    const res = await request(`${ENDPOINT}/deployable?${query}`)
    const data = await res.json()
    deployable.value = data.items || []
  } catch(e) { deployable.value = [] }
}
async function showDeployment(item: any) {
  deployment.value = null; deployDenied.value = ''
  try {
    const query = new URLSearchParams({ group: currentGroup.value }).toString()
    const res = await request(`${ENDPOINT}/${item.模型id}/deployment?${query}`)
    if (res.status === 403) {
      const data = await res.json().catch(() => ({}))
      deployDenied.value = data.detail || '越权查看被拒绝'
      return
    }
    if (!res.ok) throw new Error('部署详情读取失败')
    deployment.value = await res.json()
  } catch(e: any) { deployDenied.value = e.message || '部署详情读取失败' }
}
async function runAction(action: string, node: any) {
  actionMessage.value = ''
  try {
    const res = await request(`${ENDPOINT}/${node.id}/actions`, { method: 'POST', body: JSON.stringify({ action, group: currentGroup.value }) })
    const data = await res.json().catch(() => ({}))
    if (!res.ok || data.ok === false) { errorMessage.value = data.message || data.detail || '操作失败' ; return }
    actionMessage.value = data.message || ''
    await reload(); await reloadDeployable()
  } catch(e) { errorMessage.value = '操作失败' }
}
function openCreate() { createValues.value = {}; showCreate.value = true }
async function submitCreate() {
  try { const res = await request(ENDPOINT, { method: 'POST', body: JSON.stringify({ values: createValues.value }) }); if(!res.ok) throw new Error('创建失败'); showCreate.value = false; await reload() } catch(e: any) { errorMessage.value = e.message }
}
function exportRows() { window.open(`${ENDPOINT}/export`, '_blank') }
onMounted(async () => { await reload(); await reloadGroups(); await reloadDeployable() })
</script>
<style scoped>
.deploy-panel { margin-top: 16px; }
.deploy-panel h3 { margin: 0 0 4px; font-size: 15px; }
.group-picker { display: flex; align-items: center; gap: 6px; font-size: 13px; color: var(--muted); }
.group-picker select { padding: 6px 10px; border: 1px solid var(--border); border-radius: 6px; font-size: 13px; }
.deployment-detail { margin-top: 10px; border: 1px solid var(--border); border-radius: 8px; padding: 12px; background: #fafbfc; display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.deployment-detail dt { font-size: 12px; color: var(--muted); }
.deployment-detail dd { font-size: 13px; margin: 0 0 8px 0; }
.source-records { grid-column: 1 / -1; border-top: 1px dashed var(--border); padding-top: 8px; }
.source-records h4 { margin: 0 0 6px; font-size: 13px; }
.source-records p { margin: 2px 0; font-size: 12px; color: var(--muted); }
</style>
