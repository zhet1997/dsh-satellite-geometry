import test from 'node:test'
import assert from 'node:assert/strict'
import http from 'node:http'
import { fileURLToPath } from 'node:url'
import { Client } from '@modelcontextprotocol/sdk/client/index.js'
import { StdioClientTransport } from '@modelcontextprotocol/sdk/client/stdio.js'
import { callTool } from '../mcp/server.mjs'

test('real stdio MCP discovers tools and preserves revision/source payloads across HTTP', async () => {
  const received = []
  const service = http.createServer(async (req, res) => {
    let raw = ''; for await (const chunk of req) raw += chunk
    received.push({ method: req.method, url: req.url, authorization: req.headers.authorization, body: raw ? JSON.parse(raw) : null })
    res.setHeader('content-type', 'application/json')
    if (req.url === '/api/projects/missing') { res.statusCode = 404; res.end(JSON.stringify({ detail: 'project not found' })); return }
    res.end(JSON.stringify({ id: 'p1', projectId: 'p1', revision: 8, status: 'ok', components: [{ id: 'c1', metadata: { powerW: 12.5 } }, { id: 'c2', metadata: {} }], lastExport: { stepReadable: true, stepReadbackValid: false, sourceTopologyValid: false } }))
  })
  await new Promise(resolve => service.listen(0, '127.0.0.1', resolve))
  const client = new Client({ name: 'satellite-smoke', version: '1' }, { capabilities: {} })
  const transport = new StdioClientTransport({ command: process.execPath, args: [fileURLToPath(new URL('../mcp/server.mjs', import.meta.url))], env: { SATCAD_SERVICE_URL: `http://127.0.0.1:${service.address().port}`, SATCAD_SERVICE_TOKEN: 'synthetic-test-token' }, stderr: 'pipe' })
  try {
    await client.connect(transport)
    const listing = await client.listTools()
    assert.equal(listing.tools.length, 16)
    assert.ok(listing.tools.some(t => t.name === 'satellite_read_document'))
    const args = { projectId: 'p1', revision: 7, components: [{ id: 'c1', powerW: 12.5, sources: [{ documentId: 'd1', quote: '额定功耗 12.5 W', field: 'powerW' }] }] }
    const result = await client.callTool({ name: 'satellite_submit_metadata', arguments: args })
    assert.ok(!result.isError)
    assert.equal(received.at(-1).url, '/api/projects/p1/metadata')
    assert.equal(received.at(-1).body.revision, 7)
    assert.equal(received.at(-1).authorization, 'Bearer synthetic-test-token')
    assert.deepEqual(received.at(-1).body.components, args.components.map(component => ({ ...component, origin: 'document' })))
    const error = await client.callTool({ name: 'satellite_read_project', arguments: { projectId: 'missing' } })
    assert.equal(error.isError, true)
    assert.match(error.content[0].text, /404/)
    const traversal = await client.callTool({ name: 'satellite_read_project', arguments: { projectId: '../secret' } })
    assert.equal(traversal.isError, true)
    assert.equal(received.length, 2)
    const selected = await client.callTool({ name: 'satellite_read_project', arguments: { projectId: 'p1', componentIds: ['c1'] } })
    const value = JSON.parse(selected.content[0].text)
    assert.equal(value.revision, 8)
    assert.equal(value.totalComponentCount, 2)
    assert.equal(value.filtered, true)
    assert.deepEqual(value.components, [{ id: 'c1', metadata: { powerW: 12.5 } }])
    assert.deepEqual(value.lastExport, { stepReadable: true, stepReadbackValid: false, sourceTopologyValid: false })
    await client.callTool({ name: 'satellite_rebuild_equipment_envelopes', arguments: { projectId: 'p1', revision: 8, planId: 'plan8', authorization: 'user_requested_equivalent_envelopes', thermalContacts: 'separately_defined', reason: 'explicit equivalent geometry choice' } })
    assert.equal(received.at(-1).url, '/api/projects/p1/equipment-envelopes')
    assert.equal(received.at(-1).body.planId, 'plan8')
    assert.equal(received.at(-1).body.thermalContacts, 'separately_defined')
  } finally { await client.close(); await new Promise(resolve => service.close(resolve)) }
})

test('stale/invalid identity input rejected before making HTTP requests', async () => {
  await assert.rejects(callTool('satellite_check_project', { projectId: 'p', revision: -1 }), /revision/)
  await assert.rejects(callTool('satellite_apply_plan', { projectId: 'p', revision: 1 }), /缺少参数/)
})
