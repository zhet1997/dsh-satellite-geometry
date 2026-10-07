// Explicit native model integration check, not part of npm test. Read-only.
import fs from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
const host = 'http://127.0.0.1:3081'
const sessionId = 'satellite-selection-reference-20260929'
const stateFile = new URL('../../validation/raw/selection-native-state.json', import.meta.url)
await fs.mkdir(new URL('../../validation/raw/', import.meta.url), { recursive: true })
async function rpc(method, payload, channel = '/api') {
  const r = await fetch(`${host}${channel}/${method}`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ type: 'client-request', rpcId: crypto.randomUUID(), method, payload }) })
  const body = await r.json(); if (!body.result?.ok) throw new Error(JSON.stringify(body.result)); return body.result.value
}
if (process.argv.includes('--prompt')) {
  await rpc('session.create', { sessionId, cwd: fileURLToPath(new URL('../../', import.meta.url)) })
  await rpc('session.rename', { sessionId, title: '几何选择短引用验收' })
  const context = await rpc('selection.snapshot', { sessionId, projectId: '4a11df37a4394074b88f32d11905272c', revision: 3, selection: [{ nodeId: 'N00003', name: 'Four_foot_device' }] }, '/satellite-geometry-rpc')
  await fs.writeFile(stateFile, JSON.stringify({ sessionId, ...context }, null, 2))
  await rpc('session.prompt', { sessionId, mode: 'queue', content: [{ type: 'text', text: `所选组件：Four_foot_device（几何引用 ${context.ref}）\n这是只读验收。请使用 satellite_selection_context 解析此引用，再用 satellite MCP read_project 确认所选对象。只报告组件名称、功耗及固定性，并说明未提供的质量保持未知。不要写入、不要做几何作业、不要运行shell。` }], clientTimeZone: 'Asia/Shanghai' })
  console.log(JSON.stringify({ sessionId, ref: context.ref, promptAccepted: true }))
} else {
  const state = JSON.parse(await fs.readFile(stateFile, 'utf8'))
  const history = await rpc('session.history', { sessionId, maxMessages: 20 })
  await fs.writeFile(new URL('../../validation/raw/selection-native-evidence.json', import.meta.url), JSON.stringify({ state, history }, null, 2))
  const events = history.events.map(e => e.event || e)
  console.log(JSON.stringify(events.filter(e => /tool\/call|turn\/end|assistant\/message/.test(e.type)).map(e => ({ type: e.type, name: e.data?.name, arguments: e.data?.arguments, status: e.data?.status, text: e.type === 'assistant/message' ? e.data?.message?.content?.filter(c => c.type === 'text').map(c => c.text).join('\n') : undefined })), null, 2))
}
