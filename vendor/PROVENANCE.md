# Reused source

`step_occurrences.py` is copied without semantic changes from
`/data/lbk/codex_web/agent-web/services/cad-assembly/backend/cad/step_occurrences.py`
on work-server-5090-ali, retrieved 2026-09-29. It contains STEP occurrence/name
decoding and source relationship parsing. No runtime project data or credentials
are included. The new service retains every source occurrence; it does not invoke
the original module's exact-occurrence deduplication operation.

The copied file and the source file were compared on 2026-09-29 and have the same
SHA-256: `9e1c8cb494e98fc57755132caebf09e0317c0283877bc343bccbee1a8a6b5548`.
The source checkout HEAD observed at that time was
`bd4b5062d14e7d5e426a5762897ac1ac6646418b`; the file hash identifies the actual
working-copy bytes independently of the Git revision.

The remaining service is an independent extraction adapter. It reuses the original
project's XCAF traversal and local prototype/world instance design, with explicit
immutable source shapes and independent API/storage roots.

See `NOTICE.md` for the scope of this provenance record and license findings.
