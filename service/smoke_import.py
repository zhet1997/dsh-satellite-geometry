"""Explicit input smoke runner; no network, provider calls, or original mutations."""
import argparse
import json
import shutil
import time
from pathlib import Path

from service import storage as db
from service.geometry import import_step


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("step")
    args = parser.parse_args()
    source = Path(args.step).resolve()
    started = time.monotonic()
    project = db.new_project(f"导入验收 {source.parent.name}")
    job = db.new_job(project["id"], "smoke_import")
    target = db.project_dir(project["id"]) / "source" / "original.step"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    artifact = db.project_dir(project["id"]) / "artifacts" / "source.step"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, artifact)
    try:
        project = import_step(project, target, job["id"])
        db.save_project(project, increment=True)
        db.update_job(job["id"], status="completed", progress=100)
        print(json.dumps({"projectId": project["id"], "components": len(project["components"]),
                          "source": project["source"], "elapsedSeconds": time.monotonic() - started,
                          "artifacts": project["artifacts"]}, ensure_ascii=False, indent=2), flush=True)
    except Exception as exc:
        db.update_job(job["id"], status="failed", error=str(exc))
        raise


if __name__ == "__main__":
    main()
