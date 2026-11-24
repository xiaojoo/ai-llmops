import contextlib
import json
import runpy
import sys
from pathlib import Path


def main() -> None:
    script = Path(sys.argv[1]).resolve()
    query = json.load(sys.stdin)["query"]
    sys.path.insert(0, str(script.parent))
    with contextlib.redirect_stdout(sys.stderr):
        namespace = runpy.run_path(str(script))
        runner = namespace.get("run")
        if not callable(runner):
            raise RuntimeError("技能脚本缺少可调用的 run(query)")
        result = runner(query)
    print(json.dumps({"ok": True, "result": result}, ensure_ascii=False, default=str))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1)
