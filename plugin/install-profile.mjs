import fs from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
const plugin = path.dirname(fileURLToPath(import.meta.url))
const home = process.env.DSH_HOME || path.join(os.homedir(), '.dsh')
const profile = path.join(home, 'profiles', 'satellite-geometry')
const manifestPath = path.join(profile, 'package.json')
const link = path.join(profile, 'node_modules', '@lbk', 'dsh-satellite-geometry')
let existing
try { existing = JSON.parse(await fs.readFile(manifestPath, 'utf8')) } catch (error) { if (error.code !== 'ENOENT') throw error }
if (existing && !existing.dsh?.profile?.bundles?.includes('@lbk/dsh-satellite-geometry')) throw new Error('同名profile已有其他配置；未覆盖。请另选名称或人工核对。')
let linked = false
try {
  const current = path.resolve(await fs.realpath(link))
  const expected = path.resolve(plugin)
  if ((process.platform === 'win32' ? current.toLowerCase() !== expected.toLowerCase() : current !== expected)) throw new Error('既有插件链接指向其他路径，未覆盖。')
  linked = true
} catch (error) { if (error.code !== 'ENOENT') throw error }
await fs.mkdir(path.join(profile, 'node_modules', '@lbk'), { recursive: true })
const manifest = existing || { name: 'dsh-profile-satellite-geometry', private: true, dependencies: {}, dsh: { profile: { bundles: ['@deepseek-ai/dsh-base', '@deepseek-ai/dsh-web-app', '@lbk/dsh-satellite-geometry'] } } }
manifest.dependencies ||= {}
manifest.dependencies['@lbk/dsh-satellite-geometry'] = `link:${plugin.replaceAll('\\', '/')}`
await fs.writeFile(manifestPath, JSON.stringify(manifest, null, 2) + '\n')
try { await fs.writeFile(path.join(profile, 'cordis.patch.yml'), '[]\n', { flag: 'wx' }) } catch (error) { if (error.code !== 'EEXIST') throw error }
if (!linked) await fs.symlink(plugin, link, process.platform === 'win32' ? 'junction' : 'dir')
console.log(`独立 profile 已就绪：${profile}\n启动：dsh --profile satellite-geometry --port 3081 --no-open\n工作台：http://127.0.0.1:3081/satellite-geometry/`)
