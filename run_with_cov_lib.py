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


def require_case_data(path: Path) -> dict[str, Any]:
    data = load_json(path)
    if not isinstance(data, dict):
        abort(f"{path}: expected JSON object")
    if not isinstance(data.get("argv"), list):
        abort(f"{path}: expected argv list")
    if not all(isinstance(arg, str) for arg in data["argv"]):
        abort(f"{path}: expected argv to contain only strings")
    if not isinstance(data.get("stdin"), str):
        abort(f"{path}: expected stdin string")
    if not isinstance(data.get("ub"), bool):
        abort(f"{path}: expected ub boolean")
    return data


def test_vectors_dir() -> Path:
    root = Path(__file__).resolve().parent / "test_vectors"
    if not root.is_dir():
        abort(f"{root}: test_vectors directory does not exist")
    if not (root / "CMakeLists.txt").is_file():
        abort(f"{root / 'CMakeLists.txt'}: file does not exist")
    if not (root / "outputs").is_dir():
        abort(f"{root / 'outputs'}: directory does not exist")
    return root


def output_case_dirs(root: Path) -> list[Path]:
    outputs_dir = root / "outputs"
    paths = sorted(path for path in outputs_dir.iterdir() if path.is_dir())
    if not paths:
        abort(f"{outputs_dir}: expected at least one test case subdirectory")
    return paths


def output_case_paths(path: Path) -> list[Path]:
    json_files = sorted(path.glob("*.json"))
    if not json_files:
        abort(f"{path}: expected at least one .json file")
    return json_files


def harness_path(root: Path, case_name: str) -> Path:
    path = root / "inputs" / case_name
    c_files = sorted(path.glob("*.c"))
    if len(c_files) != 1:
        abort(f"{path}: expected exactly one .c file, found {len(c_files)}")
    return c_files[0]


def shared_lib_path(root: Path) -> Path:
    lines = (root / "CMakeLists.txt").read_text().splitlines()
    in_cov = False
    for line in lines:
        stripped = line.strip()
        if stripped == "if(ENABLE_COV)":
            in_cov = True
            continue
        if in_cov and stripped == "endif()":
            break
        if in_cov and stripped.startswith('set(MYLIB_PATH "'):
            prefix = 'set(MYLIB_PATH "'
            suffix = '")'
            if not stripped.endswith(suffix):
                abort(f"{root / 'CMakeLists.txt'}: malformed MYLIB_PATH line")
            path = Path(stripped[len(prefix) : -len(suffix)])
            if not path.is_file():
                abort(f"{path}: shared library does not exist")
            return path
    abort(f"{root / 'CMakeLists.txt'}: ENABLE_COV MYLIB_PATH not found")


def is_fresh(output_path: Path, inputs: list[Path]) -> bool:
    if not output_path.exists():
        return False
    output_mtime = output_path.stat().st_mtime_ns
    return all(
        path.exists() and path.stat().st_mtime_ns <= output_mtime for path in inputs
    )


def run_case(exe_path: Path, data: dict[str, Any], raw_path: Path) -> None:
    env = os.environ.copy()
    env["LLVM_PROFILE_FILE"] = str(raw_path)
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        temp_exe = temp_path / exe_path.name
        shutil.copy2(exe_path, temp_exe)
        subprocess.run(
            [f"./{temp_exe.name}", *data["argv"]],
            input=data["stdin"].encode(),
            capture_output=True,
            env=env,
            cwd=temp_path,
            check=False,
        )


def show_coverage(
    exe_path: Path | None, lib_path: Path, profdata_path: Path, output_path: Path
) -> None:
    command = [
        "llvm-cov-20",
        "show",
        "-object",
        str(lib_path),
        f"-instr-profile={profdata_path}",
        "-show-line-counts-or-regions",
    ]
    if exe_path is not None:
        command.insert(2, str(exe_path))
    with output_path.open("w") as stdout:
        subprocess.run(
            command,
            check=True,
            stdout=stdout,
        )


def main() -> None:
    root = test_vectors_dir()
    lib_path = shared_lib_path(root)
    cases = [
        (case_dir, output_case_paths(case_dir)) for case_dir in output_case_dirs(root)
    ]
    try:
        subprocess.run(
            [
                "cmake",
                "-S",
                ".",
                "-B",
                "./build-cov",
                "-G",
                "Ninja",
                "-DCMAKE_C_COMPILER=clang-20",
                "-DENABLE_SAN=OFF",
                "-DENABLE_COV=ON",
                "-DENABLE_OPT=OFF",
            ],
            cwd=root,
            check=True,
        )
        subprocess.run(["cmake", "--build", "build-cov"], cwd=root, check=True)
    except subprocess.CalledProcessError as exc:
        abort(
            f"cmake configure/build for build-cov failed with exit code {exc.returncode}"
        )
    exe_dir = root / "build-cov" / "bin"
    cov_dir = root / "cov"
    raw_root = cov_dir / "raw"
    data_root = cov_dir / "data"
    show_root = cov_dir / "show"
    raw_root.mkdir(parents=True, exist_ok=True)
    data_root.mkdir(parents=True, exist_ok=True)
    show_root.mkdir(parents=True, exist_ok=True)
    raw_paths: list[Path] = []
    any_changed = False

    for case_dir, input_paths in cases:
        exe_path = exe_dir / case_dir.name
        if not exe_path.is_file():
            abort(f"{exe_path}: executable does not exist")
        harness = harness_path(root, case_dir.name)
        case_raw = raw_root / case_dir.name
        case_data = data_root / case_dir.name
        case_show = show_root / case_dir.name
        case_raw.mkdir(exist_ok=True)
        case_data.mkdir(exist_ok=True)
        case_show.mkdir(exist_ok=True)
        for output_path in input_paths:
            data = require_case_data(output_path)
            name = output_path.stem
            raw_path = case_raw / f"{name}.profraw"
            data_path = case_data / f"{name}.profdata"
            show_path = case_show / f"{name}.txt"
            deps = [output_path, harness, exe_path, lib_path]
            if is_fresh(raw_path, deps):
                print(f"Keeping {raw_path}...")
            else:
                print(f"Running {exe_path} with output {output_path}...")
                run_case(exe_path, data, raw_path)
                any_changed = True
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
            if is_fresh(show_path, [data_path, exe_path, lib_path]):
                print(f"Keeping {show_path}...")
            else:
                show_coverage(exe_path, lib_path, data_path, show_path)
                any_changed = True
            if not data["ub"]:
                raw_paths.append(raw_path)

    if not raw_paths:
        abort(f"{root / 'outputs'}: no non-UB runs found")

    merged_path = cov_dir / "merged.profdata"
    merged_show_path = cov_dir / "merged.txt"
    report_path = cov_dir / "report.txt"
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
    if any_changed or not is_fresh(merged_show_path, [merged_path, lib_path]):
        show_coverage(None, lib_path, merged_path, merged_show_path)
    else:
        print(f"Keeping {merged_show_path}...")
    if any_changed or not is_fresh(report_path, [merged_path, lib_path]):
        with report_path.open("w") as stdout:
            subprocess.run(
                [
                    "llvm-cov-20",
                    "report",
                    "-object",
                    str(lib_path),
                    f"-instr-profile={merged_path}",
                ],
                check=True,
                stdout=stdout,
            )
    else:
        print(f"Keeping {report_path}...")


if __name__ == "__main__":
    main()
