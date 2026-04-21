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


def require_output_data(path: Path) -> dict[str, Any]:
    data = load_json(path)
    if not isinstance(data, dict):
        abort(f"{path}: expected JSON object")
    if not isinstance(data.get("ub"), bool):
        abort(f"{path}: expected ub boolean")
    return data


def test_vectors_dir() -> Path:
    root = Path(__file__).resolve().parent / "test_vectors"
    if not root.is_dir():
        abort(f"{root}: test_vectors directory does not exist")
    if not (root / "CMakeLists.txt").is_file():
        abort(f"{root / 'CMakeLists.txt'}: file does not exist")
    if not (root / "inputs").is_dir():
        abort(f"{root / 'inputs'}: directory does not exist")
    if not (root / "outputs").is_dir():
        abort(f"{root / 'outputs'}: directory does not exist")
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


def run_case(exe_path: Path, work_dir: Path, input_path: Path, raw_path: Path) -> None:
    data = require_input_data(input_path)
    env = os.environ.copy()
    env["LLVM_PROFILE_FILE"] = str(raw_path)
    subprocess.run(
        [str(exe_path.resolve()), *data["argv"]],
        input=data["stdin"].encode(),
        capture_output=True,
        env=env,
        cwd=work_dir,
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
    if cov_dir.exists():
        shutil.rmtree(cov_dir)
    raw_root.mkdir(parents=True)
    data_root.mkdir()
    show_root.mkdir()
    raw_paths: list[Path] = []

    for case_dir, input_paths in cases:
        exe_path = exe_dir / case_dir.name
        if not exe_path.is_file():
            abort(f"{exe_path}: executable does not exist")
        case_raw = raw_root / case_dir.name
        case_data = data_root / case_dir.name
        case_show = show_root / case_dir.name
        case_raw.mkdir()
        case_data.mkdir()
        case_show.mkdir()
        output_dir = root / "outputs" / case_dir.name
        if not output_dir.is_dir():
            abort(f"{output_dir}: output directory does not exist")
        for input_path in input_paths:
            print(f"Running {exe_path} with input {input_path}...")
            name = input_path.stem
            raw_path = case_raw / f"{name}.profraw"
            data_path = case_data / f"{name}.profdata"
            show_path = case_show / f"{name}.txt"
            run_case(exe_path, case_dir, input_path, raw_path)
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
            show_coverage(exe_path, lib_path, data_path, show_path)
            output_path = output_dir / input_path.name
            if not require_output_data(output_path)["ub"]:
                raw_paths.append(raw_path)

    if not raw_paths:
        abort(f"{root / 'outputs'}: no non-UB runs found")

    merged_path = cov_dir / "merged.profdata"
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
    show_coverage(None, lib_path, merged_path, cov_dir / "merged.txt")
    with (cov_dir / "report.txt").open("w") as stdout:
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


if __name__ == "__main__":
    main()
