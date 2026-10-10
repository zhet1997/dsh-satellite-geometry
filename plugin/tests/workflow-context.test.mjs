import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import { WorkflowContextStore, nativeJson } from '../src/workflow-context.mjs'
import { snapshotJsonValue } from '@deepseek-ai/dsh-util-values'

test('CAD signed-zero normals cross the actual DSH durable tool boundary', () => {
  const context={pose:{translationMm:[0,-0,4]},regions:[{normal:[-0,0,-1]}],skill:{content:'建模规则',resources:{}}}
  assert.equal(snapshotJsonValue(context),undefined)
  const output=nativeJson(context)
  assert.deepEqual(snapshotJsonValue(output),output)
  assert.equal(Object.is(output.regions[0].normal[0],-0),false)
  assert.throws(()=>nativeJson({...context,missing:undefined}),/缺失/)
})

test('session skill pins survive restart, reject replacement and remain independent', async () => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(),'satellite-workflow-'))
  try {
    let store = new WorkflowContextStore(directory)
    const first={serviceUrl:'http://127.0.0.1:8787',projectId:'p1',componentIds:['c1'],skill:{id:'skill-a',fingerprint:'aaa',content:'圆柱加底座',resources:{'rules.md':'不猜热容'}}}
    await store.update('session-a',first)
    first.skill.content='changed by caller'
    assert.equal((await store.read('session-a')).skill.content,'圆柱加底座')
    await store.update('session-b',{...first,skill:{id:'skill-b',fingerprint:'bbb',content:'面壳'}})
    await store.loaded('session-a')
    store=new WorkflowContextStore(directory)
    const loaded=await store.read('session-a')
    assert.ok(loaded.loadedAt)
    assert.equal(loaded.skill.content,'圆柱加底座')
    await assert.rejects(store.update('session-a',{...first,skill:{id:'skill-b',fingerprint:'bbb'}}),/新建/)
    await assert.rejects(store.update('session-a',{...first,serviceUrl:'http://another-service'}),/新建/)
    await store.update('session-a',{...loaded,componentIds:['c2'],projectId:'p2'})
    assert.equal((await store.read('session-a')).skill.fingerprint,'aaa')
    assert.equal((await store.read('session-b')).skill.fingerprint,'bbb')
    assert.deepEqual((await store.read('session-a')).componentIds,['c2'])
  } finally { await fs.rm(directory,{recursive:true,force:true}) }
})
