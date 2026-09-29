// Compact independently checked evidence. Raw native histories remain in validation/raw.
import fs from 'node:fs/promises'
import assert from 'node:assert/strict'
const validation = new URL('../../validation/', import.meta.url)
const before = JSON.parse(await fs.readFile(new URL('raw/catch-native-before.json', validation), 'utf8'))
const evidence = JSON.parse(await fs.readFile(new URL('raw/catch-native-evidence.json', validation), 'utf8'))
const project = await fetch(`http://127.0.0.1:8789/api/projects/${before.id}`).then(r => r.json())
const document = await fetch(`http://127.0.0.1:8789/api/projects/${before.id}/documents/a8170e5c4808458589f7e6ecde0de7cf`).then(r => r.json())
const rows = document.sections.map(section => ({ reference: section.reference, text: section.text, cols: section.text.split('|').map(value => value.trim()) })).filter(row => row.cols.length > 4 && /^\d+(\.\d+)?$/.test(row.cols[2]) && /^\d/.test(row.cols[3]))
const known = project.components.filter(component => component.metadata.massKg !== undefined || component.metadata.powerW !== undefined)
const details = []
for (const component of known) {
  for (const field of ['massKg', 'powerW']) {
    const provenance = component.metadata.provenance[field]
    assert.equal(provenance.origin, 'document')
    assert.equal(provenance.state, 'known')
    assert.ok(provenance.sources.length)
    for (const source of provenance.sources) {
      assert.equal(source.documentId, document.id)
      assert.equal(source.field, field)
      assert.ok(document.text.includes(source.quote))
      const row = rows.find(row => row.text === source.quote)
      assert.ok(row, 'Each quote is one exact original XLSX row')
      assert.equal(component.metadata[field], Number(row.cols[field === 'massKg' ? 2 : 4]))
    }
  }
  const dimensions = component.dimensionsMm.slice().sort((a, b) => a - b)
  const candidates = rows.filter(row => {
    const sourceDimensions = row.cols[3].split(/x|×/).map(Number).sort((a, b) => a - b)
    return sourceDimensions.length === 3 && sourceDimensions.every((value, i) => Math.abs(value - dimensions[i]) <= 0.31)
  })
  assert.equal(candidates.length, 1, `${component.id} must have exactly one dimension candidate within 0.31 mm`)
  const sourceDimensions = candidates[0].cols[3].split(/x|×/).map(Number).sort((a, b) => a - b)
  details.push({ id: component.id, name: component.name, sourceRow: candidates[0].reference, sourceProduct: candidates[0].cols[1], massKg: component.metadata.massKg, powerW: component.metadata.powerW, maxDimensionErrorMm: Math.max(...sourceDimensions.map((value, i) => Math.abs(value - dimensions[i]))) })
}
for (const component of project.components) {
  const original = before.components.find(item => item.id === component.id)
  for (const key of ['pose', 'originalPose', 'sourceHash', 'sourceFile', 'strategy', 'localBoundsMm', 'boundsMm', 'name', 'parentId']) assert.deepEqual(component[key], original[key], `${component.id} ${key} unchanged`)
  for (const field of ['fixed', 'material', 'thermalCritical', 'motionConstraints']) assert.equal(component.metadata[field], undefined, `${field} must remain unknown`)
}
assert.equal(known.length, 13)
assert.equal(project.revision, before.revision + 1)
assert.equal(project.components.filter(component => !Object.keys(component.metadata).length).length, 20)
const events = evidence.history.events.map(item => item.event || item)
const calls = events.filter(item => item.type === 'tool/call')
assert.ok(events.at(-1)?.type === 'turn/end', 'Native document extraction turn must be complete')
const selection = JSON.parse(await fs.readFile(new URL('raw/selection-native-evidence.json', validation), 'utf8'))
const selectionEvents = selection.history.events.map(item => item.event || item)
assert.ok(selectionEvents.some(item => item.type === 'tool/call' && item.data?.name === 'satellite_selection_context'))
assert.ok(selectionEvents.some(item => item.type === 'turn/end'))
const summary = {
  checkedAt: new Date().toISOString(),
  sessionId: evidence.sessionId,
  projectId: project.id,
  revisionBefore: before.revision,
  revisionAfter: project.revision,
  componentCount: project.components.length,
  componentsWithSourcedAttributes: known.length,
  sourcedFieldCount: known.length * 2,
  unmatchedComponentsRemainUnknown: 20,
  documentsReadByNativeModel: calls.filter(item => item.data?.name === 'mcp__satellite_geometry__satellite_read_document').map(item => JSON.parse(item.data.arguments).documentId),
  assertions: { nativeDocumentTurnCompleted: true, allQuotesExact: true, allValuesEqualOriginalSpreadsheetColumns: true, allFieldsDocumentProvenance: true, uniqueDimensionCandidateWithin031mm: true, unsupportedFieldsRemainUnknown: true, geometryPoseAndAssemblyUnchanged: true, nativeShortReferenceResolved: true },
  shortReferenceSessionId: selection.state.sessionId,
  rawHistoryIncluded: false,
  observations: ['Dimension matching is an inference recorded separately from original quotations; it is not an identity certificate.', 'The first submission was rejected by an older running service; after restart the model resubmitted successfully.', 'The native model used read-only file/shell tools to inspect oversized MCP spill output; componentIds filtering was subsequently added to support focused MCP verification.'],
  components: details,
}
await fs.writeFile(new URL('native-integration-summary.json', validation), JSON.stringify(summary, null, 2))
console.log(JSON.stringify({ assertions: summary.assertions, sourcedFieldCount: summary.sourcedFieldCount, revisions: [before.revision, project.revision], summary: 'validation/native-integration-summary.json' }, null, 2))
