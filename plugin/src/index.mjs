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
  ctx.tools.register(defineTool({
    name: 'satellite_selection_context',
    description: '读取当前 DSH 会话中 SG- 几何引用的固定 projectId、revision 和组件 ID。最多2000组件，每次最多100个，hasMore为true时用nextOffset继续读取。先解析引用再分批使用 satellite MCP；写操作前读取当前模型版本。',
    parameters: { ref: { type: 'string', required: true, description: '消息中的 SG- 几何引用编号' }, offset: { type: 'integer', description: '从0开始，后续使用上一次nextOffset' }, limit: { type: 'integer', description: '每页1至100，默认100' } },
    output: { schema: { type: 'json' }, render: (_args, value) => [{ type: 'text', text: JSON.stringify(value) }] },
    execute: (args, exec) => selectionContexts.read(args.ref, exec.agent?.id, endpoint, { offset: args.offset, limit: args.limit }),
  }))
  let mcpFiber
  const token = async () => (await ctx.credentials.resolve('SATCAD_SERVICE_TOKEN'))?.value || ''
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
      if (operation === 'selection.snapshot') return { ok: true, value: await selectionContexts.create(payload, endpoint) }
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
  for (const operation of ['selection.snapshot', 'settings', 'configure', 'check']) {
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
