"""One CAD job per process. The HTTP server never imports or runs OCP."""
from __future__ import annotations

import argparse
import os
import signal
import sys

from service import storage as db


def protect_parent_lifetime():
    # Linux: a server crash kills its active CAD worker instead of leaving an
    # orphan that could later overwrite recovered state.
    if sys.platform.startswith("linux"):
        import ctypes
        parent = int(os.environ.get("SATCAD_SUPERVISOR_PID", str(os.getppid())))
        ctypes.CDLL(None).prctl(1, signal.SIGTERM)
        if os.getppid() != parent:
            raise SystemExit(1)


def run(job_id):
    job = db.get_job(job_id)
    project = job["projectSnapshot"]
    try:
        db.progress(job_id, 1, "独立几何进程开始处理")
        from service.tasks import execute
        result = execute(job["kind"], project, job["payload"], job_id)
        db.progress(job_id, 99, "保存结果")
        with db.LOCK:
            current = db.load_project(project["id"])
            db.check_revision(current, project["revision"])
            if current.get("activeJobId") != job_id or db.get_job(job_id).get("cancelRequested"):
                raise db.Cancelled("任务已取消或失去项目所有权")
            result.pop("activeJobId", None)
            if "workflowBindings" in current:
                result["workflowBindings"] = current["workflowBindings"]
            increment = job["incrementRevision"]
            if increment:
                db.invalidate_exports(result)
            result["checks"]["revision"] = project["revision"] + int(increment)
            db.save_project(result, increment=increment)
            db.update_job(job_id, status="completed", progress=100, message="任务完成",
                          result={"projectId": result["id"], "revision": result["revision"], "artifacts": result["artifacts"],
                                  "summary": result.get("summary"), "checks": result["checks"]})
    except db.Cancelled as exc:
        db.update_job(job_id, status="cancelled", message=str(exc))
    except Exception as exc:
        import traceback
        traceback.print_exc()
        db.update_job(job_id, status="failed", message="任务失败；原始模型和已完成版本保持可用", error=f"{type(exc).__name__}: {exc}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("job_id")
    args = parser.parse_args()
    protect_parent_lifetime()
    run(args.job_id)
