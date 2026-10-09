import { Server } from '@modelcontextprotocol/sdk/server/index.js'
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js'
import { CallToolRequestSchema, ListToolsRequestSchema } from '@modelcontextprotocol/sdk/types.js'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const str = { type: 'string', minLength: 1 }
const revision = { type: 'integer', minimum: 0 }
const object = (properties, required = []) => ({ type: 'object', properties, required, additionalProperties: false })
const project = { projectId: str }
const rev = { ...project, revision }
const source = object({ documentId: str, quote: str, field: str, reference: { type: 'string', description: '原资料表行/页码及组件匹配依据；推断说明放此处或请求顶层notes，不冒充原文quote。' } }, ['documentId', 'quote', 'field'])
const motion = object({ allowedTranslationAxes: { type: 'array', items: { type: 'string', enum: ['X', 'Y', 'Z'] } }, maxTranslationMm: { type: 'number', minimum: 0 }, maxRotationDeg: { type: 'number', minimum: 0, maximum: 180 }, preserveContacts: { type: 'boolean', const: true }, reason: str, sources: { type: 'array', items: source } }, ['allowedTranslationAxes', 'maxTranslationMm', 'maxRotationDeg', 'preserveContacts', 'reason', 'sources'])
const definitions = [
  ['health', '检查几何服务能力和连接状态。不会调用推理模型。', object({}), 'GET', () => '/api/capabilities'],
  ['list_projects', '列出卫星几何项目；项目与模型版本必须明确后才能修改。', object({}), 'GET', () => '/api/projects'],
  ['create_project', '创建独立卫星几何项目；STEP 和资料随后在工作台上传。', object({ name: str }, ['name']), 'POST', () => '/api/projects'],
  ['read_project', '读取项目、装配树、组件稳定ID、版本、资料列表和检查结论。大项目或写入后核验时传componentIds分批读取，避免结果过长。unknown不等于检查通过。', object({ ...project, componentIds: { type: 'array', minItems: 1, maxItems: 100, items: str } }, ['projectId']), 'GET', a => `/api/projects/${id(a.projectId)}`],
  ['read_document', '读取用户上传资料解析出的文字及来源；抽取功耗、质量、材料、安装约束时必须引用原文，不得补造缺失信息。', object({ ...project, documentId: str }, ['projectId', 'documentId']), 'GET', a => `/api/projects/${id(a.projectId)}/documents/${id(a.documentId)}`],
  ['submit_metadata', '提交资料抽取的属性，origin默认document；每个已知字段（包括fixed:false）必须有对应field、documentId及精确原文quote。缺失属性省略，不能补造。motionConstraints来源field写全路径，如motionConstraints.maxTranslationMm。仅用户明确人工提供数值时允许origin:manual且省略sources，不能借manual规避资料证据校验。changedFields若提供必须列出实际提交的全部属性键。', object({ ...rev, components: { type: 'array', items: object({ id: str, origin: { type: 'string', enum: ['document', 'manual'], default: 'document' }, changedFields: { type: 'array', items: str }, massKg: { type: ['number', 'null'], minimum: 0 }, powerW: { type: ['number', 'null'], minimum: 0 }, fixed: { type: ['boolean', 'null'] }, thermalCritical: { type: ['boolean', 'null'] }, material: { type: ['string', 'null'] }, notes: { type: 'string' }, motionConstraints: motion, sources: { type: 'array', items: source } }, ['id']) }, notes: { type: 'string' } }, ['projectId', 'revision', 'components']), 'POST', a => `/api/projects/${id(a.projectId)}/metadata`],
  ['create_plan', '为指定组件提出可预览的几何简化计划。默认保持原world位姿，preserve/box/multibox是几何表示策略，不是移动指令；有疑义保留组件，真实接触/热关键特征优先保护。', object({ ...rev, summary: str, operations: { type: 'array', items: object({ componentId: str, action: { type: 'string', enum: ['preserve', 'box', 'multibox'] }, reason: str, sources: { type: 'array', items: source } }, ['componentId', 'action', 'reason']) } }, ['projectId', 'revision', 'summary', 'operations']), 'POST', a => `/api/projects/${id(a.projectId)}/plans`],
  ['apply_plan', '按用户本次任务授权自主执行简化方案，无需每个计划重复确认；用户要求仅预览时停止在计划。必须使用当前revision，不改变组件位姿。返回jobId后查询任务，不能提前宣称完成。', object({ ...rev, planId: str, preserveContacts: { type: 'boolean', description: '默认true；thermal必须true。assembly/envelope仅在用户明确允许简化接触组件时可为false，随后仍须检查并报告接触变化。' }, purpose: { type: 'string', enum: ['thermal', 'assembly', 'envelope'] } }, ['projectId', 'revision', 'planId', 'preserveContacts', 'purpose']), 'POST', a => `/api/projects/${id(a.projectId)}/plans/${id(a.planId)}/apply`],
  ['check_project', '执行可用的真实几何与包络检查，明确区分原始实体相交与包络相交。unknown/不可验证必须如实汇报。', object(rev, ['projectId', 'revision']), 'POST', a => `/api/projects/${id(a.projectId)}/check`],
  ['export_project', '导出当前模型版本的简化STEP、查看模型及结构化记录。导出成功本身不是几何质量合格证明。', object(rev, ['projectId', 'revision']), 'POST', a => `/api/projects/${id(a.projectId)}/export`],
  ['rebuild_equipment_envelopes', '用户明确选择设备等效包络、热接触另行定义时执行完整 preserve/box 方案。源外形实测局部包围盒重建有效闭合实体，保持原始位姿；源缺陷保留为证据，不认证真实接触或包络相交。', object({ ...rev, planId: str, authorization: { type: 'string', const: 'user_requested_equivalent_envelopes' }, thermalContacts: { type: 'string', const: 'separately_defined' }, reason: str }, ['projectId', 'revision', 'planId', 'authorization', 'thermalContacts', 'reason']), 'POST', a => `/api/projects/${id(a.projectId)}/equipment-envelopes`],
  ['restore_component', '根据用户要求恢复组件原始几何或原始位姿。其他组件不受影响。', object({ ...rev, componentId: str, restoreGeometry: { type: 'boolean' }, restorePose: { type: 'boolean' } }, ['projectId', 'revision', 'componentId', 'restoreGeometry', 'restorePose']), 'POST', a => `/api/projects/${id(a.projectId)}/components/${id(a.componentId)}/restore`],
  ['organize_assembly', '整理装配语义：组件重命名、创建逻辑分组或取消分组，保持原始几何与位姿不变。必须给依据reason，按稳定ID操作。', object({ ...rev, operations: { type: 'array', items: object({ action: { type: 'string', enum: ['rename', 'group', 'ungroup'] }, componentIds: { type: 'array', items: str }, name: str, groupId: str, reason: str }, ['action', 'reason']) } }, ['projectId', 'revision', 'operations']), 'POST', a => `/api/projects/${id(a.projectId)}/semantics`],
  ['update_pose', '仅在用户明确要求优化或已验证原实体真实碰撞时调整位姿。默认不移动，禁止为了包络假碰撞移动。服务强制要求已有motionConstraints，固定件/超自由度/超范围/产生新碰撞或改变接触都会拒绝。', object({ ...rev, componentId: str, rotation: { type: 'array', minItems: 3, maxItems: 3, items: { type: 'array', minItems: 3, maxItems: 3, items: { type: 'number' } } }, translationMm: { type: 'array', minItems: 3, maxItems: 3, items: { type: 'number' } }, reason: str, authorization: { type: 'string', enum: ['user_requested', 'verified_source_collision'] } }, ['projectId', 'revision', 'componentId', 'rotation', 'translationMm', 'reason', 'authorization']), 'POST', a => `/api/projects/${id(a.projectId)}/components/${id(a.componentId)}/pose`],
  ['read_job', '查询异步作业结果和进度；只有完成状态及输出工件已出现才说明执行成功。', object({ jobId: str }, ['jobId']), 'GET', a => `/api/jobs/${id(a.jobId)}`],
  ['cancel_job', '用户要求取消时提交取消请求；随后查询最终状态，不将请求接受误报为已停止。', object({ jobId: str }, ['jobId']), 'POST', a => `/api/jobs/${id(a.jobId)}/cancel`],
]
function id(value) { if (typeof value !== 'string' || !/^[A-Za-z0-9_.-]{1,160}$/.test(value)) throw new Error('无效对象ID'); return encodeURIComponent(value) }
export const tools = definitions.map(([name, description, inputSchema]) => ({ name: `satellite_${name}`, description, inputSchema }))
export async function callTool(name, args = {}, endpoint = process.env.SATCAD_SERVICE_URL || 'http://127.0.0.1:8787', signal) {
  const def = definitions.find(d => `satellite_${d[0]}` === name)
  if (!def) throw new Error('未知卫星几何工具')
  for (const required of def[2].required) if (args[required] === undefined) throw new Error(`缺少参数 ${required}`)
  if (args.revision !== undefined && (!Number.isSafeInteger(args.revision) || args.revision < 0)) throw new Error('revision必须是非负整数')
  const [, , , method, route] = def
  const body = { ...args }; for (const field of ['projectId', 'documentId', 'componentId', 'planId', 'jobId']) delete body[field]
  if (name === 'satellite_rebuild_equipment_envelopes') body.planId = args.planId
  if (name === 'satellite_submit_metadata' && Array.isArray(body.components)) body.components = body.components.map(component => ({ ...component, origin: component.origin || 'document' }))
  const response = await fetch(`${endpoint.replace(/\/+$/, '')}${route(args)}`, { method, signal: signal || AbortSignal.timeout(110000), headers: { 'content-type': 'application/json', ...(process.env.SATCAD_SERVICE_TOKEN ? { authorization: `Bearer ${process.env.SATCAD_SERVICE_TOKEN}` } : {}) }, ...(method === 'GET' ? {} : { body: JSON.stringify(body) }) })
  const result = await response.json()
  if (!response.ok) throw new Error(`几何服务 ${response.status}: ${JSON.stringify(result)}`)
  if (name === 'satellite_read_project' && args.componentIds !== undefined) {
    if (!Array.isArray(args.componentIds) || args.componentIds.length < 1 || args.componentIds.length > 100) throw new Error('componentIds须包含1至100个组件')
    args.componentIds.forEach(id)
    const wanted = new Set(args.componentIds)
    const components = (result.components || []).filter(component => wanted.has(component.id))
    const missing = [...wanted].filter(value => !components.some(component => component.id === value))
    if (missing.length) throw new Error(`当前项目不存在组件：${missing.join(', ')}`)
    return { id: result.id, name: result.name, revision: result.revision, units: result.units, filtered: true, totalComponentCount: result.components?.length || 0, components, documents: result.documents, checks: result.checks, source: result.source, envelopeRefinement: result.envelopeRefinement, lastExport: result.lastExport }
  }
  return result
}
export async function main() {
  const server = new Server({ name: 'satellite-geometry', version: '0.1.0' }, { capabilities: { tools: {} } })
  server.setRequestHandler(ListToolsRequestSchema, async () => ({ tools }))
  server.setRequestHandler(CallToolRequestSchema, async (request, extra) => {
    try { return { content: [{ type: 'text', text: JSON.stringify(await callTool(request.params.name, request.params.arguments, undefined, extra.signal)) }] } }
    catch (error) { return { isError: true, content: [{ type: 'text', text: error.message }] } }
  })
  await server.connect(new StdioServerTransport())
}
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) await main()
