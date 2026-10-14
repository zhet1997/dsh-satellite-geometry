// Read-only/failed-operation checks against the installed DSH transport.
// The supplied IDs must belong to the independent recovery validation project.
import fs from 'node:fs/promises'
import assert from 'node:assert/strict'

const [projectId,sessionId]=process.argv.slice(2)
assert.ok(/^[a-z0-9_-]+$/i.test(projectId||''),'provide the independent test project ID')
assert.ok(/^[a-z0-9_-]+$/i.test(sessionId||''),'provide the independent test session ID')
const root=new URL('../',import.meta.url)
const base='http://127.0.0.1:3081'
const log=await fs.readFile(new URL('runtime/dsh.stdout.log',root),'utf8')
const launch=log.match(/http:\/\/127\.0\.0\.1:3081\/\?token=[^\s]+/)?.[0]
assert.ok(launch,'local DSH launch token unavailable')
const auth=await fetch(launch.replace('/?token=','/satellite-geometry/?token='),{redirect:'manual'})
assert.equal(auth.status,303)
const cookie=auth.headers.get('set-cookie').split(';')[0]
const health=await (await fetch(base+'/api/cad/health',{headers:{cookie}})).json()
assert.equal(health.version,'0.3.1')
const method='satellite-geometry/documents.recovery'
const response=await fetch(base+'/api/'+method,{method:'POST',headers:{cookie,'content-type':'application/json'},
  body:JSON.stringify({type:'client-request',rpcId:'document-recovery-failure-check',method,payload:{projectId,sessionId,
    documentIds:['missing-document-for-validation'],requestId:'expected-failure-check',action:'claim'}})})
assert.equal(response.status,200)
const envelope=await response.json()
assert.equal(envelope.type,'server-response')
assert.equal(envelope.result.ok,false)
const failure=envelope.result.error
assert.equal(typeof failure.code,'string')
assert.equal(typeof failure.message,'string')
assert.ok(failure.details&&typeof failure.details==='object'&&!Array.isArray(failure.details),
  'DSH 0.2 rc2 requires details on failure envelopes; otherwise the client rejects the response')
const report={serviceVersion:health.version,authenticatedProxy:true,dshFailureEnvelopeValid:true,
  responseCode:failure.code,responseMessage:failure.message,passed:true}
await fs.writeFile(new URL('validation/document-recovery-host.raw.json',root),JSON.stringify(report,null,2)+'\n')
console.log(JSON.stringify(report))
