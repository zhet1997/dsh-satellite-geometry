import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { spawnSync } from 'node:child_process'

test('profile installer preserves an existing profile whose plugin points elsewhere', async () => {
  const testHome = await fs.mkdtemp(path.join(os.tmpdir(), 'satcad-profile-'))
  try {
    const profile = path.join(testHome, 'profiles/satellite-geometry')
    const target = path.join(testHome, 'other-plugin')
    await fs.mkdir(path.join(profile, 'node_modules/@lbk'), { recursive: true })
    await fs.mkdir(target)
    const manifest = JSON.stringify({ name: 'existing-profile', private: true, dependencies: { '@lbk/dsh-satellite-geometry': 'link:original' }, dsh: { profile: { bundles: ['@lbk/dsh-satellite-geometry'] } } })
    await fs.writeFile(path.join(profile, 'package.json'), manifest)
    await fs.symlink(target, path.join(profile, 'node_modules/@lbk/dsh-satellite-geometry'), process.platform === 'win32' ? 'junction' : 'dir')
    const result = spawnSync(process.execPath, [fileURLToPath(new URL('../install-profile.mjs', import.meta.url))], { env: { ...process.env, DSH_HOME: testHome }, encoding: 'utf8' })
    assert.notEqual(result.status, 0)
    assert.equal(await fs.readFile(path.join(profile, 'package.json'), 'utf8'), manifest)
    assert.equal(await fs.realpath(path.join(profile, 'node_modules/@lbk/dsh-satellite-geometry')), await fs.realpath(target))
  } finally { await fs.rm(testHome, { recursive: true, force: true }) }
})
