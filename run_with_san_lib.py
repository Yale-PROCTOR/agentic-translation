#!/usr/bin/env python3
import json
import os
import shutil
import subprocess
import sys
import tempfile
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


def harness_path(path: Path) -> Path:
    c_files = sorted(path.glob("*.c"))
    if len(c_files) != 1:
        abort(f"{path}: expected exactly one .c file, found {len(c_files)}")
    return c_files[0]


def shared_lib_path(root: Path) -> Path | None:
    prefix = 'set(MYLIB_PATH "'
    suffix = '")'
    for line in (root / "CMakeLists.txt").read_text().splitlines():
        stripped = line.strip()
        if not stripped.startswith(prefix):
            continue
        if not stripped.endswith(suffix):
            abort(f"{root / 'CMakeLists.txt'}: malformed MYLIB_PATH line")
        path = Path(stripped[len(prefix) : -len(suffix)])
        if not path.is_file():
            abort(f"{path}: shared library does not exist")
        return path
    return None


def is_fresh(output_path: Path, inputs: list[Path]) -> bool:
    if not output_path.exists():
        return False
    output_mtime = output_path.stat().st_mtime_ns
    return all(
        path.exists() and path.stat().st_mtime_ns <= output_mtime for path in inputs
    )


def read_log(path: Path) -> str:
    if not path.is_file():
        return ""
    return path.read_text()


def run_case(exe_path: Path, output_dir: Path, input_path: Path) -> None:
    data = require_input_data(input_path)
    env = os.environ.copy()
    env["ASAN_OPTIONS"] = "exitcode=86:detect_leaks=0"
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        temp_exe = temp_path / exe_path.name
        shutil.copy2(exe_path, temp_exe)
        try:
            result = subprocess.run(
                [f"./{temp_exe.name}", *data["argv"]],
                input=data["stdin"].encode(),
                capture_output=True,
                env=env,
                cwd=temp_path,
                timeout=60,
            )
        except subprocess.TimeoutExpired:
            print(f"Timeout after 60 seconds for input {input_path}")
            return
        log = read_log(temp_path / "test-vector-output.log")
    output = {
        "argv": data["argv"],
        "stdin": data["stdin"],
        "stdout": result.stdout.decode("latin-1"),
        "stderr": result.stderr.decode("latin-1"),
        "log": log,
        "exitcode": result.returncode,
        "ub": result.returncode == 86,
    }
    (output_dir / input_path.name).write_text(json.dumps(output))


def main() -> None:
    root = test_vectors_dir()
    lib_path = shared_lib_path(root)
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
    outputs_root.mkdir(exist_ok=True)

    for case_dir, input_paths in cases:
        exe_path = exe_dir / case_dir.name
        if not exe_path.is_file():
            abort(f"{exe_path}: executable does not exist")
        harness = harness_path(case_dir)
        outputs = outputs_root / case_dir.name
        outputs.mkdir(exist_ok=True)
        for input_path in input_paths:
            output_path = outputs / input_path.name
            deps = [input_path, harness, exe_path]
            if lib_path is not None:
                deps.append(lib_path)
            if is_fresh(output_path, deps):
                print(f"Keeping {output_path}...")
                continue
            print(f"Running {exe_path} with input {input_path}...")
            run_case(exe_path, outputs, input_path)


if __name__ == "__main__":
    main()
