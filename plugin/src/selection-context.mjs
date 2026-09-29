import fs from 'node:fs/promises'
import path from 'node:path'
import { randomBytes } from 'node:crypto'
import { selectionProblem, SELECTION_PAGE_SIZE } from './selection-contract.mjs'

const identity = /^[A-Za-z0-9_.-]{1,160}$/
function validId(value) {
  if (typeof value !== 'string' || !identity.test(value)) throw new Error('无效的项目、会话或组件标识')
  return value
}
const label = value => String(value || '').replace(/[\r\n\t]/g, ' ').slice(0, 120)

// References are write-once, session-bound snapshots. Never follow the live selection.
export class SelectionContextStore {
  constructor(directory) { this.directory = directory }
  async create(payload, serviceUrl) {
    const sessionId = validId(payload?.sessionId)
    const projectId = validId(payload?.projectId)
    if (!Number.isSafeInteger(payload?.revision) || payload.revision < 0) throw new Error('模型版本无效')
    const problem = selectionProblem(payload, true)
    if (problem) throw new Error(problem)
    const components = payload.selection.map(item => ({ id: validId(item.nodeId || item.id), name: label(item.name) }))
    const snapshot = { sessionId, serviceUrl, projectId, revision: payload.revision, components, createdAt: new Date().toISOString() }
    await fs.mkdir(this.directory, { recursive: true })
    for (let attempt = 0; attempt < 3; attempt++) {
      const ref = `SG-${randomBytes(6).toString('hex').toUpperCase()}`
      try {
        await fs.writeFile(path.join(this.directory, `${ref}.json`), JSON.stringify({ ref, ...snapshot }), { flag: 'wx', mode: 0o600 })
        return { ref, componentNames: components.slice(0, 4).map(item => item.name || item.id), componentCount: components.length, revision: snapshot.revision }
      } catch (error) { if (error.code !== 'EEXIST') throw error }
    }
    throw new Error('无法保存选择引用，请重试')
  }
  async read(ref, sessionId, serviceUrl, { offset = 0, limit = SELECTION_PAGE_SIZE } = {}) {
    if (!Number.isSafeInteger(offset) || offset < 0 || !Number.isSafeInteger(limit) || limit < 1 || limit > SELECTION_PAGE_SIZE) throw new Error('引用读取 offset 须为非负整数，limit 须为 1 至 100')
    if (typeof ref !== 'string' || !/^SG-[A-F0-9]{12}$/.test(ref)) throw new Error('无效的几何引用')
    const snapshot = JSON.parse(await fs.readFile(path.join(this.directory, `${ref}.json`), 'utf8'))
    if (!sessionId || snapshot.sessionId !== sessionId) throw new Error('该几何引用属于其他会话，请在当前会话重新带入选择')
    if (snapshot.serviceUrl !== serviceUrl) throw new Error('几何服务地址已改变，请重新带入选择以确认对象')
    const { serviceUrl: _serviceUrl, sessionId: _sessionId, components, ...context } = snapshot
    const hasMore = offset + limit < components.length
    return { ...context, components: components.slice(offset, offset + limit), componentCount: components.length, offset, limit, hasMore, ...(hasMore ? { nextOffset: offset + limit } : {}) }
  }
}
