"""Validation utility: export a copied component in a diagnostic workspace."""
import argparse
import copy
import importlib.util
import json
import tempfile
from pathlib import Path

from service import storage as db


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("project_dir")
    parser.add_argument("component_id")
    parser.add_argument("geometry_module")
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location("review_geometry", args.geometry_module)
    geometry = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(geometry)
    source_root = Path(args.project_dir)
    source = json.loads((source_root / "project.json").read_text())
    component = copy.deepcopy(next(item for item in source["components"] if item["id"] == args.component_id))
    prototype = source_root / (component.get("candidateFile") or component["sourceFile"])
    cache = geometry.brep_cache_path(prototype)
    cq = geometry.cq_module()
    shape = cq.Shape.importBin(str(cache)) if cache.is_file() else cq.importers.importStep(str(prototype)).val()
    db.ROOT = Path(tempfile.mkdtemp(prefix="satcad-export-review-"))
    project = db.new_project("Copied invalid source topology review")
    relative = "source/prototypes/source.step"
    geometry.write_shape(shape, db.project_dir(project["id"]) / relative)
    component.update(sourceFile=relative, parentId=None, sourceHash=geometry.source_hash(db.project_dir(project["id"]) / relative))
    component.pop("candidateFile", None)
    component["sourceTopologyValid"] = bool(shape.isValid())
    node = {"id": component["id"], "name": component["name"], "children": [], "parentId": None, "isLeaf": True}
    project.update(components=[component], tree=[node], sourceTree=[copy.deepcopy(node)], rootIds=[component["id"]],
                   source={"name": prototype.name, "sha256": component["sourceHash"]})
    job = db.new_job(project["id"], "isolated_export_review")
    result = geometry.export_project(project, job["id"])
    db.save_project(result)
    output = db.project_dir(project["id"]) / "artifacts" / "r0" / "simplified.step"
    print(json.dumps({"diagnosticRoot": str(db.ROOT), "sourceComponentId": component["id"],
                      "stepBytes": output.stat().st_size, "export": result["lastExport"],
                      "checks": result["checks"]}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
