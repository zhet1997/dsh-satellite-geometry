import { build } from 'esbuild'
import { cp, mkdir, access, rm } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
const id = '@lbk/dsh-satellite-geometry'
await mkdir(new URL('./lib/', import.meta.url), { recursive: true })
await build({ entryPoints: [new URL('./src/client.jsx', import.meta.url).pathname.replace(/^\/(\w:)/, '$1')], outfile: new URL('./lib/client.js', import.meta.url).pathname.replace(/^\/(\w:)/, '$1'), bundle: true, format: 'cjs', platform: 'browser', target: 'es2022', external: ['react', 'react/jsx-runtime'], banner: { js: `window.__ModuleLoader__.load({id:${JSON.stringify(id)},factory:(require)=>{var module={exports:{}};var exports=module.exports;` }, footer: { js: 'return module.exports;}});' } })
const viewer = new URL('../web/dist/', import.meta.url)
try {
  await access(viewer)
  const outputViewer = fileURLToPath(new URL('./public/viewer/', import.meta.url))
  const publicRoot = fileURLToPath(new URL('./public/', import.meta.url))
  if (path.resolve(outputViewer) !== path.resolve(publicRoot, 'viewer')) throw new Error('Unexpected generated viewer directory')
  await rm(outputViewer, { recursive: true, force: true })
  await cp(viewer, outputViewer, { recursive: true })
} catch (error) { if (error.code !== 'ENOENT') throw error; console.warn('Viewer not built yet: build web then rerun plugin build before packaging.') }
