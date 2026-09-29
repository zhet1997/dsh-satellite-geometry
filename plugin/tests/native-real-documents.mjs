// Explicit, authorized integration check on the imported CATCH satellite project.
// Not part of npm test; writes sourced metadata only, never geometry or pose.
import fs from 'node:fs/promises'
const host = 'http://127.0.0.1:3081'
const service = 'http://127.0.0.1:8789'
const sessionId = 'satellite-catch-documents-20260929'
const projectId = '51cf1056426043b59c23257fcf7695b6'
const documentIds = ['509a10db20e24aaf82edc90433060c79', 'a8170e5c4808458589f7e6ecde0de7cf']
const evidenceDir = new URL('../../validation/raw/', import.meta.url)
await fs.mkdir(evidenceDir, { recursive: true })
async function rpc(method, payload) {
  const response = await fetch(`${host}/api/${method}`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ type: 'client-request', rpcId: crypto.randomUUID(), method, payload }) })
  const body = await response.json(); if (!body.result?.ok) throw new Error(JSON.stringify(body.result)); return body.result.value
}
async function project() { const r = await fetch(`${service}/api/projects/${projectId}`); if (!r.ok) throw new Error(`project ${r.status}`); return r.json() }
if (process.argv.includes('--retry')) {
  const prompt = '几何服务已经更新，继续完成同一项目资料抽取验收。不要再读取本地源码、日志或其他项目；只用 satellite MCP。请先 read_project 获取当前 revision，然后重新 submit_metadata。注意最新协议：组件 origin:document，每项只传 id/massKg/powerW/sources，不传组件 notes，不传 changedFields；组件 notes 本身也是需原文来源的属性，你的尺寸匹配推断不是资料原文，因此将每个组件的匹配说明和置信度放在请求顶层 notes，或 sources.reference。sources.quote必须保留原始精确表行，尤其不要改变数字/空格/轴序。你的电池组偏差0.302mm，请修正顶层“全部≤0.3mm”表述并准确记录容差。若某项仍有来源冲突就省略或修正该项，保持无法唯一匹配项未知。写完使用read_project核验，简短报告结果；不做任何几何作业或位移。已有授权无需确认。'
  await rpc('session.prompt', { sessionId, mode: 'queue', content: [{ type: 'text', text: prompt }], clientTimeZone: 'Asia/Shanghai' })
  console.log(JSON.stringify({ sessionId, retryAccepted: true }))
} else if (process.argv.includes('--prompt')) {
  const before = await project()
  await fs.writeFile(new URL('catch-native-before.json', evidenceDir), JSON.stringify(before, null, 2))
  await rpc('session.create', { sessionId, cwd: 'D:/AgentPrj/my_new_computer/work/dsh-satellite-geometry' })
  await rpc('session.rename', { sessionId, title: 'CATCH 卫星真实资料抽取验收' })
  const prompt = `这是已授权的 DSH 插件验收。仅操作项目 ${projectId}（原项目 CATCH 卫星，33个组件），相关原始DOCX资料ID ${documentIds[0]}、XLSX资料ID ${documentIds[1]}。请加载 satellite-geometry skill，用 satellite MCP read_project 和 read_document 读取实际模型及两份资料。将能够可靠对应到组件的质量、功耗、材料等属性抽取并提交；组件名如P013_part与中文资料名可能不同，可依据唯一吻合的包络尺寸（考虑轴向排列与合理数值容差）及文档上下文对应，并在 notes 记录匹配依据；重复或不唯一匹配必须保留未知。至少认真寻找一个可靠映射，但没有证据时不要为达标强填。submit_metadata 用 origin:document，每个已给字段都有sources[{documentId,quote:精确原文,field}]，包括fixed:false也需来源，因此资料未说明固定性就省略。未提供值保持未知，不能假设0、false或常用材料。记录匹配置信度及仍需人工核对项。使用当前revision，不运行shell，不改名、分组、简化、位移、检查或导出，不访问其他项目。已有本任务授权，无需另行确认。结束时简要报告你实际读了哪些资料、写入哪些有依据属性和哪些未知。`
  await rpc('session.prompt', { sessionId, mode: 'queue', content: [{ type: 'text', text: prompt }], clientTimeZone: 'Asia/Shanghai' })
  console.log(JSON.stringify({ sessionId, projectId, revisionBefore: before.revision, promptAccepted: true }))
} else {
  const history = await rpc('session.history', { sessionId, maxMessages: 40 })
  const after = await project()
  await fs.writeFile(new URL('catch-native-evidence.json', evidenceDir), JSON.stringify({ sessionId, projectId, documentIds, history, project: after }, null, 2))
  const events = history.events.map(e => e.event || e)
  const meaningful = events.filter(e => /tool\/call|turn\/end|assistant\/message/.test(e.type)).map(e => ({ type: e.type, name: e.data?.name, status: e.data?.status, text: e.type === 'assistant/message' ? e.data?.message?.content?.filter(c => c.type === 'text').map(c => c.text).join('\n').slice(0, 1600) : undefined }))
  console.log(JSON.stringify({ sessionId, revision: after.revision, metadata: after.components.filter(c => Object.keys(c.metadata || {}).length).map(c => ({ id: c.id, name: c.name, massKg: c.metadata.massKg, powerW: c.metadata.powerW, provenanceFields: Object.keys(c.metadata.provenance || {}) })), events: meaningful.slice(-12) }, null, 2))
}
