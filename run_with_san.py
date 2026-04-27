#!/usr/bin/env python3
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


def abort(message: str) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(1)


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        abort(f"{path}: invalid JSON: {exc}")


def executable() -> Path:
    build_path = Path("build-san")
    reply_dir = build_path / ".cmake" / "api" / "v1" / "reply"
    if not reply_dir.exists():
        abort(f"{reply_dir}: codemodel reply directory does not exist")

    indexes = list(reply_dir.glob("index-*.json"))
    if not indexes:
        abort(f"{reply_dir}: no index JSON found")

    index = load_json(indexes[0])
    codemodel_file = index["reply"]["codemodel-v2"]["jsonFile"]
    codemodel = load_json(reply_dir / codemodel_file)
    paths: list[Path] = []

    for config in codemodel["configurations"]:
        for target in config["targets"]:
            target_data = load_json(reply_dir / target["jsonFile"])
            if target_data["type"] != "EXECUTABLE":
                continue
            for artifact in target_data.get("artifacts", []):
                paths.append((build_path / artifact["path"]).resolve())

    if not paths:
        abort("build-san codemodel contains no executables")
    if len(paths) > 1:
        abort("build-san codemodel contains multiple executables")
    return paths[0]


def input_data(path: Path) -> dict[str, Any]:
    if not path.exists():
        abort(f"{path}: input file does not exist")

    data = load_json(path)
    if not isinstance(data, dict):
        abort(f"{path}: expected JSON object")
    if not isinstance(data.get("argv"), list):
        abort(f"{path}: expected argv list")
    if not all(isinstance(arg, str) for arg in data["argv"]):
        abort(f"{path}: expected argv to contain only strings")
    if not isinstance(data.get("stdin"), str):
        abort(f"{path}: expected stdin string")
    return data


def is_fresh(output_path: Path, inputs: list[Path]) -> bool:
    if not output_path.exists():
        return False
    output_mtime = output_path.stat().st_mtime_ns
    return all(
        path.exists() and path.stat().st_mtime_ns <= output_mtime for path in inputs
    )


def main() -> None:
    exe = executable()
    exe_cmd = [f"./{exe.name}"]
    exe_cwd = exe.parent
    inputs = Path("inputs")
    outputs = Path("outputs")
    outputs.mkdir(exist_ok=True)

    for arg in inputs.iterdir():
        input_path = Path(arg)
        output_path = outputs / input_path.name
        if is_fresh(output_path, [input_path, exe]):
            print(f"Keeping {output_path}...")
            continue
        print(f"Running {exe} with input {arg}...")
        data = input_data(input_path)
        env = os.environ.copy()
        env["ASAN_OPTIONS"] = "exitcode=86:detect_leaks=0"
        try:
            result = subprocess.run(
                [*exe_cmd, *data["argv"]],
                input=data["stdin"].encode(),
                capture_output=True,
                env=env,
                cwd=exe_cwd,
                timeout=60,
            )
        except subprocess.TimeoutExpired:
            print(f"Timeout after 60 seconds for input {input_path}")
            continue
        output = {
            "argv": data["argv"],
            "stdin": data["stdin"],
            "stdout": result.stdout.decode("latin-1"),
            "stderr": result.stderr.decode("latin-1"),
            "exitcode": result.returncode,
            "ub": result.returncode == 86,
        }
        output_path.write_text(json.dumps(output))


if __name__ == "__main__":
    main()
