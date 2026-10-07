import fs from 'node:fs/promises'
import assert from 'node:assert/strict'
const root = new URL('../', import.meta.url)
const base = 'http://127.0.0.1:3081'
const log = await fs.readFile(new URL('runtime/dsh.stdout.log', root), 'utf8')
const launch = log.match(/http:\/\/127\.0\.0\.1:3081\/\?token=[^\s]+/)?.[0]
assert.ok(launch, 'DSH launch URL missing')
const auth = await fetch(launch.replace('/?token=', '/satellite-geometry/?token='), { redirect: 'manual' })
assert.equal(auth.status, 303)
const cookie = auth.headers.get('set-cookie').split(';')[0]
const get = async path => { const r = await fetch(base + path, { headers: { cookie } }); assert.equal(r.status, 200, path); return r }
const rpc = async (operation, payload = {}) => {
  const method = `satellite-geometry/${operation}`
  const r = await fetch(`${base}/api/${method}`, { method: 'POST', headers: { cookie, 'content-type': 'application/json' }, body: JSON.stringify({ type: 'client-request', rpcId: 'upgrade-validation', method, payload }) })
  assert.equal(r.status, 200)
  const body = await r.json(); assert.equal(body.result.ok, true, JSON.stringify(body)); return body.result.value
}
for (const path of ['/satellite-geometry/', '/api/cad/projects', '/api/satellite-geometry/settings']) {
  assert.equal((await fetch(base + path, { method: path.endsWith('/settings') ? 'POST' : 'GET' })).status, 401, `unauthenticated ${path}`)
}
assert.equal((await fetch(base + '/api/cad/projects', { headers: { cookie, origin: 'https://example.com' } })).status, 403)
await get('/satellite-geometry/')
await get('/satellite-geometry/viewer/')
const health = await (await get('/api/cad/health')).json()
assert.equal(health.status, 'ok')
const before = await rpc('settings')
await rpc('configure', { serviceUrl: before.serviceUrl })
assert.equal((await rpc('settings')).serviceUrl, before.serviceUrl)
assert.equal((await rpc('check')).status, 'ok')
const listing = await (await get('/api/cad/projects')).json()
const projects = Array.isArray(listing) ? listing : listing.projects
assert.ok(projects.length >= 8)
const project = await (await get('/api/cad/projects/ea3a894c85e243edaab17500b65a0af7')).json()
assert.ok(project.components.length > 0)
const snapshot = await rpc('selection.snapshot', { sessionId: 'upgrade-validation', projectId: project.id || project.projectId, revision: project.revision, selection: [{ nodeId: project.components[0].id, name: project.components[0].name }] })
assert.equal(snapshot.componentCount, 1)
const evidence = { date: new Date().toISOString(), dshVersion: '0.2.0-rc.2', pluginVersion: '0.2.0', workbenchLaunchTokenExchange: true, unauthenticatedRequestsRejected: true, crossOriginRejected: true, settingsReadWriteAndMcpReconnect: true, geometryHealth: health.status, projectCount: projects.length, selectionSnapshotCreated: true }
await fs.writeFile(new URL('validation/dsh-upgrade-0.2.0.json', root), JSON.stringify(evidence, null, 2) + '\n')
console.log(JSON.stringify(evidence, null, 2))
