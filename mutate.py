#!/usr/bin/env python3
import copy
import json
import re
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

Mutation = tuple[Callable[[str], bool], Callable[[str], str]]


def abort(message: str) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(1)


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        abort(f"{path}: invalid JSON: {exc}")


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


def is_number_arg(value: str) -> bool:
    return re.fullmatch(r"\d+|\d+\.\d+", value) is not None


def any_arg(value: str) -> bool:
    return True


MUTATIONS: tuple[Mutation, ...] = (
    (is_number_arg, lambda value: f"+{value}"),
    (is_number_arg, lambda value: f"-{value}"),
    (is_number_arg, lambda value: f"0{value}"),
    (is_number_arg, lambda value: f"a{value}"),
    (any_arg, lambda value: f" {value}"),
    (any_arg, lambda value: f"\n{value}"),
    (is_number_arg, lambda value: f"{value}a"),
    (any_arg, lambda value: f"{value} "),
    (any_arg, lambda value: f"{value}\n"),
)


def mutated_strings(value: str) -> list[str]:
    return [mutation(value) for applies, mutation in MUTATIONS if applies(value)]


def mutated_lists(values: list[str]) -> list[list[str]]:
    return [
        values[:index] + values[index + 1 :]
        for index in range(len(values))
    ] + [
        [*values, "a"]
    ] + [
        values[:index] + [values[index + 1], values[index]] + values[index + 2 :]
        for index in range(len(values) - 1)
    ]


def mutants(data: dict[str, Any]) -> list[dict[str, Any]]:
    result = []
    for index, value in enumerate(data["argv"]):
        for mutated in mutated_strings(value):
            mutant = copy.deepcopy(data)
            mutant["argv"][index] = mutated
            result.append(mutant)

    for mutated in mutated_lists(data["argv"]):
        mutant = copy.deepcopy(data)
        mutant["argv"] = mutated
        result.append(mutant)

    stdin = data["stdin"]
    if not stdin:
        return result

    mutant = copy.deepcopy(data)
    midpoint = len(stdin) // 2
    mutant["stdin"] = f"{stdin[:midpoint]}\x00{stdin[midpoint:]}"
    result.append(mutant)

    seen: set[str] = set()
    parts = stdin.split()
    for index, value in enumerate(parts):
        for mutated in mutated_strings(value):
            mutated_parts = parts.copy()
            mutated_parts[index] = mutated
            mutated_stdin = " ".join(mutated_parts)
            if mutated_stdin in seen:
                continue
            seen.add(mutated_stdin)
            mutant = copy.deepcopy(data)
            mutant["stdin"] = mutated_stdin
            result.append(mutant)

    for mutated in mutated_lists(parts):
        mutated_stdin = " ".join(mutated)
        if mutated_stdin in seen:
            continue
        seen.add(mutated_stdin)
        mutant = copy.deepcopy(data)
        mutant["stdin"] = mutated_stdin
        result.append(mutant)
    return result


def write_mutants(path: Path) -> None:
    for index, mutant in enumerate(mutants(input_data(path)), start=1):
        output_path = path.with_name(f"{path.stem}-mutated-{index}.json")
        output_path.write_text(json.dumps(mutant))


def main(argv: list[str]) -> int:
    if not argv:
        abort("usage: mutate.py INPUT.json [INPUT.json ...]")

    for arg in argv:
        write_mutants(Path(arg))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
