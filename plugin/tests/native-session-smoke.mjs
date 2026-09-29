// Explicit integration check, never part of npm test. Uses only a synthetic test fixture.
import fs from 'node:fs/promises'
const host = 'http://127.0.0.1:3081'
const service = process.env.SATCAD_TEST_SERVICE || 'http://127.0.0.1:8787'
const sessionId = 'satellite-plugin-integration-20260929'
const stateFile = new URL('../../validation/raw/native-smoke-state.json', import.meta.url)
await fs.mkdir(new URL('../../validation/raw/', import.meta.url), { recursive: true })
async function rpc(method, payload) {
  const r = await fetch(`${host}/api/${method}`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ type: 'client-request', rpcId: crypto.randomUUID(), method, payload }) })
  const body = await r.json(); if (!body.result?.ok) throw new Error(JSON.stringify(body.result)); return body.result.value
}
async function api(url, init) { const r = await fetch(`${service}${url}`, init); const body = await r.json(); if (!r.ok) throw new Error(JSON.stringify(body)); return body }
if (process.argv.includes('--prepare')) {
  const p = await api('/api/projects', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ name: 'DSH-MCP-资料抽取验收' }) })
  const projectId = p.id || p.project?.id
  const source = await fetch(`${service}/api/projects/${process.env.SATCAD_TEST_SOURCE_PROJECT || '60c5d49617a94642801511ebc002b019'}/artifacts/source.step`)
  const form = new FormData(); form.append('file', new Blob([await source.arrayBuffer()]), 'synthetic-contact.step')
  const job = await api(`/api/projects/${projectId}/import`, { method: 'POST', body: form })
  const state = { sessionId, projectId, jobId: job.jobId }
  await fs.writeFile(stateFile, JSON.stringify(state, null, 2)); console.log(JSON.stringify(state))
} else if (process.argv.includes('--prompt')) {
  const state = JSON.parse(await fs.readFile(stateFile, 'utf8'))
  const project = await api(`/api/projects/${state.projectId}`)
  if (!project.components?.length) throw new Error('fixture import not complete')
  const docs = new FormData()
  docs.append('file', new Blob(['验收用合成资料，非真实卫星参数。\nFour_foot_device（组件 N00003）：额定功耗 12.5 W；质量未知；安装后位置固定。\nMounting_plate（组件 N00002）：材料为铝合金；质量未提供。\n'], { type: 'text/plain' }), 'synthetic-specification.txt')
  const document = await api(`/api/projects/${state.projectId}/documents`, { method: 'POST', body: docs })
  state.documentId = document.document?.id || document.id
  await rpc('session.create', { sessionId, cwd: 'D:/AgentPrj/my_new_computer/work/dsh-satellite-geometry' })
  await rpc('session.rename', { sessionId, title: '卫星插件 MCP 资料抽取验收（合成数据）' })
  const prompt = `这是已授权的插件集成验收，仅操作合成项目 ${state.projectId}，资料ID ${state.documentId}。请用 satellite MCP 工具 read_project、read_document 读取该项目和资料，抽取有原文支持的功耗、固定约束、材料，使用 submit_metadata 提交到正确组件，sources必须包含documentId、精确原文quote和field。资料中未提供质量，必须保留未知，不能补造。当前任务无需再征求批准。不要运行shell、不要移动或简化几何、不涉及其他项目。结束时简短报告实际调用工具和写入结果。`
  await rpc('session.prompt', { sessionId, mode: 'queue', content: [{ type: 'text', text: prompt }], clientTimeZone: 'Asia/Shanghai' })
  await fs.writeFile(stateFile, JSON.stringify(state, null, 2)); console.log(JSON.stringify({ ...state, promptAccepted: true }))
} else {
  const state = JSON.parse(await fs.readFile(stateFile, 'utf8'))
  const history = await rpc('session.history', { sessionId, maxMessages: 15 })
  const project = await api(`/api/projects/${state.projectId}`)
  await fs.writeFile(new URL('../../validation/raw/native-smoke-evidence.json', import.meta.url), JSON.stringify({ state, history, project }, null, 2))
  console.log(JSON.stringify({ state, revision: project.revision, metadata: project.components?.map(c => ({ id: c.id, metadata: c.metadata })), events: history.events.map(e => ({ type: e.event?.type || e.type, data: e.event?.data || e.data })).filter(e => /tool|turn\/end|assistant\/message/.test(e.type)) }, null, 2))
}
