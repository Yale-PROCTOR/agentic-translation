---
name: add-test-inputs
description: Add high-quality test vectors for C projects whose translated test workspace targets a shared library through per-case harnesses under test_vectors/inputs. Use when asked to improve shared-library test coverage by adding harness directories or argv/stdin JSON inputs.
---

# Add Test Inputs

Add focused shared-library test vectors without changing library source, generated coverage, runner scripts, or existing outputs. Each test case lives in `test_vectors/inputs/<case>/`, contains exactly one `.c` harness, and contains one or more JSON inputs shaped as `{"argv": list[str], "stdin": str}`.

## Workflow

1. Understand the library first.
   - Use `rg --files`, `find`, `rg`, or similar tools to locate `.c` and `.h` files.
   - Read the relevant `.c` and `.h` files to understand exported functions, required setup, meaningful argument combinations, boundary cases, and error paths.
   - Do not build the library or run ad hoc binaries directly.

2. Review existing test vectors.
   - Read every case directory under `test_vectors/inputs/`.
   - For each case, read the harness `.c` file and every JSON input in that directory.
   - If `test_vectors/cov/report.txt` and `test_vectors/cov/merged.txt` exist, read them.
   - Read `test_vectors/cov/show/<case>/<input>.txt` only when per-input coverage is useful.

3. Decide whether to add vectors.
   - If coverage and behavioral diversity are already strong, stop and tell the user in one sentence that the test vectors are already good.
   - Do not rely only on statement coverage. Prefer inputs that exercise meaningful API states, argument combinations, buffer sizes, boundary values, call ordering, libc-call variations, and error handling.
   - When exercising different sequences of library calls, prefer different harnesses.
   - When exercising the same sequence of library calls with different data, prefer one harness with multiple JSON input files.
   - For a simple library, only a few harnesses, possibly only one, can be sufficient.
   - Do not try to cover undefined behavior in merged coverage. It is acceptable to add a deliberate UB-triggering input when it documents an important boundary; the coverage script will exclude it from merged data.

4. Add only new test-vector files.
   - Reuse an existing case directory only when its harness already reaches the intended library behavior; in that case add only new JSON inputs there.
   - Otherwise add a new directory under `test_vectors/inputs/` with a concise descriptive name, exactly one `.c` harness, and one or more JSON inputs.
   - Never modify existing harnesses or existing JSON inputs.
   - Never modify `test_vectors/CMakeLists.txt`, `test_vectors/outputs/`, or `test_vectors/cov/` manually.
   - Use this exact JSON shape:

```json
{
  "argv": ["arg1"],
  "stdin": "input text\n"
}
```

5. Validate with sanitizers.
   - Run `./run_with_san.py`.
   - The script runs each harness executable from its case directory, and writes output JSON files under `test_vectors/outputs/<case>/`.
   - Continue only when the script exits successfully.

6. Validate coverage.
   - Run `./run_with_cov.py`.
   - Read `test_vectors/cov/report.txt` and `test_vectors/cov/merged.txt`.
   - Read relevant files under `test_vectors/cov/show/` when checking whether a new vector hit the intended library code.
   - If new vectors miss their intended paths, add more new files and rerun both scripts.

7. Finish concisely.
   - If no vectors were needed, say the existing test vectors are already good.
   - If vectors were added and validation passed, summarize the added case directories or JSON inputs in one sentence.

## Quality Bar

- Prefer vectors that make the harness call the shared library in meaningfully different ways.
- Use separate harnesses for meaningfully different call sequences, and JSON inputs for variations within one call sequence.
- Do not assert outputs in the harness.
- Make the harness print every relevant function output so it is captured in output JSON files, including return values and updated pointer arguments.
- Keep harnesses minimal and deterministic.
- Keep case and input names stable and descriptive, such as `parse-header/empty.json` or `init-twice/repeat-call.json`.
- Ensure each case directory still contains exactly one `.c` file.
