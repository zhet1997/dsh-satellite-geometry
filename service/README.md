# Satellite Geometry service

Current service version: **0.3.0**. The thermal workbench API and button mapping are documented in [workbench-api.md](../docs/workbench-api.md). `workbench.py` validates recipes, named copies, identity states, contact edits, immutable Skill bindings, and external evidence. `modeling.py` builds solid/face geometry; `skill_versions.py` stores versioned content and resources.

This is the independent STEP-first backend used by the DSH MCP tools and the web workbench. The API process stores project state and supervises CAD jobs. Each CAD job runs in a separate Python process so a long OCCT operation cannot freeze HTTP health, progress, or cancellation requests. The original `codex_web` application is not required at runtime.

## Runtime and persistence

Install `requirements.txt` in a Python 3.12 environment, then start from the repository root:

```sh
python -m uvicorn service.app:app --host 127.0.0.1 --port 8787
```

The service uses `SATCAD_DATA_ROOT` when set, otherwise `service/data`. Project source STEP, prototype STEP, revision artifacts, documents, plans, and job logs live below that root. Run one API instance per data root. `SATCAD_TOKEN` optionally requires a bearer token on all API routes except health. CORS origins may be configured through `SATCAD_CORS_ORIGINS`.

`SATCAD_JOB_TIMEOUT_SECONDS` defaults to 3600. A cancelled or timed-out job terminates its worker and does not commit a project revision. The previous saved project remains readable. Failed jobs retain diagnostic logs. Source pair results that completed before interruption can be cached and reused; incomplete pairs are never cached as successful.

On Linux, each exact pair runs in a bounded fork child that inherits the worker's read-only BRep. `SATCAD_PAIR_TIMEOUT_SECONDS` defaults to 10 and `SATCAD_CHECK_BUDGET_SECONDS` to 300 per exact checking round, excluding source loading. A timed-out pair is unknown, and checking continues for other pairs. Successful pairs are saved; failures are reused only within that job, so another job can retry with larger limits. `checks.unknownPairCounts` separates pair timeouts, round-budget omissions, pair-count limits, and geometry errors. The supervisor cancels the entire process group and reaps the pair child. These individual-pair isolation guarantees apply to Linux/WSL and the Linux Docker runtime; native Windows has whole-job process isolation only.

Source and candidate shapes use a bounded in-process cache and optional native binary BRep files under `.brep-cache` beside their STEP files. Disk cache keys include absolute STEP path, modification time, size, kernel version, and cache format version. Invalid or unavailable caches fall back to STEP. The source STEP and its hash remain the external provenance record. This avoids repeated STEP conversion in later check/export jobs.

## Project and geometry contract

- `POST /api/projects` creates an empty project. `POST /api/projects/{id}/import` accepts a multipart `file` containing STEP/STP. An imported source cannot be replaced in that project; another source needs another project.
- Mutating operations use the current integer `revision`. A stale revision returns HTTP 409. One CAD job may own a project at a time.
- Import retains source occurrences, immutable source-local prototype geometry, original world poses, and the complete `sourceTree`. A separate working `tree` may contain component renames and semantic groups.
- Source and API poses use millimetres in a right-handed Z-up frame. GLB uses standard metres in a right-handed Y-up frame: `[x,z,-y]/1000`. GLB nodes contain `extras.componentId` and `extras.prototypeId`; consumers must not convert axes or units a second time.
- Up to 128 source leaves are individual components by default. Larger inputs use the original project's semantic top-down grouping, retaining `sourceNodeIds` for all constituent occurrences. `SATCAD_MAX_LEAF_COMPONENTS` changes that threshold.
- Box and multibox candidates are measured by OCCT. LLM-supplied executable code or invented bounding dimensions are not accepted.

Import, simplify, plan application, geometry checks, export, pose changes, and restoration return a job ID. `GET /api/jobs/{id}` returns public status/progress/result; internal payload and project snapshots are excluded. `POST /api/jobs/{id}/cancel` requests cancellation.

## Documents and field provenance

Upload DOCX, XLSX, PDF, TXT, Markdown, CSV, or JSON through `POST /api/projects/{id}/documents`. PDF extraction is text only; scanned documents need a separate OCR workflow. Source documents and extracted text remain separate from geometry.

Submit component properties through `POST /api/projects/{id}/metadata`:

```json
{
  "revision": 1,
  "components": [{
    "id": "N00002",
    "origin": "document",
    "massKg": 3,
    "sources": [{
      "documentId": "document-id",
      "field": "massKg",
      "quote": "设备质量为 3 kg",
      "reference": "Table 2, row 5; component matched by dimensions"
    }]
  }]
}
```

Each supplied non-null field with `origin=document` needs a reference with that exact field name and a verbatim quote in the stored extracted text. This includes `fixed:false`, `thermalCritical:false`, and `notes`. Omit unknown fields. Evidence coverage and literal quote existence are checked; interpretation of the quote and component matching remain reviewable LLM judgments. Do not describe these checks as automatic verification of engineering truth.

For manual edits, use `origin=manual` and send only the changed fields. Optional `changedFields` must exactly match the supplied property keys. Manual edits must omit `sources`; the service removes old evidence only for those fields and preserves all other references. A null value clears that property and records it as unknown. Results expose `metadata.provenance[field]` with origin, state, timestamp, and sources. Match explanations can go in the top-level request `notes` or a source's `reference` rather than being presented as a quoted component property.

`motionConstraints` contains permitted world translation axes, maximum displacement from the original pose, maximum rotation from the original pose, contact-preservation intent, and a reason. Document-derived constraints require references for each explicitly supplied subfield, using names such as `motionConstraints.maxTranslationMm` and `motionConstraints.reason`. Human-specified constraints use `origin=manual`.

## Layout and acceptance boundaries

Simplification preserves original poses. Fixed means the position and orientation cannot change; it does not prohibit envelope simplification. `thermalCritical` components keep their original geometry. In thermal mode, contact-bearing or uncertain components retain their complete source geometry.

There is no general automatic layout search in this initial extraction. A DSH agent can submit an explicit pose candidate only after recording motion constraints and either an explicit user layout request or a verified source collision. An envelope-only overlap never authorizes automatic movement. A pose candidate is checked against the original STEP BRep at its new pose. Unknown checks, new real collisions, and protected contact changes reject the commit. An automatic collision repair must reduce real intersection volume without making an existing interference worse.

Source collisions and candidate-envelope collisions are separate reports. A pair whose envelopes intersect but whose original BRep does not is an envelope false positive. Source pair cache identity includes source hashes, both poses, tolerance, kernel version, and algorithm version; a pose change invalidates that pair automatically. `SATCAD_MAX_EXACT_PAIRS` defaults to 1500. Pairs beyond the limit remain unknown, and affected components are retained.

Envelope false positives trigger one bounded refinement using per-solid boxes or planar slices. Source geometry must remain covered, and volume recovery is checked before accepting the sliced candidate. An unresolved or failed refinement restores the affected component's original geometry without moving it. Initial false positives, refinement choices, fallback reasons, and the associated revision remain in `envelopeRefinement` in the project and exported report. Source compounds with faces that do not belong to any solid remain unknown and retain their original geometry; `sourceGeometryCoverage` records that evidence. Older imports obtain this evidence during their next check.

The thermal acceptance status covers preservation of identified contact-bearing and explicitly critical source components. It does not certify thermal conductance, material properties, or physical mounting contact. The assembly acceptance status covers component-to-component original BRep intersection. It does not certify cables, bolt/hole fits, installation order, or complete shell containment. These limits are recorded alongside both status values.

Export creates a named STEP assembly following the working tree, GLB, `properties.json`, `contacts.json`, and a ZIP bundle. Repeated instances share the same local part definition and carry individual Locations, avoiding geometry duplication while preserving world poses. The exported STEP occurrence names are checked against every working component, and instance/prototype counts are recorded. All original poses and the complete source tree remain in the property report.

`lastExport` and `properties.json.export` distinguish `stepReadable`, `stepReadbackValid`, and `sourceTopologyValid`. Existing invalid source parts may be exported as review/repair candidates: the report lists `invalidSourceComponentIds`, warnings, and status `source_and_output_invalid_review_required`. A source with existing defects whose output happens to pass topology readback still has status `source_defects_review_required`. A new topology failure from fully valid inputs, or an invalid simplified candidate, remains a failed export. Readability does not certify topology, equivalence of every defect, or engineering acceptance; a successful topology readback never promotes an unknown engineering check to passed.

## Focused validation

```sh
python -m unittest service.test_api service.test_geometry service.test_workbench -v
```

The fixtures exercise repeated instances and nested transforms, true foot contact area, envelope false positives, thermal preservation, source-pair cache invalidation, pose constraints, rejection of damaging moves, semantic-group STEP roundtrips, quote coverage, manual evidence replacement, concurrent upload reservation, and cancellable isolated workers.

Recipe `surface_shell` means a face collection with no solids. Its thickness, material, mass and other thermal fields remain separate from geometry. Both candidates and the assembled export are checked by importing the actual STEP file without the pre-export BRep cache. A valid in-memory shape alone does not pass the serialization gate. Installation selectors are clipped to exposed output faces; buried regions reject the rebuild. Geometry or pose changes invalidate linked contacts, and geometric candidates do not certify thermal conductance.

Identity `nameStatus` is `identified`, `candidate`, or `unidentified`; omitted states default to `candidate`. Content hashing and session bindings keep Skill versions immutable. New default rules create a new version for future runs; existing session pins are unchanged. `/evidence` exposes the actual recipe, identity evidence, checks, unknowns, feedback and downloaded artifacts, with `scoring: external`.
