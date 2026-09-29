import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import { SelectionContextStore } from '../src/selection-context.mjs'
import { selectionProblem, MAX_SELECTION_COMPONENTS } from '../src/selection-contract.mjs'

test('selection references survive restart, remain fixed and reject another session or service', async () => {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'satcad-reference-'))
  try {
    const store = new SelectionContextStore(dir)
    const input = { sessionId: 'session-a', projectId: 'p1', revision: 5, selection: [{ nodeId: 'n1', name: '设备' }] }
    const reference = await store.create(input, 'http://service-a')
    input.revision = 6; input.selection[0].nodeId = 'n2'
    const restored = new SelectionContextStore(dir)
    const snapshot = await restored.read(reference.ref, 'session-a', 'http://service-a')
    assert.equal(snapshot.revision, 5)
    assert.equal(snapshot.components[0].id, 'n1')
    assert.equal(snapshot.serviceUrl, undefined)
    await assert.rejects(restored.read(reference.ref, 'session-b', 'http://service-a'), /其他会话/)
    await assert.rejects(restored.read(reference.ref, 'session-a', 'http://service-b'), /服务地址/)
    await assert.rejects(restored.read('../outside', 'session-a', 'http://service-a'), /无效/)
    const second = await store.create(input, 'http://service-a')
    assert.notEqual(reference.ref, second.ref)
    assert.equal((await restored.read(reference.ref, 'session-a', 'http://service-a')).revision, 5)
  } finally { await fs.rm(dir, { recursive: true, force: true }) }
})

test('a 194-component selection reaches the draft and resolves all immutable IDs in pages', async () => {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'satcad-large-reference-'))
  try {
    const store = new SelectionContextStore(dir)
    const input = { sessionId: 'large-session', projectId: 'real-size-project', revision: 9, selection: Array.from({ length: 194 }, (_, i) => ({ nodeId: `N${String(i + 1).padStart(5, '0')}`, name: `组件 ${i + 1}` })) }
    assert.equal(selectionProblem(input, true), '')
    const originalIds = input.selection.map(item => item.nodeId)
    const reference = await store.create(input, 'http://service')
    assert.equal(reference.componentCount, 194)
    assert.deepEqual(reference.componentNames, ['组件 1', '组件 2', '组件 3', '组件 4'])
    input.selection = []; input.revision = 10
    const first = await store.read(reference.ref, 'large-session', 'http://service')
    assert.equal(first.components.length, 100)
    assert.equal(first.componentCount, 194)
    assert.equal(first.revision, 9)
    assert.equal(first.hasMore, true)
    assert.equal(first.nextOffset, 100)
    const last = await new SelectionContextStore(dir).read(reference.ref, 'large-session', 'http://service', { offset: first.nextOffset })
    assert.equal(last.components.length, 94)
    assert.equal(last.hasMore, false)
    assert.equal(last.nextOffset, undefined)
    assert.deepEqual([...first.components, ...last.components].map(item => item.id), originalIds)
    await assert.rejects(store.read(reference.ref, 'large-session', 'http://service', { limit: 101 }), /1 至 100/)
    input.selection = Array.from({ length: MAX_SELECTION_COMPONENTS }, (_, i) => ({ nodeId: `N${i}`, name: '组件' }))
    assert.equal(selectionProblem(input, true), '')
    const maximum = await store.create(input, 'http://service')
    assert.equal(maximum.componentCount, 2000)
    input.selection.push({ nodeId: 'overflow', name: '越界' })
    assert.match(selectionProblem(input, true), /2000/)
    await assert.rejects(store.create(input, 'http://service'), /2000/)
    input.selection = []
    assert.match(selectionProblem(input, true), /项目名称/)
    await assert.rejects(store.create(input, 'http://service'), /先选择组件/)
  } finally { await fs.rm(dir, { recursive: true, force: true }) }
})
