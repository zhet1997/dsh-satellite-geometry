"""Copy completed local development projects into an empty container data volume."""
from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, action="append", required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--uid", type=int, default=10001)
    parser.add_argument("--gid", type=int, default=10001)
    args = parser.parse_args()
    destination = args.destination.resolve()
    projects = []
    ids = set()
    for source in args.source:
        for file in (source / "projects").glob("*/project.json"):
            project = json.loads(file.read_text(encoding="utf-8"))
            if project.get("activeJobId"):
                raise RuntimeError(f"Project {project['id']} has an active job")
            if project["id"] in ids or (destination / "projects" / project["id"]).exists():
                raise RuntimeError(f"Refusing to overwrite project {project['id']}")
            ids.add(project["id"])
            projects.append((file.parent, project))
    # Validate every target before writing anything. Original data is never moved.
    for directory, project in projects:
        shutil.copytree(directory, destination / "projects" / project["id"])
    for source in args.source:
        for file in (source / "jobs").glob("*"):
            if not file.is_file():
                continue
            target = destination / "jobs" / file.name
            if target.exists():
                raise RuntimeError(f"Refusing to overwrite job {file.name}")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(file, target)
    for current, dirs, files in os.walk(destination):
        os.chown(current, args.uid, args.gid)
        for name in files:
            os.chown(Path(current) / name, args.uid, args.gid)
    print(json.dumps({"projects": [{"id": p["id"], "name": p["name"], "revision": p["revision"]} for _, p in projects]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
