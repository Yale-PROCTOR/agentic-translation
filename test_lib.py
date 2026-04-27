#!/usr/bin/env python3
import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

RUN_TIMEOUT_SECONDS = 60


def help_text(program: str) -> str:
    return f"""Usage:
  {program} build
  {program} run
  {program} perf
  {program} help
  {program} -h
  {program} --help

Modes:
  build   Run `cargo build` and print JSON with stderr and exit_code.
  run     Build debug Rust, compile harnesses without optimization, and print JSON with measured output, expected output, and success.
  perf    Build release Rust, compile harnesses with optimization, run every test vector once per expected runtime, and print JSON with correctness and runtime ratios.
  help    Print this message.
"""


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("mode", nargs="?", choices=("build", "run", "perf", "help"))
    parser.add_argument("-h", "--help", action="store_true", dest="show_help")
    args = parser.parse_args(argv)
    if args.show_help or args.mode in (None, "help"):
        print(help_text(Path(sys.argv[0]).name))
        raise SystemExit(0)
    return args


def command_result(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def test_cases(root: Path) -> list[tuple[Path, Path, list[Path]]]:
    cases = []
    for case_dir in sorted((root / "test_vectors" / "inputs").iterdir()):
        if not case_dir.is_dir():
            continue
        harnesses = sorted(case_dir.glob("*.c"))
        if len(harnesses) != 1:
            raise ValueError(f"{case_dir}: expected exactly one .c file")
        inputs = sorted(case_dir.glob("*.json"))
        if not inputs:
            raise ValueError(f"{case_dir}: expected at least one .json file")
        cases.append((case_dir, harnesses[0], inputs))
    return cases


def expected_output(data: dict[str, Any]) -> dict[str, Any]:
    expected = {
        "stdout": data["stdout"],
        "stderr": data["stderr"],
        "exitcode": data["exitcode"],
    }
    if "log" in data:
        expected["log"] = data["log"]
    return expected


def harness_build_dir(opt: bool) -> str:
    return "build-opt" if opt else "build-run"


def configure_harnesses(root: Path, opt: bool) -> None:
    build_dir = harness_build_dir(opt)
    subprocess.run(
        [
            "cmake",
            "-S",
            "./test_vectors",
            "-B",
            f"./test_vectors/{build_dir}",
            "-G",
            "Ninja",
            "-DCMAKE_C_COMPILER=clang-20",
            f"-DENABLE_OPT={'ON' if opt else 'OFF'}",
        ],
        cwd=root,
        check=True,
    )
    subprocess.run(
        ["cmake", "--build", f"./test_vectors/{build_dir}"],
        cwd=root,
        check=True,
    )


def read_log(path: Path) -> str:
    if not path.is_file():
        return ""
    return path.read_text()


def run_one(exe: Path, data: dict[str, Any]) -> dict[str, Any]:
    start = time.perf_counter()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        temp_exe = temp_path / exe.name
        shutil.copy2(exe, temp_exe)
        try:
            result = subprocess.run(
                [f"./{temp_exe.name}", *data["argv"]],
                input=data["stdin"].encode(),
                capture_output=True,
                cwd=temp_path,
                timeout=RUN_TIMEOUT_SECONDS,
            )
            elapsed = time.perf_counter() - start
            return {
                "stdout": result.stdout.decode("latin-1"),
                "stderr": result.stderr.decode("latin-1"),
                "exitcode": result.returncode,
                "log": read_log(temp_path / "test-vector-output.log"),
                "runtime": elapsed,
            }
        except subprocess.TimeoutExpired as error:
            elapsed = time.perf_counter() - start
            return {
                "stdout": (error.stdout or b"").decode("latin-1"),
                "stderr": (error.stderr or b"").decode("latin-1"),
                "exitcode": None,
                "log": read_log(temp_path / "test-vector-output.log"),
                "runtime": elapsed,
            }


def success(result: dict[str, Any], expected: dict[str, Any]) -> bool:
    return all(result[key] == value for key, value in expected.items())


def build(root: Path, release: bool) -> dict[str, Any]:
    command = ["cargo", "build"]
    if release:
        command.append("--release")
    result = command_result(command, root / "translated_rust")
    return {"stderr": result.stderr, "exit_code": result.returncode}


def test_vector_name(case_dir: Path, input_path: Path) -> str:
    return f"{case_dir.name}/{input_path.name}"


def run(root: Path) -> list[dict[str, Any]]:
    configure_harnesses(root, opt=False)
    bin_dir = root / "test_vectors" / harness_build_dir(False) / "bin"
    results = []
    for case_dir, _, input_paths in test_cases(root):
        exe = bin_dir / case_dir.name
        for path in input_paths:
            data = load_json(path)
            result = run_one(exe, data)
            expected = expected_output(data)
            results.append(
                {
                    "test_vector": test_vector_name(case_dir, path),
                    "stdout": result["stdout"],
                    "stderr": result["stderr"],
                    "exitcode": result["exitcode"],
                    "log": result["log"],
                    "expected": expected,
                    "success": success(result, expected),
                }
            )
    return results


def perf(root: Path) -> list[dict[str, Any]]:
    configure_harnesses(root, opt=True)
    bin_dir = root / "test_vectors" / harness_build_dir(True) / "bin"
    results = []
    for case_dir, _, input_paths in test_cases(root):
        exe = bin_dir / case_dir.name
        for path in input_paths:
            data = load_json(path)
            runs = [run_one(exe, data) for _ in data["runtimes"]]
            first = runs[0]
            consistent = all(
                run["stdout"] == first["stdout"]
                and run["stderr"] == first["stderr"]
                and run["exitcode"] == first["exitcode"]
                and run["log"] == first["log"]
                for run in runs[1:]
            )
            if not consistent:
                results.append(
                    {
                        "test_vector": test_vector_name(case_dir, path),
                        "status": "inconsistent",
                        "runs": runs,
                    }
                )
                continue
            expected = expected_output(data)
            average_runtime = sum(run["runtime"] for run in runs) / len(runs)
            results.append(
                {
                    "test_vector": test_vector_name(case_dir, path),
                    "stdout": first["stdout"],
                    "stderr": first["stderr"],
                    "exitcode": first["exitcode"],
                    "log": first["log"],
                    "average_runtime": average_runtime,
                    "expected": expected | {"average_runtime": data["average_runtime"]},
                    "success": success(first, expected),
                    "ratio": average_runtime / data["average_runtime"],
                }
            )
    return results


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    root = Path(__file__).resolve().parent
    if args.mode == "build":
        result = build(root, release=False)
        print(json.dumps({"mode": args.mode, "result": result}, indent=2))
        return 1 if result["exit_code"] else 0

    build_result = build(root, release=args.mode == "perf")
    if build_result["exit_code"]:
        print(json.dumps({"mode": args.mode, "build": build_result}, indent=2))
        return 1

    try:
        results = run(root) if args.mode == "run" else perf(root)
    except subprocess.CalledProcessError as error:
        print(
            json.dumps(
                {
                    "mode": args.mode,
                    "cmake": {"command": error.cmd, "exit_code": error.returncode},
                },
                indent=2,
            )
        )
        return 1
    print(json.dumps({"mode": args.mode, "results": results}, indent=2))
    failed = any(result.get("success") is False for result in results)
    inconsistent = any(result.get("status") == "inconsistent" for result in results)
    return 1 if failed or inconsistent else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
