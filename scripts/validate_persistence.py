"""Record and compare real HTTP state across a separately performed cold restart."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import httpx


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["before", "after"])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    base = "http://127.0.0.1:8787"
    snapshot = {}
    with httpx.Client(timeout=120, trust_env=False) as client:
        health = client.get(base + "/api/health")
        health.raise_for_status()
        assert health.json()["service"] == "satellite-geometry"
        listing = client.get(base + "/api/projects")
        listing.raise_for_status()
        for item in listing.json()["projects"]:
            assert not item.get("activeJobId"), "Wait for current geometry jobs before restart"
            response = client.get(base + "/api/projects/" + item["id"])
            response.raise_for_status()
            project = response.json()
            entry = {"name": project["name"], "revision": project["revision"],
                     "componentCount": len(project["components"]),
                     "documentCount": len(project.get("documents", []))}
            if project.get("artifacts", {}).get("step"):
                digest = hashlib.sha256()
                with client.stream("GET", base + project["artifacts"]["step"]) as download:
                    download.raise_for_status()
                    for block in download.iter_bytes():
                        digest.update(block)
                entry["stepSha256"] = digest.hexdigest()
                entry["export"] = project.get("lastExport")
            snapshot[item["id"]] = entry
        workbench = client.get("http://127.0.0.1:3081/satellite-geometry/")
        workbench.raise_for_status()
        proxy = client.get("http://127.0.0.1:3081/api/cad/health")
        proxy.raise_for_status()
        assert proxy.json()["service"] == "satellite-geometry"
    stamp = datetime.now(timezone.utc).isoformat()
    if args.phase == "before":
        result = {"container": "dsh-satellite-geometry-geometry-1", "beforeAt": stamp,
                  "projectsBefore": snapshot, "restartPersistencePassed": False}
    else:
        result = json.loads(args.output.read_text(encoding="utf-8"))
        assert snapshot == result["projectsBefore"], "Project revision, documents or exported bytes changed after restart"
        result.update(afterAt=stamp, projectsAfter=snapshot, restartPersistencePassed=True,
                      workbenchHttpReady=True, dshProxyReady=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"phase": args.phase, "projects": len(snapshot),
                      "stepDownloads": sum("stepSha256" in p for p in snapshot.values()),
                      "restartPersistencePassed": result["restartPersistencePassed"]}))


if __name__ == "__main__":
    main()
