---
name: add-test-inputs
description: Add high-quality JSON test inputs for C projects that build a single executable and are tested only through argv and stdin. Use when asked to improve binary test coverage by adding files under an inputs directory, especially when run_with_san.py and run_with_cov.py are available.
---

# Add Test Inputs

## Overview

Add focused test inputs for a C binary without changing source, scripts, generated coverage, or existing inputs. Each input must be a JSON object with `argv: list[str]` and `stdin: str`.

## Workflow

1. Understand the program first.
   - Use `rg --files`, `find`, `rg`, or similar tools to locate `.c` and `.h` files.
   - Read the relevant source carefully enough to understand accepted argv forms, stdin parsing, error paths, edge cases, and meaningful state combinations.
   - Do not build or run the binary directly.

2. Review existing tests.
   - Read every JSON file under `inputs/`. The directory may be empty.
   - If inputs already exist, read `cov/report.txt` for aggregate coverage and `cov/merged.txt` for covered and uncovered lines.
   - Use `cov/show/*.txt` only when per-input coverage helps explain what a test covers.

3. Decide whether to add inputs.
   - If coverage and behavioral diversity are already excellent, stop and tell the user in one sentence that the inputs are already good.
   - Do not rely only on statement coverage. Prefer inputs that exercise meaningful parser branches, option combinations, boundary values, array positions, library-call variations, and error handling.
   - Do not try to cover undefined behavior in merged coverage. It is acceptable to add a deliberate UB-triggering input when it documents an important boundary; the coverage script will exclude it from merged data.

4. Add only new input JSON files.
   - Write new files under `inputs/` with concise descriptive names.
   - Never delete or modify existing inputs.
   - Never modify source code, scripts, `outputs/`, or `cov/` manually.
   - If `inputs/` is empty, focus on inputs that cover the main logic rather than edge cases and error cases, because generated mutations will cover many edge cases.
   - If `inputs/` contains existing inputs with mutations, carefully think about edge cases not covered by the mutations.
   - Use this exact shape. `argv` contains only arguments after the executable path:

```json
{
  "argv": ["arg1"],
  "stdin": "input text\n"
}
```

5. Generate mutations for the added inputs.
   - Run `./mutate.py` with the new input JSON files, for example `./mutate.py inputs/a.json inputs/b.json`.
   - This automatically generates mutations for the specified input JSON files, typically by appending, prepending, inserting, or removing characters to/from the argv string or stdin string.
   - Use mutations to cover many edge cases without writing all of them manually.

6. Validate with sanitizers.
   - Run `./run_with_san.py`.
   - The script records stdout, stderr, and exit code under `outputs/`; do not inspect or edit outputs unless needed to diagnose script failure.
   - Continue only when the script exits successfully.

7. Validate coverage.
   - Run `./run_with_cov.py`.
   - Read `cov/report.txt` and `cov/merged.txt`.
   - Read relevant files under `cov/show/` when checking whether a specific new input behaved as intended.
   - If new inputs miss their intended paths, add or adjust only the new input JSON files and rerun both scripts.

8. Finish concisely.
   - If no inputs were needed, say the existing inputs are already good.
   - If inputs were added and validation passed, summarize the added inputs in one sentence.

## Quality Bar

- Prefer a small set of high-value inputs over broad enumeration.
- Include negative and boundary cases when they reveal distinct behavior.
- Keep names stable and descriptive, such as `empty-stdin.json`, `unknown-option.json`, or `large-index.json`.
- Ensure JSON strings preserve intended newlines and bytes representable as text.
