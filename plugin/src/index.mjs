import fs from 'node:fs'
import path from 'node:path'
import http from 'node:http'
import https from 'node:https'
import os from 'node:os'
import { fileURLToPath } from 'node:url'
import z from '@deepseek-ai/schemastery'
import * as McpClient from '@deepseek-ai/dsh-mcp-client'
import * as SkillFilesystem from '@deepseek-ai/dsh-skill-filesystem'
import { defineTool } from '@deepseek-ai/dsh-tools'
import { SelectionContextStore } from './selection-context.mjs'
import { WorkflowContextStore, nativeJson } from './workflow-context.mjs'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const namespace = 'satellite-geometry'
export const name = namespace
export const inject = ['webServer', 'connection', 'settings', 'credentials', 'tools']
export const Config = z.object({
  serviceUrl: z.string().default('http://127.0.0.1:8787').volatile(),
  connectMcp: z.boolean().default(true).volatile(),
})
export function normalizeEndpoint(value) {
  const url = new URL(value)
  if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.search || url.hash) throw new Error('服务地址必须是 HTTP(S) 地址，不包含用户名、密码或查询参数')
  return url.href.replace(/\/+$/, '')
}
export function sameOrigin(req) {
  const host = req.headers.host
  if (!host) return false
  let hostname
  try { hostname = new URL(`http://${host}`).hostname } catch { return false }
  if (!['localhost', '127.0.0.1', '[::1]'].includes(hostname)) return false
  if (req.headers['sec-fetch-site'] === 'cross-site') return false
  if (!req.headers.origin) return true
  try { return new URL(req.headers.origin).host === host } catch { return false }
}
function json(res, status, value) { res.writeHead(status, { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store' }); res.end(JSON.stringify(value)) }
function staticFile(res, file) {
  if (!fs.existsSync(file) || !fs.statSync(file).isFile()) return json(res, 404, { error: '前端尚未构建。请先构建 web，再构建 plugin。' })
  const mime = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml', '.png': 'image/png', '.wasm': 'application/wasm', '.json': 'application/json' }[path.extname(file)] || 'application/octet-stream'
  res.writeHead(200, { 'content-type': mime, 'cache-control': 'no-cache', 'x-content-type-options': 'nosniff', 'content-security-policy': "frame-ancestors 'self'" }); fs.createReadStream(file).pipe(res)
}
export async function apply(ctx, config) {
  ctx.effect(() => ctx.settings.configure({ auto: false }, ctx.fiber))
  const readConfig = () => ({ serviceUrl: config.serviceUrl.get(), connectMcp: config.connectMcp.get() })
  let effective = readConfig()
  let endpoint = normalizeEndpoint(process.env.SATCAD_SERVICE_URL || effective.serviceUrl)
  const selectionContexts = new SelectionContextStore(path.join(process.env.DSH_HOME || path.join(os.homedir(), '.dsh'), 'satellite-geometry', 'selection-contexts'))
  const workflows = new WorkflowContextStore(path.join(process.env.DSH_HOME || path.join(os.homedir(), '.dsh'), 'satellite-geometry', 'workflow-contexts'))
  const pendingSelections = new Map()
  ctx.tools.register(defineTool({
    name: 'satellite_selection_context',
    description: '读取当前 DSH 会话中 SG- 几何引用的固定 projectId、revision 和组件 ID。最多2000组件，每次最多100个，hasMore为true时用nextOffset继续读取。先解析引用再分批使用 satellite MCP；写操作前读取当前模型版本。',
    parameters: { ref: { type: 'string', required: true, description: '消息中的 SG- 几何引用编号' }, offset: { type: 'integer', description: '从0开始，后续使用上一次nextOffset' }, limit: { type: 'integer', description: '每页1至100，默认100' } },
    output: { schema: { type: 'json' }, render: (_args, value) => [{ type: 'text', text: JSON.stringify(value) }] },
    execute: (args, exec) => selectionContexts.read(args.ref, exec.agent?.id, endpoint, { offset: args.offset, limit: args.limit }),
  }))
  let mcpFiber
  const token = async () => (await ctx.credentials.resolve('SATCAD_SERVICE_TOKEN'))?.value || ''
  const service = async (route, body, signal) => {
    const bearer = await token()
    const response = await fetch(`${endpoint}/api${route}`, { method: body === undefined ? 'GET' : 'POST',
      headers: { 'content-type': 'application/json', ...(bearer ? { authorization: `Bearer ${bearer}` } : {}) },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }), signal: signal || AbortSignal.timeout(15000) })
    const value = await response.json()
    if (!response.ok) throw new Error(typeof value.detail === 'string' ? value.detail : `几何服务返回 ${response.status}`)
    return value
  }
  const bindWorkflow = async (payload, signal) => {
    const previous = await workflows.read(payload.sessionId)
    const project = await service(`/projects/${encodeURIComponent(payload.projectId)}`, undefined, signal)
    const skillId = payload.skillId || previous?.skill.id || (await service('/skills', undefined, signal)).defaultSkillId
    const skill = await service(`/skills/${encodeURIComponent(skillId)}`, undefined, signal)
    if(previous && (previous.skill.id !== skill.id || previous.serviceUrl !== endpoint)) throw new Error('此会话已固定其他 Skill 或服务，请先新建会话')
    const binding = await service(`/projects/${encodeURIComponent(project.id)}/workflow-bindings`, { revision: project.revision, sessionId: payload.sessionId,
      skillId, componentIds: (payload.selection || []).map(c => c.nodeId || c.id) }, signal)
    await workflows.update(payload.sessionId, { serviceUrl: endpoint, projectId: project.id,
      componentIds: (payload.selection || []).map(c => c.nodeId || c.id), skill, revision: project.revision })
    return binding
  }
  ctx.tools.register(defineTool({
    name: 'satellite_workflow_context',
    description: '读取当前 DSH 会话固定的建模 Skill 正文、资源、实际指纹、当前工程/选区/方案/接触及可读资料地址。卫星写操作前必须调用并遵循返回Skill；未绑定可提供projectId绑定默认版本。不同版本使用不同会话。',
    parameters: { projectId: { type: 'string', description: '未选择工程时传项目ID，或明确切换工程；不改变固定Skill' }, offset: { type: 'integer' }, limit: { type: 'integer' } },
    output: { schema: { type: 'json' }, render: (_args, value) => [{ type: 'text', text: JSON.stringify(value) }] },
    execute: async (args, exec) => {
      const sessionId = exec.agent?.id
      if (!sessionId) throw new Error('工具需在 DSH 会话内调用')
      let current = await workflows.read(sessionId)
      if(!current && pendingSelections.has(sessionId)) { await bindWorkflow(pendingSelections.get(sessionId),exec.signal);current=await workflows.read(sessionId) }
      if(args.projectId && args.projectId !== current?.projectId) { await bindWorkflow({sessionId,projectId:args.projectId},exec.signal); current=await workflows.read(sessionId) }
      if (!current || current.serviceUrl !== endpoint) throw new Error('请在工作台选择工程，或传 projectId 绑定当前会话')
      const offset = args.offset ?? 0, limit = args.limit ?? 50
      if(!Number.isSafeInteger(offset)||offset<0||!Number.isSafeInteger(limit)||limit<1||limit>100)throw new Error('limit为1至100，offset为非负整数')
      const project = await service(`/projects/${encodeURIComponent(current.projectId)}/context`, undefined, exec.signal)
      const loaded = await workflows.loaded(sessionId)
      const binding = await service(`/projects/${encodeURIComponent(current.projectId)}/workflow-bindings/${encodeURIComponent(sessionId)}/loaded`, {}, exec.signal)
      const selected = current.componentIds.length ? project.components.filter(c => current.componentIds.includes(c.id)) : project.components
      return nativeJson({ ...project, components: selected.slice(offset, offset+limit).map(c => ({...c, installationRegions: (c.installationRegions || []).map(r=>({...r, faces:(r.faces || []).map(({verticesMm,triangles,...face})=>face)}))})),
        totalComponentCount:selected.length,hasMore:offset+limit<selected.length,nextOffset:offset+limit,
        sessionId, skill: loaded.skill, binding, contextReadUrl: `/api/cad/projects/${project.projectId}/context`,
        instructions: '遵循此会话固定的Skill正文。修改后等待job完成；未知不视为通过。用文档工具读取资料原文。' })
    },
  }))
  ctx.tools.guard(exec => {
    if (!/satellite_/.test(exec.name) || /satellite_(read_|list_|health|selection_context|workflow_context|create_project)/.test(exec.name)) return
    const current = workflows.cached(exec.agent?.id)
    if(!current?.loadedAt || current.serviceUrl !== endpoint) return '请先调用 satellite_workflow_context 读取当前会话固定Skill与工程，再修改'
    if(exec.arguments?.projectId && exec.arguments.projectId !== current.projectId) return '写操作工程与会话上下文不一致；先明确切换工程并读取workflow_context'
  })
  const pendingRecords = new Set()
  ctx.inject(['sessions'], sessionCtx => {
    sessionCtx.on('session/event', (session, event) => {
      if(!['user/message','assistant/message','tool/call','tool/result','turn/end'].includes(event.type))return
      const binding = workflows.cached(session.id)
      if(!binding)return
      const data = event.data || {}, message=data.message || data
      const text = (message.content || []).filter(b=>b.type==='text').map(b=>b.text).join('\n').slice(0,12000)
      const summary = text || (event.type==='tool/call' ? `${data.name}: ${String(data.arguments).slice(0,12000)}` : event.type)
      const pending = service(`/projects/${encodeURIComponent(binding.projectId)}/session-records`, {sessionId:session.id,seq:event.seq??0,
        type:event.type,summary,componentIds:binding.componentIds,skillFingerprint:binding.skill.fingerprint}).catch(e=>ctx.logger.warn(`卫星会话关联记录未保存：${e.message}`))
      pendingRecords.add(pending); pending.finally(()=>pendingRecords.delete(pending))
    }, {global:true})
    sessionCtx.on('session/flush',()=>Promise.allSettled([...pendingRecords]).then(()=>undefined),{global:true})
  })
  const connect = async () => {
    if (mcpFiber) { await mcpFiber.dispose(); mcpFiber = undefined }
    if (effective.connectMcp) {
      mcpFiber = ctx.plugin(McpClient, { serverName: 'satellite_geometry', transport: 'stdio', command: process.execPath, args: [path.join(root, 'mcp/server.mjs')], env: { SATCAD_SERVICE_URL: endpoint, SATCAD_SERVICE_TOKEN: await token() }, toolCallTimeoutMs: 120000, failOnStartupError: true })
      await mcpFiber.await()
    }
  }
  await connect()
  ctx.inject(['skills'], skillCtx => { skillCtx.plugin(SkillFilesystem, { providerName: 'satellite-geometry', includeDefaultRoots: false, customSkillDirs: [path.join(root, 'skills')], watch: false }) })
  const handleRequest = async (operation, payload, signal) => {
    try {
      if (operation === 'selection.snapshot') { const binding=await bindWorkflow(payload,signal); return { ok: true, value: {...await selectionContexts.create(payload, endpoint),skillFingerprint:binding.skillFingerprint} } }
      if (operation === 'workflow.bind') return {ok:true,value:await bindWorkflow(payload,signal)}
      if (operation === 'workflow.select') {
        pendingSelections.set(payload.sessionId,payload)
        if(!await workflows.read(payload.sessionId))return {ok:true,value:{sessionId:payload.sessionId,projectId:payload.projectId,skillId:null}}
        return {ok:true,value:await bindWorkflow(payload,signal)}
      }
      if (operation === 'settings') return { ok: true, value: { serviceUrl: endpoint, tokenConfigured: Boolean(await token()), connectMcp: effective.connectMcp, workbenchUrl: '/satellite-geometry/' } }
      if (operation === 'configure') {
        const serviceUrl = normalizeEndpoint(payload?.serviceUrl)
        if (payload?.clearToken === true) await ctx.credentials.unset('SATCAD_SERVICE_TOKEN')
        else if (typeof payload?.token === 'string' && payload.token.trim()) await ctx.credentials.set('SATCAD_SERVICE_TOKEN', payload.token.trim())
        await ctx.settings.update(namespace, { serviceUrl })
        effective = readConfig(); endpoint = serviceUrl; await connect()
        return { ok: true, value: { serviceUrl, connected: true } }
      }
      if (operation === 'check') {
        const response = await fetch(`${endpoint}/api/health`, { signal: AbortSignal.any([signal, AbortSignal.timeout(6000)]) })
        if (!response.ok) throw new Error(`几何服务返回 ${response.status}`)
        return { ok: true, value: await response.json() }
      }
      throw new Error('未知操作')
    } catch (e) { return { ok: false, error: { code: 'internal', message: e.message } } }
  }
  // Exact routes share DSH's authenticated /api transport. Custom RPC channels
  // in 0.2.0-rc.2 incorrectly access webServer from the connection's owner.
  for (const operation of ['selection.snapshot', 'workflow.bind', 'workflow.select', 'settings', 'configure', 'check']) {
    ctx.connection.fetch.register({
      path: `/api/satellite-geometry/${operation}`, methods: ['POST'], requestBody: 'buffered',
      fetch: async request => {
        let message
        try { message = await request.json() } catch { return new Response('Invalid JSON', { status: 400 }) }
        if (message?.type !== 'client-request' || typeof message.rpcId !== 'string' || message.method !== `${namespace}/${operation}`) return new Response('Invalid RPC envelope', { status: 400 })
        return Response.json({ type: 'server-response', rpcId: message.rpcId, result: await handleRequest(operation, message.payload, request.signal) })
      },
    })
  }
  ctx.webServer.register({ kind: 'prefix', path: '/api/cad', handler: async (req, res) => {
    if (!sameOrigin(req)) return json(res, 403, { error: '仅接受本机同源请求' })
    const rejection = ctx.connection.requestRejection(req)
    if (rejection) return json(res, rejection, { error: '请先登录 DSH' })
    const incoming = new URL(req.url, 'http://localhost')
    const target = new URL(`${endpoint}/api${incoming.pathname.slice('/api/cad'.length)}${incoming.search}`)
    const headers = { ...req.headers, host: target.host }
    delete headers.cookie; delete headers.authorization; delete headers.origin; delete headers.referer
    const bearer = await token()
    if (bearer) headers.authorization = `Bearer ${bearer}`
    const proxy = (target.protocol === 'https:' ? https : http).request(target, { method: req.method, headers }, response => {
      const responseHeaders = { ...response.headers, 'cache-control': 'no-store' }
      delete responseHeaders['set-cookie']; res.writeHead(response.statusCode, responseHeaders); response.pipe(res)
    })
    proxy.on('error', error => { if (!res.headersSent) json(res, 502, { error: `无法连接几何服务：${error.message}` }); else res.destroy() })
    req.on('aborted', () => proxy.destroy()); res.on('close', () => { if (!res.writableEnded) proxy.destroy() }); req.pipe(proxy)
  } })
  ctx.webServer.register({ kind: 'prefix', path: '/satellite-geometry', handler: (req, res) => {
    if (!sameOrigin(req)) return json(res, 403, { error: '仅接受本机同源请求' })
    // Exchange DSH's launch token at our index, retaining its signed cookie and
    // relative clean redirect, so the desktop shortcut opens the workbench.
    const entryUrl = new URL(req.url, 'http://localhost')
    if (entryUrl.pathname === '/satellite-geometry/' && entryUrl.searchParams.has('token')) {
      req.url = `/${entryUrl.search}`
      ctx.connection.authorizeIndex(req, res)
      return
    }
    if (!ctx.connection.authorizeIndex(req, res)) return
    const pathname = decodeURIComponent(new URL(req.url, 'http://localhost').pathname)
    if (pathname === '/satellite-geometry' || pathname === '/satellite-geometry/') return staticFile(res, path.join(root, 'public/workbench.html'))
    if (pathname.startsWith('/satellite-geometry/viewer/')) {
      const base = fs.existsSync(path.join(root, 'public/viewer/index.html')) ? path.join(root, 'public/viewer') : path.resolve(root, '../web/dist')
      const relative = pathname.slice('/satellite-geometry/viewer/'.length) || 'index.html'
      const file = path.resolve(base, relative)
      if (!file.startsWith(base + path.sep)) return json(res, 403, { error: 'invalid path' })
      return staticFile(res, file)
    }
    json(res, 404, { error: 'not found' })
  } })
}
