import fs from 'node:fs/promises'
import path from 'node:path'
import { randomBytes } from 'node:crypto'

const validId = value => {
  if (typeof value !== 'string' || !/^[A-Za-z0-9_-]{1,200}$/.test(value)) throw new Error('无效会话或工程 ID')
  return value
}

/** OCCT emits -0.0 normals. DSH's durable JSON boundary requires canonical 0. */
export function nativeJson(value) {
  return JSON.parse(JSON.stringify(value, (_key, item) => {
    if (item === undefined || (typeof item === 'number' && !Number.isFinite(item))) throw new Error('工程上下文包含缺失或非有限字段')
    return item
  }))
}

/** Durable session pins. A new selection never changes the frozen workflow. */
export class WorkflowContextStore {
  constructor(directory) { this.directory = directory; this.cache = new Map(); this.chains = new Map() }
  file(id) { return path.join(this.directory, `${validId(id)}.json`) }
  async read(id) {
    if (this.cache.has(id)) return this.cache.get(id)
    try { const value = JSON.parse(await fs.readFile(this.file(id), 'utf8')); this.cache.set(id, value); return value }
    catch (e) { if (e.code === 'ENOENT') return null; throw e }
  }
  async update(sessionId, value) {
    validId(sessionId)
    const pending = (this.chains.get(sessionId) || Promise.resolve()).catch(() => {}).then(async () => {
      const previous = await this.read(sessionId)
      if (previous && (previous.serviceUrl !== value.serviceUrl || previous.skill.id !== value.skill.id || previous.skill.fingerprint !== value.skill.fingerprint)) throw new Error('此会话已固定其他 Skill 或服务，请新建 DSH 会话')
      const result = structuredClone({ ...value, skill: previous?.skill || value.skill, sessionId, boundAt: previous?.boundAt || new Date().toISOString(), loadedAt: value.loadedAt || previous?.loadedAt || null })
      await fs.mkdir(this.directory, { recursive: true })
      const temp = `${this.file(sessionId)}.${randomBytes(5).toString('hex')}.tmp`
      await fs.writeFile(temp, JSON.stringify(result), { mode: 0o600 })
      await fs.rename(temp, this.file(sessionId)); this.cache.set(sessionId, result)
      return result
    })
    this.chains.set(sessionId, pending)
    try { return await pending } finally { if (this.chains.get(sessionId) === pending) this.chains.delete(sessionId) }
  }
  async loaded(sessionId) {
    const current = await this.read(sessionId)
    if (!current) throw new Error('当前会话尚未绑定几何工程')
    return this.update(sessionId, {...current,loadedAt:new Date().toISOString()})
  }
  cached(sessionId) { return this.cache.get(sessionId) }
}
