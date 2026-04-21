#!/usr/bin/env python3
import json
import os
import shutil
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


def require_input_data(path: Path) -> dict[str, Any]:
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


def test_vectors_dir() -> Path:
    root = Path(__file__).resolve().parent / "test_vectors"
    if not root.is_dir():
        abort(f"{root}: test_vectors directory does not exist")
    if not (root / "CMakeLists.txt").is_file():
        abort(f"{root / 'CMakeLists.txt'}: file does not exist")
    if not (root / "inputs").is_dir():
        abort(f"{root / 'inputs'}: directory does not exist")
    return root


def test_case_dirs(root: Path) -> list[Path]:
    inputs_dir = root / "inputs"
    paths = sorted(path for path in inputs_dir.iterdir() if path.is_dir())
    if not paths:
        abort(f"{inputs_dir}: expected at least one test case subdirectory")
    return paths


def validate_test_case_dir(path: Path) -> list[Path]:
    c_files = sorted(path.glob("*.c"))
    json_files = sorted(path.glob("*.json"))
    if len(c_files) != 1:
        abort(f"{path}: expected exactly one .c file, found {len(c_files)}")
    if not json_files:
        abort(f"{path}: expected at least one .json file")
    return json_files


def run_case(
    exe_path: Path, work_dir: Path, output_dir: Path, input_path: Path
) -> None:
    data = require_input_data(input_path)
    env = os.environ.copy()
    env["ASAN_OPTIONS"] = "exitcode=86:detect_leaks=0"
    try:
        result = subprocess.run(
            [str(exe_path.resolve()), *data["argv"]],
            input=data["stdin"].encode(),
            capture_output=True,
            env=env,
            cwd=work_dir,
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        print(f"Timeout after 60 seconds for input {input_path}")
        return
    output = {
        "argv": data["argv"],
        "stdin": data["stdin"],
        "stdout": result.stdout.decode("latin-1"),
        "stderr": result.stderr.decode("latin-1"),
        "exitcode": result.returncode,
        "ub": result.returncode == 86,
    }
    (output_dir / input_path.name).write_text(json.dumps(output))


def main() -> None:
    root = test_vectors_dir()
    cases = [
        (case_dir, validate_test_case_dir(case_dir))
        for case_dir in test_case_dirs(root)
    ]
    try:
        subprocess.run(
            [
                "cmake",
                "-S",
                ".",
                "-B",
                "./build-san",
                "-G",
                "Ninja",
                "-DCMAKE_C_COMPILER=clang-20",
                "-DENABLE_SAN=ON",
                "-DENABLE_COV=OFF",
                "-DENABLE_OPT=OFF",
            ],
            cwd=root,
            check=True,
        )
        subprocess.run(["cmake", "--build", "build-san"], cwd=root, check=True)
    except subprocess.CalledProcessError as exc:
        abort(
            f"cmake configure/build for build-san failed with exit code {exc.returncode}"
        )
    exe_dir = root / "build-san" / "bin"
    outputs_root = root / "outputs"
    if outputs_root.exists():
        shutil.rmtree(outputs_root)
    outputs_root.mkdir()

    for case_dir, input_paths in cases:
        exe_path = exe_dir / case_dir.name
        if not exe_path.is_file():
            abort(f"{exe_path}: executable does not exist")
        outputs = outputs_root / case_dir.name
        outputs.mkdir()
        for input_path in input_paths:
            print(f"Running {exe_path} with input {input_path}...")
            run_case(exe_path, case_dir, outputs, input_path)


if __name__ == "__main__":
    main()
