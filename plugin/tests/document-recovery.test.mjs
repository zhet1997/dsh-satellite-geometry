import test from 'node:test'
import assert from 'node:assert/strict'
import { dispatchDocumentRecovery } from '../src/document-recovery.mjs'

function fixture() {
  const calls = [], claimed = new Set(), state = new Map()
  const rpc = { call: async (_channel, method, body) => {
    calls.push({method,body})
    if (method === 'session/prompt') return {ok:true}
    if (body.action !== 'claim') { state.set(body.requestId,body.action); return {ok:true,value:{}} }
    const documents = body.documentIds.filter(id=>!claimed.has(id)).map(id=>{
      claimed.add(id); return {id,name:'问题表.xlsx',extractionStatus:'needs_recovery'}
    })
    state.set(body.requestId,'claim')
    return {ok:true,value:{documents}}
  } }
  return {rpc,calls,state}
}

test('concurrent tabs and reloads queue one recovery prompt after the durable claim', async () => {
  const {rpc,calls}=fixture()
  const args={rpc,projectId:'p1',sessionId:'s1',documentIds:['d1']}
  const results=await Promise.all([dispatchDocumentRecovery({...args,newRequestId:()=> 'request-a'}),dispatchDocumentRecovery({...args,newRequestId:()=> 'request-b'})])
  await dispatchDocumentRecovery({...args,newRequestId:()=> 'after-reload'})
  assert.equal(results.reduce((sum,result)=>sum+result.queued,0),1)
  const prompts=calls.filter(call=>call.method==='session/prompt')
  assert.equal(prompts.length,1)
  assert.equal(prompts[0].body.args.request.sessionId,'s1')
  assert.equal(prompts[0].body.args.request.requestId,'request-a')
  assert.match(prompts[0].body.args.request.content[0].text,/satellite_recover_document/)
  assert.match(prompts[0].body.args.request.content[0].text,/不修改几何/)
  assert.equal(calls.find(call=>call.body.action==='submitted').body.requestId,'request-a')
})

test('a switched session cannot receive the pending recovery', async () => {
  const {rpc,calls,state}=fixture()
  const result=await dispatchDocumentRecovery({rpc,projectId:'p1',sessionId:'s1',documentIds:['d1'],isCurrent:()=>false,newRequestId:()=> 'switched'})
  assert.equal(result.queued,0)
  assert.equal(calls.filter(call=>call.method==='session/prompt').length,0)
  assert.equal(state.get('switched'),'dispatch_failed')
})

test('an uncertain prompt delivery is recorded and never automatically retried', async () => {
  const {rpc,calls,state}=fixture()
  const original=rpc.call
  rpc.call=async (...args)=>{
    if(args[1]==='session/prompt') {calls.push({method:args[1],body:args[2]});throw new Error('connection closed')}
    return original(...args)
  }
  const args={rpc,projectId:'p1',sessionId:'s1',documentIds:['d1']}
  const result=await dispatchDocumentRecovery({...args,newRequestId:()=> 'uncertain'})
  await dispatchDocumentRecovery({...args,newRequestId:()=> 'second-request'})
  assert.equal(result.queued,0)
  assert.equal(state.get('uncertain'),'dispatch_failed')
  assert.equal(calls.filter(call=>call.method==='session/prompt').length,1)
})
