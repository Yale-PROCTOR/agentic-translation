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
    build_path = Path("build-cov")
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
        abort("build-cov codemodel contains no executables")
    if len(paths) > 1:
        abort("build-cov codemodel contains multiple executables")
    return paths[0]


def output_data(path: Path) -> dict[str, Any]:
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
    outputs = Path("outputs")
    cov = Path("cov")
    raw = cov / "raw"
    data_dir = cov / "data"
    show = cov / "show"
    raw.mkdir(parents=True)
    data_dir.mkdir(exist_ok=True)
    show.mkdir(exist_ok=True)
    raw_paths: list[Path] = []
    any_changed = False

    for output_path in outputs.glob("*.json"):
        data = output_data(output_path)
        name = output_path.stem
        env = os.environ.copy()
        raw_path = raw / f"{name}.profraw"
        data_path = data_dir / f"{name}.profdata"
        show_path = show / f"{name}.txt"
        if is_fresh(raw_path, [output_path, exe]):
            print(f"Keeping {raw_path}...")
        else:
            print(f"Running {exe} with output {output_path}...")
            env["LLVM_PROFILE_FILE"] = str(raw_path)
            subprocess.run(
                [*exe_cmd, *data["argv"]],
                input=data["stdin"].encode(),
                capture_output=True,
                env=env,
                cwd=exe_cwd,
            )
            any_changed = True
        if not data["ub"]:
            raw_paths.append(raw_path)
        if is_fresh(data_path, [raw_path]):
            print(f"Keeping {data_path}...")
        else:
            subprocess.run(
                [
                    "llvm-profdata-20",
                    "merge",
                    "-sparse",
                    str(raw_path),
                    "-o",
                    str(data_path),
                ],
                check=True,
            )
            any_changed = True
        if is_fresh(show_path, [data_path, exe]):
            print(f"Keeping {show_path}...")
        else:
            with show_path.open("w") as stdout:
                subprocess.run(
                    [
                        "llvm-cov-20",
                        "show",
                        str(exe),
                        f"-instr-profile={data_path}",
                        "-show-line-counts-or-regions",
                    ],
                    check=True,
                    stdout=stdout,
                )
            any_changed = True

    merged_path = cov / "merged.profdata"
    merged_show_path = cov / "merged.txt"
    report_path = cov / "report.txt"
    if not is_fresh(merged_path, raw_paths):
        subprocess.run(
            [
                "llvm-profdata-20",
                "merge",
                "-sparse",
                *map(str, raw_paths),
                "-o",
                str(merged_path),
            ],
            check=True,
        )
        any_changed = True
    else:
        print(f"Keeping {merged_path}...")
    if any_changed or not is_fresh(merged_show_path, [merged_path, exe]):
        with merged_show_path.open("w") as stdout:
            subprocess.run(
                [
                    "llvm-cov-20",
                    "show",
                    str(exe),
                    f"-instr-profile={merged_path}",
                    "-show-line-counts-or-regions",
                ],
                check=True,
                stdout=stdout,
            )
    else:
        print(f"Keeping {merged_show_path}...")
    if any_changed or not is_fresh(report_path, [merged_path, exe]):
        with report_path.open("w") as stdout:
            subprocess.run(
                [
                    "llvm-cov-20",
                    "report",
                    str(exe),
                    f"-instr-profile={merged_path}",
                ],
                check=True,
                stdout=stdout,
            )
    else:
        print(f"Keeping {report_path}...")


if __name__ == "__main__":
    main()
