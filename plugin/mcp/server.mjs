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
  ['read_document', '读取资料原文、来源、读取状态和diagnostics.availableRecoveryMethods；待恢复或无法读取不等于资料已理解，缺失参数保持未知。抽取属性必须引用原文。', object({ ...project, documentId: str }, ['projectId', 'documentId']), 'GET', a => `/api/projects/${id(a.projectId)}/documents/${id(a.documentId)}`],
  ['recover_document', '针对已安排到本会话的资料执行受控恢复：retry重新兼容读取，xlsx_xml/docx_xml读取原文件XML，mark_unreadable记录无法恢复的原因。每次先读取最新revision，原文件不修改；自动最多两次尝试。XML数值未解释日期、单位或格式，禁止补造原文及物理参数。', object({ ...rev, documentId:str, sessionId:str, method:{type:'string',enum:['retry','xlsx_xml','docx_xml','mark_unreadable']},reason:{type:'string',maxLength:4000} }, ['projectId','revision','documentId','sessionId','method','reason']), 'POST', a => `/api/projects/${id(a.projectId)}/documents/${id(a.documentId)}/recover`],
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
const auditContext = object({ sessionId: str, skillFingerprint: str, selectionRef: str, feedback: str })
const vector = { type: 'array', minItems: 3, maxItems: 3, items: { type: 'number' } }
const part = object({ id: str, name: str, kind: { type: 'string', enum: ['source', 'box', 'cylinder'] }, centerMm: vector, sizeMm: vector,
  radiusMm: { type: 'number', exclusiveMinimum: 0 }, heightMm: { type: 'number', exclusiveMinimum: 0 }, axis: vector }, ['id', 'name', 'kind'])
const thermal = object({ thicknessMm: { type: ['number', 'null'] }, material: { type: ['string', 'null'] }, massKg: { type: ['number', 'null'] },
  specificHeatJPerKgK: { type: ['number', 'null'] }, conductivityWPerMK: { type: ['number', 'null'] }, powerW: { type: ['number', 'null'] } })
const region = object({ id: str, name: str, partId: str, selector: { type: 'string', enum: ['xmin', 'xmax', 'ymin', 'ymax', 'zmin', 'zmax', 'lateral', 'all'] } }, ['id', 'name', 'partId', 'selector'])
const recipe = object({ schemaVersion: { type: 'integer', const: 1 }, representation: { type: 'string', enum: ['source', 'solid', 'surface_shell'] },
  parts: { type: 'array', minItems: 1, items: part }, thermal, regions: { type: 'array', items: region }, dimensionBasis: str,
  notes: { type: 'string' }, sources: { type: 'array', items: source }, legacyCandidateFile: { type: ['string', 'null'] } }, ['representation', 'parts', 'dimensionBasis'])
const side = object({ componentId: str, regionId: { type: ['string', 'null'] } }, ['componentId'])
const contact = object({ id: str, a: side, b: side, status: { type: 'string', enum: ['candidate', 'confirmed', 'needs_review', 'excluded'] },
  origin: { type: 'string', enum: ['manual', 'document', 'geometry'] }, areaMm2: { type: ['number', 'null'] }, conductanceWPerK: { type: ['number', 'null'] }, evidence: str, sources: { type: 'array', items: source } }, ['id', 'a', 'b', 'evidence'])
definitions.push(
  ['read_recipes', '读取单机可重建方案、源局部尺寸、安装区域及副本。使用稳定组件ID，单位Z-up毫米。', object(project, ['projectId']), 'GET', a => `/api/projects/${id(a.projectId)}/recipes`],
  ['rebuild_recipes', '按工程师要求直接修改并重建当前单机方案。可组合盒体与圆柱；surface_shell输出面、不输出实体，热参数另存且未知填null。保持当前位姿，关联接触标为待复核；等待jobId完成。context关联会话、SG引用和工程师意见，不实时修改Skill。', object({ ...rev, changes: { type: 'array', minItems: 1, items: object({ componentId: str, recipe, reason: str }, ['componentId', 'recipe', 'reason']) }, context: auditContext }, ['projectId', 'revision', 'changes']), 'POST', a => `/api/projects/${id(a.projectId)}/recipes/rebuild`],
  ['save_recipe_copy', '保存当前已应用的单机方案为命名副本，共用源几何。保存不表示认证工程正确。', object({ ...rev, componentId: str, name: str, context: auditContext }, ['projectId', 'revision', 'componentId', 'name']), 'POST', a => `/api/projects/${id(a.projectId)}/components/${id(a.componentId)}/recipe-copies`],
  ['load_recipe_copy', '载入命名单机方案副本并重建，保持当前位姿。返回jobId，关联安装接触需复核。', object({ ...rev, componentId: str, copyId: str, context: auditContext }, ['projectId', 'revision', 'componentId', 'copyId']), 'POST', a => `/api/projects/${id(a.projectId)}/components/${id(a.componentId)}/recipe-copies/${id(a.copyId)}/load`],
  ['read_contacts', '读取热接触清单、区域/源贴面证据和完整性。candidate/未知不能认作确认或无接触。', object(project, ['projectId']), 'GET', a => `/api/projects/${id(a.projectId)}/thermal-contacts`],
  ['update_contacts', '维护安装/热接触双方区域、面积、状态和资料依据。confirmed必须明确两个有效区域；仅几何证据不能确认热连接；未知导通保持null。', object({ ...rev, contacts: { type: 'array', minItems: 1, items: contact }, context: auditContext }, ['projectId', 'revision', 'contacts']), 'POST', a => `/api/projects/${id(a.projectId)}/thermal-contacts`],
  ['identify_equipment', '按配套文件可靠匹配单机并提交简洁中文名称及两层工程分类；保留源名称与稳定ID。不确定身份保持待识别，不编造设备名。', object({ ...rev, components: { type: 'array', items: object({ componentId: str, displayName: str, engineeringGroup: { type: 'string', enum: ['结构', '单机', '附件', '待分类'] }, nameStatus: { type: 'string', enum: ['identified', 'candidate', 'unidentified'], description: '可靠匹配才 identified；有冲突用 candidate；无依据用 unidentified，省略默认 candidate。' }, basis: str, sources: { type: 'array', items: source } }, ['componentId', 'displayName', 'basis']) }, context: auditContext }, ['projectId', 'revision', 'components']), 'POST', a => `/api/projects/${id(a.projectId)}/identities`],
  ['read_evidence', '返回当前方案、测量、Skill绑定/实际读取指纹、检查未知项、接触、反馈和导出地址，供外部测试系统评分。插件不评分。', object(project, ['projectId']), 'GET', a => `/api/projects/${id(a.projectId)}/evidence`],
  ['record_feedback', '仅保存工程师经验、对象/会话/引用和修改意见，供以后集中升级Skill；不实时改写Skill。', object({ ...rev, componentIds: { type: 'array', items: str }, reason: str, context: auditContext }, ['projectId', 'revision', 'reason']), 'POST', a => `/api/projects/${id(a.projectId)}/feedback`],
)
function id(value) { if (typeof value !== 'string' || !/^[A-Za-z0-9_.-]{1,160}$/.test(value)) throw new Error('无效对象ID'); return encodeURIComponent(value) }
export const tools = definitions.map(([name, description, inputSchema]) => ({ name: `satellite_${name}`, description, inputSchema }))
export async function callTool(name, args = {}, endpoint = process.env.SATCAD_SERVICE_URL || 'http://127.0.0.1:8787', signal) {
  const def = definitions.find(d => `satellite_${d[0]}` === name)
  if (!def) throw new Error('未知卫星几何工具')
  for (const required of def[2].required) if (args[required] === undefined) throw new Error(`缺少参数 ${required}`)
  if (args.revision !== undefined && (!Number.isSafeInteger(args.revision) || args.revision < 0)) throw new Error('revision必须是非负整数')
  const [, , , method, route] = def
  const body = { ...args }; for (const field of ['projectId', 'documentId', 'componentId', 'planId', 'jobId', 'copyId']) delete body[field]
  if (name === 'satellite_rebuild_equipment_envelopes') body.planId = args.planId
  if (name === 'satellite_submit_metadata' && Array.isArray(body.components)) body.components = body.components.map(component => ({ ...component, origin: component.origin || 'document' }))
  const response = await fetch(`${endpoint.replace(/\/+$/, '')}${route(args)}`, { method, signal: signal || AbortSignal.timeout(110000), headers: { 'content-type': 'application/json', ...(process.env.SATCAD_SERVICE_TOKEN ? { authorization: `Bearer ${process.env.SATCAD_SERVICE_TOKEN}` } : {}) }, ...(method === 'GET' ? {} : { body: JSON.stringify(body) }) })
  let result
  try { result = await response.json() }
  catch { throw new Error(`服务返回了非标准响应（${response.status}），请查看运行日志`) }
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
  const server = new Server({ name: 'satellite-geometry', version: '0.3.1' }, { capabilities: { tools: {} } })
  server.setRequestHandler(ListToolsRequestSchema, async () => ({ tools }))
  server.setRequestHandler(CallToolRequestSchema, async (request, extra) => {
    try { return { content: [{ type: 'text', text: JSON.stringify(await callTool(request.params.name, request.params.arguments, undefined, extra.signal)) }] } }
    catch (error) { return { isError: true, content: [{ type: 'text', text: error.message }] } }
  })
  await server.connect(new StdioServerTransport())
}
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) await main()
