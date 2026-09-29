"""Small durable project/job store; source geometry is never overwritten."""
from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(os.environ.get("SATCAD_DATA_ROOT", Path(__file__).parent / "data")).resolve()
SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,80}$")


class StateLock:
    """Reentrant thread lock plus OS file lock shared with CAD subprocesses."""
    def __init__(self):
        self.thread_lock = threading.RLock()
        self.local = threading.local()

    def __enter__(self):
        self.thread_lock.acquire()
        depth = getattr(self.local, "depth", 0)
        if depth == 0:
            ROOT.mkdir(parents=True, exist_ok=True)
            handle = (ROOT / ".state.lock").open("a+b")
            try:
                if os.name == "nt":
                    import msvcrt
                    handle.seek(0)
                    handle.write(b"0")
                    handle.flush()
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            except BaseException:
                handle.close()
                self.thread_lock.release()
                raise
            self.local.handle = handle
        self.local.depth = depth + 1
        return self

    def __exit__(self, *_):
        self.local.depth -= 1
        if self.local.depth == 0:
            handle = self.local.handle
            if os.name == "nt":
                import msvcrt
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()
            del self.local.handle
        self.thread_lock.release()


LOCK = StateLock()


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_id(value: str) -> str:
    if not SAFE_ID.fullmatch(value):
        raise ValueError("无效项目或资源标识")
    return value


def project_dir(project_id: str) -> Path:
    return ROOT / "projects" / safe_id(project_id)


def atomic_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".write-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_project(project_id: str) -> dict:
    return read_json(project_dir(project_id) / "project.json")


def save_project(project: dict, *, increment: bool = False) -> dict:
    if increment:
        project["revision"] += 1
    project["updatedAt"] = now()
    atomic_json(project_dir(project["id"]) / "project.json", project)
    return project


def new_project(name: str) -> dict:
    project = {
        "id": uuid.uuid4().hex, "name": name.strip() or "卫星几何项目", "revision": 0,
        "status": "empty", "units": "mm", "createdAt": now(), "updatedAt": now(),
        "coordinateSystem": {"source": "Z-up mm", "glb": "Y-up m", "glbTransform": "[x,z,-y]/1000"},
        "tree": [], "components": [], "artifacts": {}, "documents": [], "plans": [],
        "checks": {"sourceCollisions": [], "envelopeCollisions": [], "falsePositivePairs": [],
                   "contacts": [], "warnings": [], "sourceComplete": False, "envelopeComplete": False,
                   "thermalStatus": "unknown", "assemblyStatus": "unknown"},
    }
    return save_project(project)


def list_projects() -> list[dict]:
    result = []
    for path in (ROOT / "projects").glob("*/project.json"):
        try:
            project = read_json(path)
            result.append({key: project.get(key) for key in ("id", "name", "revision", "status", "updatedAt", "activeJobId")})
        except (ValueError, OSError):
            continue
    return sorted(result, key=lambda item: item.get("updatedAt") or "", reverse=True)


def artifact_url(project_id: str, relative: str) -> str:
    return f"/api/projects/{project_id}/artifacts/{relative}"


def artifact_path(project_id: str, relative: str) -> Path:
    root = project_dir(project_id) / "artifacts"
    candidate = (root / relative).resolve()
    if root.resolve() not in candidate.parents:
        raise ValueError("资源路径越界")
    return candidate


def check_revision(project: dict, revision: int) -> None:
    if revision != project["revision"]:
        raise ValueError(f"项目版本已变化：提交 {revision}，当前 {project['revision']}，请刷新后重试")


def invalidate_exports(project: dict) -> None:
    """Old artifacts remain immutable but must not masquerade as current output."""
    for key in ("step", "report", "contacts", "bundle"):
        project["artifacts"].pop(key, None)
    project.pop("lastExport", None)


def new_job(project_id: str, kind: str) -> dict:
    job_id = uuid.uuid4().hex
    job = {"id": job_id, "jobId": job_id, "projectId": project_id, "kind": kind,
           "status": "queued", "progress": 0, "message": "任务已排队", "createdAt": now(), "updatedAt": now()}
    atomic_json(ROOT / "jobs" / f"{job_id}.json", job)
    return job


def get_job(job_id: str) -> dict:
    return read_json(ROOT / "jobs" / f"{safe_id(job_id)}.json")


def update_job(job_id: str, **changes) -> dict:
    with LOCK:
        job = get_job(job_id)
        job.update(changes, updatedAt=now())
        atomic_json(ROOT / "jobs" / f"{job_id}.json", job)
        return job


class Cancelled(Exception):
    pass


def progress(job_id: str, amount: float, message: str) -> None:
    if get_job(job_id).get("cancelRequested"):
        raise Cancelled("用户取消任务")
    update_job(job_id, status="running", progress=round(amount, 1), message=message)
