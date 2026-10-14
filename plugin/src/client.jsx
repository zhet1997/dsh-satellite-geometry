import React, { useEffect, useRef, useState } from 'react'
import { selectionProblem } from './selection-contract.mjs'
import { dispatchDocumentRecovery } from './document-recovery.mjs'
const channel = '/api'
const rpcMethod = operation => `satellite-geometry/${operation}`
const button = { padding: '7px 11px', border: '1px solid #b8c8d7', borderRadius: 7, background: '#f1f7fc', color: '#18374e', cursor: 'pointer', fontSize: 12 }
function SelectionDock({ sessionId, useInput, inputActions, rpc }) {
  const [selection, setSelection] = useState(null)
  const [notice, setNotice] = useState('')
  const input = useInput(s => s)
  const live = useRef({ sessionId, input, inputActions })
  live.current = { sessionId, input, inputActions }
  useEffect(() => {
    setSelection(null); setNotice('')
    return () => { if (window.parent !== window) window.parent.postMessage({ type: 'satellite-geometry:chat-not-ready', sessionId }, location.origin) }
  }, [sessionId])
  useEffect(() => {
    if (window.parent !== window) window.parent.postMessage({ type: 'satellite-geometry:chat-ready', sessionId }, window.location.origin)
    let active = true
    const report = (ok, message) => {
      setNotice(message)
      window.parent.postMessage({ type: 'satellite-geometry:selection-result', ok, message, sessionId }, location.origin)
    }
    const receive = async event => {
      if (event.origin !== location.origin || event.source !== window.parent || window.parent === window) return
      const d = event.data
      if (!d || !['satellite-geometry:selection', 'satellite-geometry:ask-selection', 'satellite-geometry:run-workflow', 'satellite-geometry:bind-skill', 'satellite-geometry:recover-documents'].includes(d.type)) return
      if (d.type === 'satellite-geometry:recover-documents') {
        let message
        try {
          const result = await dispatchDocumentRecovery({rpc,projectId:d.projectId,documentIds:d.documentIds,sessionId,
            isCurrent:()=>active&&live.current.sessionId===sessionId})
          message = result.message
        } catch { message = '原始资料已保存，恢复等待当前会话就绪' }
        if(active) {
          setNotice(message)
          window.parent.postMessage({type:'satellite-geometry:recovery-result',projectId:d.projectId,sessionId,message},location.origin)
        }
        return
      }
      if (d.type === 'satellite-geometry:bind-skill' || d.type === 'satellite-geometry:run-workflow') {
        try {
          const r=await rpc.call(channel,rpcMethod('workflow.bind'),{sessionId,projectId:d.projectId,revision:d.revision,selection:d.selection||[],...(d.skillId?{skillId:d.skillId}:{})})
          if(!r.ok)throw new Error(r.error?.message||'会话绑定失败')
          if(d.type==='satellite-geometry:run-workflow'){
            const result=await rpc.call(channel,'session/prompt',{args:{request:{requestId:crypto.randomUUID(),sessionId,mode:'queue',content:[{type:'text',text:`当前卫星工程 ${d.projectId}，固定Skill指纹 ${r.value.skillFingerprint}。先调用satellite_workflow_context，再按已授权任务自主处理：\n${d.prompt}`}],clientTimeZone:'Asia/Shanghai'}}})
            if(!result.ok)throw new Error(result.error?.message||'任务未送入会话')
            report(true,'建模任务已送入当前 DSH 会话。')
          }else report(true,`已绑定建模 Skill ${r.value.skillFingerprint.slice(0,12)}`)
        }catch(e){report(false,e.message)}
        return
      }
      const asking = d.type === 'satellite-geometry:ask-selection'
      const problem = selectionProblem(d, asking)
      if (problem) { setSelection(null); if (asking) report(false, problem); return }
      setSelection(d)
      if(!asking){
        try{const r=await rpc.call(channel,rpcMethod('workflow.select'),{sessionId,projectId:d.projectId,revision:d.revision,selection:d.selection});if(!r.ok)setNotice(r.error?.message||'上下文同步失败')}
        catch(e){if(active)setNotice(e.message)}
      }
      if (d.type === 'satellite-geometry:ask-selection') {
        setNotice('正在带入选择…')
        try {
          const result = await rpc.call(channel, rpcMethod('selection.snapshot'), { sessionId, projectId: d.projectId, revision: d.revision, selection: d.selection })
          if (!result.ok) throw new Error(result.error?.message || '无法保存组件引用')
          if (!active || live.current.sessionId !== sessionId) return
          const names = result.value.componentNames
          const count = result.value.componentCount ?? names.length
          const displayNames = names.slice(0, 4).join('、') + (count > 4 ? `等 ${count} 个组件` : '')
          const draft = live.current.input.draft || ''
          live.current.inputActions.setDraft(`${draft}${draft ? '\n\n' : ''}所选组件：${displayNames}（几何引用 ${result.value.ref}）\n当前工程 ${d.projectId}，请先读取 satellite_workflow_context 的固定 Skill 与真实文件/方案上下文。\n${d.prompt || '请分析所选组件；默认保留原位置，说明依据，修改当前单机方案。'}`)
          report(true, `已将 ${count} 个组件带入草稿，请编辑问题后发送。`)
        } catch (error) { if (active) report(false, error.message) }
      }
    }
    window.addEventListener('message', receive)
    return () => { active = false; window.removeEventListener('message', receive) }
  }, [sessionId, rpc])
  return <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '5px 10px', fontSize: 12, color: 'var(--dsw-alias-label-secondary)' }}>
    {window.parent === window && <button style={button} onClick={() => window.open('/satellite-geometry/', '_blank', 'noopener')}>打开几何工作台 ↗</button>}
    {selection && <span>所选 {selection.selection.length} 个组件 · 版本 {selection.revision}</span>}
    {notice && <span role="status">{notice}</span>}
  </div>
}
function SettingsCard({ rpc }) {
  const [url, setUrl] = useState('http://127.0.0.1:8787')
  const [status, setStatus] = useState('')
  const [token, setToken] = useState('')
  const [configured, setConfigured] = useState(false)
  useEffect(() => { rpc.call(channel, rpcMethod('settings'), {}).then(r => { if (r.ok) { setUrl(r.value.serviceUrl); setConfigured(r.value.tokenConfigured) } }).catch(e => setStatus(e.message)) }, [rpc])
  const action = async kind => { setStatus('连接中…'); try { const r = await rpc.call(channel, rpcMethod(kind), { serviceUrl: url, ...(kind === 'configure' && token ? { token } : {}) }); if (!r.ok) throw new Error(r.error?.message || '连接失败'); if (token && kind === 'configure') { setConfigured(true); setToken('') }; setStatus(kind === 'configure' ? '地址已保存，MCP 已重新连接。' : `几何服务可用：${r.value.status || '正常'}`) } catch (e) { setStatus(e.message) } }
  return <li style={{ padding: 20, border: '1px solid #c5cdd5', borderRadius: 12, listStyle: 'none' }}><h3>卫星几何工作台</h3><p>使用当前 DSH 模型理解资料与需求，几何计算由独立服务执行。</p><label>几何服务地址 <input value={url} onChange={e => setUrl(e.target.value)} style={{ width: '100%', padding: 8, margin: '8px 0' }} /></label><label>访问令牌（{configured ? '已配置，留空保留' : '本机服务可留空'}）<input type="password" autoComplete="off" value={token} onChange={e => setToken(e.target.value)} style={{ width: '100%', padding: 8, margin: '8px 0' }} /></label><div style={{ display: 'flex', gap: 8 }}><button style={button} onClick={() => action('configure')}>保存并连接</button><button style={button} onClick={() => action('check')}>检查连接</button><button style={button} onClick={() => window.open('/satellite-geometry/', '_blank', 'noopener')}>打开工作台</button></div><p role="status">{status}</p></li>
}
export const inject = ['slots', 'connection']
export function apply(ctx) {
  ctx.slots.inject('conversation.input.dock', () => ctx.slots.register({ name: 'conversation.input.dock', id: 'satellite-geometry-selection', order: -10, inject: () => ({ rpc: ctx.connection.rpc }) }, SelectionDock))
  ctx.slots.inject('settings.plugins.tab', () => ctx.slots.register({ name: 'settings.plugins.tab', id: 'satellite-geometry', label: () => '卫星几何', order: 20, inject: () => ({ rpc: ctx.connection.rpc }) }, SettingsCard))
}
