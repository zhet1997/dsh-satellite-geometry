"""Inspect solid/face coverage of local STEP prototypes without model calls."""
import argparse
import json
import time
from pathlib import Path

from service.geometry import read_shape, solid_face_coverage


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="+")
    args = parser.parse_args()
    for name in args.paths:
        started = time.monotonic()
        shape = read_shape(Path(name))
        print(json.dumps({"path": name, "solidCount": len(shape.Solids()),
                          "coverage": solid_face_coverage(shape),
                          "elapsedSeconds": round(time.monotonic() - started, 3)}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
