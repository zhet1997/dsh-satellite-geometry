"""Validation utility: read-only comparison of saved inputs and exported STEP."""
import argparse
import json
import time
from pathlib import Path

from service.geometry import brep_cache_path, cq_module, shape_transform, solid_face_coverage, bounds


def read_without_writes(path):
    cq = cq_module()
    cache = brep_cache_path(path)
    return cq.Shape.importBin(str(cache)) if cache.is_file() else cq.importers.importStep(str(path)).val()


def fingerprint(shape):
    return {"topologyValid": bool(shape.isValid()), "solidCount": len(shape.Solids()),
            "faceCoverage": solid_face_coverage(shape), "boundsMm": bounds(shape),
            "volumeMm3": abs(float(shape.Volume())) if shape.Solids() else 0.}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("project_dir")
    parser.add_argument("--components", action="store_true")
    parser.add_argument("--only-uncertain", action="store_true")
    args = parser.parse_args()
    root = Path(args.project_dir)
    project = json.loads((root / "project.json").read_text())
    shapes = []
    started = time.monotonic()
    for component in project["components"]:
        if args.only_uncertain and component.get("sourceValid"):
            continue
        local = read_without_writes(root / (component.get("candidateFile") or component["sourceFile"]))
        shapes.append(shape_transform(local, component["pose"]))
        if args.components:
            print(json.dumps({"componentId": component["id"], "name": component["name"],
                              "strategy": component["strategy"], "fingerprint": fingerprint(local)}, ensure_ascii=False), flush=True)
    if args.only_uncertain:
        return
    original = cq_module().Compound.makeCompound(shapes)
    print(json.dumps({"stage": "input_candidate", "elapsedSeconds": time.monotonic() - started,
                      "componentCount": len(shapes), "fingerprint": fingerprint(original)}, ensure_ascii=False), flush=True)
    output = root / "artifacts" / f"r{project['revision']}" / "simplified.step"
    result = read_without_writes(output)
    print(json.dumps({"stage": "export_readback", "elapsedSeconds": time.monotonic() - started,
                      "bytes": output.stat().st_size, "fingerprint": fingerprint(result)}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
