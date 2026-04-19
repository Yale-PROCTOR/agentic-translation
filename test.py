#!/usr/bin/env python3
import argparse
import json
import subprocess
import sys
import time
import tomllib
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
  run     Run every test vector and print JSON with measured output, expected output, and success.
  perf    Build with `--release`, run every test vector once per expected runtime, and print JSON with correctness and runtime ratios.
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


def binary_name(rust_dir: Path) -> str:
    cargo = tomllib.loads((rust_dir / "Cargo.toml").read_text())
    package_name = cargo["package"]["name"]
    bins = cargo.get("bin", [])
    return bins[0]["name"] if bins else package_name


def executable(root: Path, release: bool) -> Path:
    profile = "release" if release else "debug"
    return (
        root
        / "translated_rust"
        / "target"
        / profile
        / binary_name(root / "translated_rust")
    )


def test_vectors(root: Path) -> list[Path]:
    return sorted((root / "test_vectors").glob("*.json"))


def expected_output(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "stdout": data["stdout"],
        "stderr": data["stderr"],
        "exitcode": data["exitcode"],
    }


def run_one(exe: Path, data: dict[str, Any]) -> dict[str, Any]:
    start = time.perf_counter()
    try:
        result = subprocess.run(
            [str(exe), *data["argv"]],
            input=data["stdin"].encode(),
            capture_output=True,
            timeout=RUN_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as error:
        elapsed = time.perf_counter() - start
        return {
            "stdout": (error.stdout or b"").decode("latin-1"),
            "stderr": (error.stderr or b"").decode("latin-1"),
            "exitcode": None,
            "runtime": elapsed,
        }
    elapsed = time.perf_counter() - start
    return {
        "stdout": result.stdout.decode("latin-1"),
        "stderr": result.stderr.decode("latin-1"),
        "exitcode": result.returncode,
        "runtime": elapsed,
    }


def success(result: dict[str, Any], expected: dict[str, Any]) -> bool:
    return (
        result["stdout"] == expected["stdout"]
        and result["stderr"] == expected["stderr"]
        and result["exitcode"] == expected["exitcode"]
    )


def build(root: Path, release: bool) -> dict[str, Any]:
    command = ["cargo", "build"]
    if release:
        command.append("--release")
    result = command_result(command, root / "translated_rust")
    return {
        "stderr": result.stderr,
        "exit_code": result.returncode,
    }


def run(root: Path) -> list[dict[str, Any]]:
    exe = executable(root, release=False)
    results = []
    for path in test_vectors(root):
        data = load_json(path)
        result = run_one(exe, data)
        expected = expected_output(data)
        results.append(
            {
                "test_vector": path.name,
                "stdout": result["stdout"],
                "stderr": result["stderr"],
                "exitcode": result["exitcode"],
                "expected": expected,
                "success": success(result, expected),
            }
        )
    return results


def perf(root: Path) -> list[dict[str, Any]]:
    exe = executable(root, release=True)
    results = []
    for path in test_vectors(root):
        data = load_json(path)
        runs = [run_one(exe, data) for _ in data["runtimes"]]
        first = runs[0]
        consistent = all(
            run["stdout"] == first["stdout"]
            and run["stderr"] == first["stderr"]
            and run["exitcode"] == first["exitcode"]
            for run in runs[1:]
        )
        if not consistent:
            results.append(
                {"test_vector": path.name, "status": "inconsistent", "runs": runs}
            )
            continue
        expected = expected_output(data)
        average_runtime = sum(run["runtime"] for run in runs) / len(runs)
        results.append(
            {
                "test_vector": path.name,
                "stdout": first["stdout"],
                "stderr": first["stderr"],
                "exitcode": first["exitcode"],
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

    results = run(root) if args.mode == "run" else perf(root)
    print(json.dumps({"mode": args.mode, "results": results}, indent=2))
    failed = any(result.get("success") is False for result in results)
    inconsistent = any(result.get("status") == "inconsistent" for result in results)
    return 1 if failed or inconsistent else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
