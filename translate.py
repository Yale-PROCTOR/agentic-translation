#!/usr/bin/env python3
import json
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

START_MESSAGE = "This is the beginning of the whole translation process."
RETRY_DELAY_SECONDS = 60
MODEL = "gpt-5.4"
REASONING = "model_reasoning_effort = medium"

CMAKE_APPEND = """
option(ENABLE_SAN "Enable sanitizers" OFF)
option(ENABLE_COV "Enable code coverage" OFF)
option(ENABLE_OPT "Enable optimization" OFF)

if(ENABLE_SAN)
    message(STATUS "Sanitizers enabled")
    get_property(_translation_targets DIRECTORY PROPERTY BUILDSYSTEM_TARGETS)
    foreach(_translation_target IN LISTS _translation_targets)
        get_target_property(_translation_type ${_translation_target} TYPE)
        if(_translation_type MATCHES "^(EXECUTABLE|STATIC_LIBRARY|SHARED_LIBRARY|MODULE_LIBRARY|OBJECT_LIBRARY)$")
            target_compile_options(${_translation_target} PRIVATE
                -g
                -fsanitize=address,undefined,float-divide-by-zero,local-bounds
                -fsanitize-address-use-after-scope
                -fsanitize-address-use-after-return=always
                -fno-sanitize-recover=all
            )
        endif()
        if(_translation_type MATCHES "^(EXECUTABLE|SHARED_LIBRARY|MODULE_LIBRARY)$")
            target_link_options(${_translation_target} PRIVATE
                -fsanitize=address,undefined,float-divide-by-zero,local-bounds
            )
        endif()
    endforeach()
endif()

if(ENABLE_COV)
    message(STATUS "Code coverage enabled")
    get_property(_translation_targets DIRECTORY PROPERTY BUILDSYSTEM_TARGETS)
    foreach(_translation_target IN LISTS _translation_targets)
        get_target_property(_translation_type ${_translation_target} TYPE)
        if(_translation_type MATCHES "^(EXECUTABLE|STATIC_LIBRARY|SHARED_LIBRARY|MODULE_LIBRARY|OBJECT_LIBRARY)$")
            target_compile_options(${_translation_target} PRIVATE
                -g
                -fprofile-instr-generate
                -fcoverage-mapping
            )
        endif()
        if(_translation_type MATCHES "^(EXECUTABLE|SHARED_LIBRARY|MODULE_LIBRARY)$")
            target_link_options(${_translation_target} PRIVATE
                -fprofile-instr-generate
            )
        endif()
    endforeach()
endif()

if(ENABLE_OPT)
    message(STATUS "Optimization enabled")
    get_property(_translation_targets DIRECTORY PROPERTY BUILDSYSTEM_TARGETS)
    foreach(_translation_target IN LISTS _translation_targets)
        get_target_property(_translation_type ${_translation_target} TYPE)
        if(_translation_type MATCHES "^(EXECUTABLE|STATIC_LIBRARY|SHARED_LIBRARY|MODULE_LIBRARY|OBJECT_LIBRARY)$")
            target_compile_options(${_translation_target} PRIVATE
                -O3
            )
        endif()
    endforeach()
endif()
"""


class Abort(Exception):
    pass


def abort(message: str) -> None:
    raise Abort(message)


def run(command: list[str], cwd: Path) -> None:
    result = subprocess.run(command, cwd=cwd, text=True, capture_output=True)
    if result.returncode == 0:
        return

    parts = [f"{' '.join(command)} failed with exit code {result.returncode}"]
    if result.stdout:
        parts.append(f"stdout:\n{result.stdout}")
    if result.stderr:
        parts.append(f"stderr:\n{result.stderr}")
    abort("\n".join(parts))


def configure(proj_dir: Path, build_dir: str, san: bool, cov: bool, opt: bool) -> None:
    build_path = proj_dir / build_dir
    query_dir = build_path / ".cmake" / "api" / "v1" / "query"
    query_dir.mkdir(parents=True)
    (query_dir / "codemodel-v2").touch()
    run(
        [
            "cmake",
            "-S",
            ".",
            "-B",
            f"./{build_dir}",
            "-G",
            "Ninja",
            "-DCMAKE_C_COMPILER=clang-20",
            f"-DENABLE_SAN={'ON' if san else 'OFF'}",
            f"-DENABLE_COV={'ON' if cov else 'OFF'}",
            f"-DENABLE_OPT={'ON' if opt else 'OFF'}",
        ],
        cwd=proj_dir,
    )
    check_artifacts(build_path)


def build(proj_dir: Path, build_dir: str) -> None:
    run(["cmake", "--build", build_dir], cwd=proj_dir)


def input_json_files(inputs_dir: Path) -> set[Path]:
    return set(inputs_dir.glob("*.json"))


def print_result_error(
    result: subprocess.CompletedProcess[str], command: list[str]
) -> None:
    print(
        f"{' '.join(command)} failed with exit code {result.returncode}",
        file=sys.stderr,
    )
    if result.stdout:
        print(f"stdout:\n{result.stdout}", file=sys.stderr)


def run_testgen_codex(proj_dir: Path) -> None:
    command = [
        "codex",
        "exec",
        "-m",
        MODEL,
        "-c",
        REASONING,
        "--full-auto",
        "-C",
        str(proj_dir),
        "$add-test-inputs Add test inputs for this project",
    ]
    while True:
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=None, text=True)
        if result.returncode == 0:
            return
        print_result_error(result, command)
        time.sleep(RETRY_DELAY_SECONDS)


def add_test_inputs(proj_dir: Path) -> None:
    inputs_dir = proj_dir / "inputs"
    for _ in range(10):
        before = input_json_files(inputs_dir)
        run_testgen_codex(proj_dir)
        after = input_json_files(inputs_dir)
        if not after - before:
            break


def format_messages(messages: list[tuple[str, str]]) -> str:
    return "\n".join(f"{role}: {message}" for role, message in messages)


def parse_json_output(stdout: str) -> dict[str, Any]:
    text = stdout.strip()
    if not text:
        raise ValueError("empty stdout")
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        decoder = json.JSONDecoder()
        for index, char in reversed(list(enumerate(text))):
            if char != "{":
                continue
            try:
                value, end = decoder.raw_decode(text[index:])
            except json.JSONDecodeError:
                continue
            if index + end == len(text):
                break
        else:
            raise ValueError("could not find final JSON object in stdout") from None
    if not isinstance(value, dict):
        raise ValueError("stdout JSON is not an object")
    return value


def run_agent_codex(
    prompt: str,
    schema_path: Path,
    workspace: Path,
    validator: Callable[[dict[str, Any]], Any],
) -> dict[str, Any]:
    command = [
        "codex",
        "exec",
        "-m",
        MODEL,
        "-c",
        REASONING,
        "--full-auto",
        "--output-schema",
        str(schema_path),
        "-C",
        str(workspace),
        prompt,
    ]
    while True:
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=None, text=True)
        if result.returncode != 0:
            print_result_error(result, command)
        else:
            try:
                payload = parse_json_output(result.stdout)
                validator(payload)
                return payload
            except ValueError as error:
                print(f"codex output invalid: {error}", file=sys.stderr, flush=True)
                if result.stdout:
                    print(f"stdout:\n{result.stdout}", file=sys.stderr)
        time.sleep(RETRY_DELAY_SECONDS)


def planner_prompt(previous_round: list[tuple[str, str]] | None) -> str:
    message = (
        START_MESSAGE
        if previous_round is None
        else f"Messages from previous sessions:\n{format_messages(previous_round)}"
    )
    return f"$translation-planner As a Planner, plan the translation. {message}"


def executor_prompt(messages: list[tuple[str, str]]) -> str:
    return (
        "$translation-executor As an Executor, execute the translation following the messages:\n"
        f"{format_messages(messages)}"
    )


def reviewer_prompt(messages: list[tuple[str, str]]) -> str:
    return (
        "$translation-reviewer As a Reviewer, review the translation based on the messages:\n"
        f"{format_messages(messages)}"
    )


def unwrap_message(message: str) -> str:
    while True:
        try:
            value = json.loads(message.strip())
        except json.JSONDecodeError:
            return message
        if not isinstance(value, dict):
            return message
        inner = value.get("message")
        if not isinstance(inner, str):
            return message
        message = inner


def require_message(payload: dict[str, Any], role: str) -> str:
    message = payload.get("message")
    if not isinstance(message, str):
        raise ValueError(f"{role} response missing string message")
    return unwrap_message(message)


def require_review(payload: dict[str, Any]) -> tuple[bool, str]:
    ok = payload.get("ok")
    message = payload.get("message")
    if not isinstance(ok, bool) or not isinstance(message, str):
        raise ValueError("Reviewer response missing ok/message")
    return ok, unwrap_message(message)


def print_message(role: str, message: str) -> None:
    print(f"\033[1;36m{role}: {message}\033[0m", flush=True)


def write_schema(path: Path, properties: dict[str, dict[str, str]]) -> None:
    path.write_text(
        json.dumps(
            {
                "type": "object",
                "properties": properties,
                "required": list(properties),
                "additionalProperties": False,
            }
        )
    )


def write_agent_schemas(workspace: Path) -> tuple[Path, Path, Path]:
    planner_schema = workspace / ".planner.output.json"
    executor_schema = workspace / ".executor.output.json"
    reviewer_schema = workspace / ".reviewer.output.json"
    message = {"message": {"type": "string"}}
    write_schema(planner_schema, message)
    write_schema(executor_schema, message)
    write_schema(
        reviewer_schema,
        {"ok": {"type": "boolean"}, "message": {"type": "string"}},
    )
    return planner_schema, executor_schema, reviewer_schema


def orchestrate_translation(workspace: Path) -> None:
    planner_schema, executor_schema, reviewer_schema = write_agent_schemas(workspace)
    previous_round: list[tuple[str, str]] | None = None
    while True:
        planner = require_message(
            run_agent_codex(
                planner_prompt(previous_round),
                planner_schema,
                workspace,
                lambda payload: require_message(payload, "Planner"),
            ),
            "Planner",
        )
        print_message("Planner", planner)
        if not planner:
            return
        current_round = [("Planner", planner)]
        while True:
            executor = require_message(
                run_agent_codex(
                    executor_prompt(current_round),
                    executor_schema,
                    workspace,
                    lambda payload: require_message(payload, "Executor"),
                ),
                "Executor",
            )
            current_round.append(("Executor", executor))
            print_message("Executor", executor)
            reviewer_ok, reviewer = require_review(
                run_agent_codex(
                    reviewer_prompt(current_round),
                    reviewer_schema,
                    workspace,
                    require_review,
                )
            )
            current_round.append(("Reviewer", reviewer))
            print_message("Reviewer", reviewer)
            if reviewer_ok:
                previous_round = current_round
                break


def load_json(path: Path) -> Any:
    return json.loads(path.read_text())


def extract_archive(archive: Path, proj_dir: Path) -> None:
    with tarfile.open(archive) as tar:
        tar.extractall(proj_dir)


def remove_ub_outputs(outputs_dir: Path) -> None:
    for output_path in outputs_dir.glob("*.json"):
        if load_json(output_path)["ub"]:
            output_path.unlink()


def executable_artifact(build_path: Path) -> Path:
    reply_dir = build_path / ".cmake" / "api" / "v1" / "reply"
    index_path = next(reply_dir.glob("index-*.json"))
    index = load_json(index_path)
    codemodel_file = index["reply"]["codemodel-v2"]["jsonFile"]
    codemodel = load_json(reply_dir / codemodel_file)
    executables: list[Path] = []
    shared_libs: list[Path] = []

    for config in codemodel["configurations"]:
        for target in config["targets"]:
            target_data = load_json(reply_dir / target["jsonFile"])
            target_type = target_data["type"]
            for artifact in target_data.get("artifacts", []):
                path = (build_path / artifact["path"]).resolve()
                if target_type == "EXECUTABLE":
                    executables.append(path)
                elif target_type == "SHARED_LIBRARY":
                    shared_libs.append(path)

    if len(executables) != 1 or shared_libs:
        abort(
            f"{build_path}: expected exactly one executable and no shared libraries; "
            f"found {len(executables)} executable(s) and {len(shared_libs)} shared library artifact(s)"
        )
    return executables[0]


def check_artifacts(build_path: Path) -> None:
    executable_artifact(build_path)


def timed_run(exe: Path, data: dict[str, Any]) -> float:
    start = time.perf_counter_ns()
    subprocess.run(
        [str(exe), *data["argv"]],
        input=data["stdin"].encode(),
        capture_output=True,
    )
    return (time.perf_counter_ns() - start) / 1_000_000_000


def record_runtimes(proj_dir: Path) -> None:
    exe = executable_artifact(proj_dir / "build-opt")
    for output_path in (proj_dir / "outputs").glob("*.json"):
        data = load_json(output_path)
        runtimes = [timed_run(exe, data)]
        if runtimes[0] < 5:
            extra_runs = int(min(10, 10 / runtimes[0])) - 1
        else:
            extra_runs = 1
        runtimes.extend(timed_run(exe, data) for _ in range(extra_runs))
        data["runtimes"] = runtimes
        data["average_runtime"] = sum(runtimes) / len(runtimes)
        output_path.write_text(json.dumps(data))


def create_rust_project(proj_dir: Path, executable_name: str) -> None:
    src_dir = proj_dir / "src"
    bin_dir = src_dir / "bin"
    bin_dir.mkdir(parents=True)
    (proj_dir / "Cargo.toml").write_text(
        "\n".join(
            [
                "[package]",
                f'name = "{executable_name}"',
                'edition = "2024"',
                "",
                "[workspace]",
                "",
                "[dependencies]",
                'bytemuck = "1.25.0"',
                'lazy_static = "1.5.0"',
                'xj_scanf = "0.2.2"',
                "",
            ]
        )
    )
    (proj_dir / "rust-toolchain").write_text("nightly-2025-11-11\n")
    (bin_dir / f"{executable_name}.rs").write_text("fn main() {}\n")
    (src_dir / "lib.rs").write_text("")
    (proj_dir / ".gitignore").write_text("/target\n")


def write_translation_workspace(workspace: Path, root_dir: Path) -> None:
    shutil.copytree(root_dir / "skills-translation", workspace / ".codex" / "skills")
    shutil.copy2(root_dir / "AGENTS_TRANSLATION.md", workspace / "AGENTS.md")
    shutil.copy2(root_dir / "test.py", workspace / "test.py")
    write_agent_schemas(workspace)
    text = (
        "This is the beginning of the whole translation process, "
        "and this file is empty yet.\n"
    )
    for name in ["EXECUTE.md", "PLAN.md", "REVIEW.md"]:
        (workspace / name).write_text(text)


def commit_initial_workspace(workspace: Path) -> None:
    run(
        [
            "git",
            "add",
            "c",
            "translated_rust",
            "test_vectors",
            "test.py",
            ".codex",
            "AGENTS.md",
            "EXECUTE.md",
            "PLAN.md",
            "REVIEW.md",
            ".planner.output.json",
            ".executor.output.json",
            ".reviewer.output.json",
        ],
        cwd=workspace,
    )
    run(
        [
            "git",
            "-c",
            "user.name=Codex",
            "-c",
            "user.email=codex@example.com",
            "commit",
            "-m",
            "initial commit",
        ],
        cwd=workspace,
    )


def main() -> None:
    root_dir = Path(__file__).resolve().parent
    no_codex = "--no-codex" in sys.argv[1:]
    args = [arg for arg in sys.argv[1:] if arg != "--no-codex"]
    archive = Path(args[0])
    output_path = Path(args[1])
    archive_name = archive.name.removesuffix(".tar.gz")
    workspace = Path(
        tempfile.mkdtemp(prefix="tmp-", suffix=f"-{archive_name}", dir=".")
    )
    archive_dir = workspace / archive_name
    try:
        run(["git", "init"], cwd=workspace)
        archive_dir.mkdir()

        extract_archive(archive, archive_dir)
        testgen_dir = archive_dir / "test_case"
        if not testgen_dir.exists():
            testgen_dir.mkdir()
            for path in list(archive_dir.iterdir()):
                if path == testgen_dir:
                    continue
                shutil.move(str(path), testgen_dir / path.name)

        (testgen_dir / "inputs").mkdir()
        (testgen_dir / "outputs").mkdir()
        shutil.copy2(root_dir / "run_with_cov.py", testgen_dir)
        shutil.copy2(root_dir / "run_with_san.py", testgen_dir)
        shutil.copy2(root_dir / "mutate.py", testgen_dir)
        (testgen_dir / "CMakeLists.txt").open("a").write(CMAKE_APPEND)

        configure(testgen_dir, "build-san", san=True, cov=False, opt=False)
        configure(testgen_dir, "build-cov", san=False, cov=True, opt=False)
        build(testgen_dir, "build-san")
        build(testgen_dir, "build-cov")
        shutil.copytree(root_dir / "skills-testgen", testgen_dir / ".codex" / "skills")
        if not no_codex:
            add_test_inputs(testgen_dir)
        remove_ub_outputs(testgen_dir / "outputs")

        configure(testgen_dir, "build-opt", san=False, cov=False, opt=True)
        build(testgen_dir, "build-opt")
        executable_name = executable_artifact(testgen_dir / "build-opt").name
        record_runtimes(testgen_dir)

        shutil.copytree(testgen_dir / "outputs", workspace / "test_vectors")
        shutil.rmtree(archive_dir, ignore_errors=True)
        c_dir = workspace / "c"
        c_dir.mkdir()
        extract_archive(archive, c_dir)
        rust_dir = workspace / "translated_rust"
        rust_dir.mkdir()
        create_rust_project(rust_dir, executable_name)
        run(["cargo", "build"], cwd=rust_dir)
        write_translation_workspace(workspace, root_dir)
        commit_initial_workspace(workspace)

        if not no_codex:
            orchestrate_translation(workspace)

        if output_path.exists():
            shutil.rmtree(output_path)
        shutil.copytree(rust_dir, output_path)

    except Abort as exc:
        shutil.rmtree(workspace, ignore_errors=True)
        print(exc, file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
