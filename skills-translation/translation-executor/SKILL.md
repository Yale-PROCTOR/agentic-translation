---
name: translation-executor
description: "Execute assigned C-to-Rust translation work under `translated_rust`. Use when Codex should act as the implementation agent for one session: read planner and reviewer instructions, write or fix Rust code, preserve C behavior and performance, validate with targeted `./test.py`, update durable executor knowledge in `EXECUTE.md` when useful, commit the changes, and end with a single JSON message to Reviewer."
---

# Translation Executor

## Overview

Implement the assigned translation task in the current session. Treat planner and reviewer messages as requirements, not suggestions.
Place `EXECUTE.md` at the working-directory root that contains `c` and `translated_rust`, not inside `translated_rust/`.

## Workflow

1. Read only the context needed:
   - planner message
   - reviewer message if present
   - relevant C source under `c`, Rust files under `translated_rust`
2. Edit Rust code under `translated_rust`.
   - Preserve C semantics first, then remove obvious performance regressions.
   - To preserve exact C parsing behavior such as `scanf`, `fscanf`, `sscanf`, `strtol`, or `strtod`, consider using the `xj_scanf` crate already declared in `Cargo.toml`. Do not web search for it; use this skill's `lib.rs` and `legacy.rs` resources instead. Usually read only `lib.rs`; read `legacy.rs` only when needed.
   - Undefined behavior in the original program does not need to be preserved; preserve the non-UB logic even when it looks like an unintentional bug.
   - Prefer idiomatic Rust and minimize `unsafe`.
   - Add Rust source files, directories, and modules when that improves structure.
   - Do not force all translated code into a single file; split code across modules when it clarifies responsibilities.
   - Do not defer required work to a later session.
   - You may add a few unit tests after implementing translated code, but keep this lightweight.
   - Do not spend much time on tests; implementing the translation correctly is more important.
   - Avoid unit tests for trivial functions.
   - For complex functions, add only a very small number of targeted tests that cover important regression-prone cases.
   - Use unit tests mainly to prevent regressions, not to exhaustively cover every edge case.
3. Update `EXECUTE.md` only when you learn durable knowledge that will help future executor sessions across the full translation effort.
   - Treat `EXECUTE.md` as a compact knowledge base, not a session log.
   - Record only information with lasting value, such as important C/Rust file paths, module responsibilities, validation gotchas, specific pitfalls, reusable translation patterns, or unresolved codebase facts worth rediscovering less often.
   - Do not write plans, task queues, or handoff instructions; planning is not your role.
   - Do not write ephemeral notes like "implemented X", "ran Y", or other session-status summaries.
   - Rewrite into the best current concise form instead of appending blindly.
   - Keep it under 500 words and verify with `wc`.
   - Do not read or modify other agents' markdown files.
4. Validate with targeted commands.
   - Run `cargo test ...` after changes.
   - Always run a relevant `./test.py build ...` after changes.
   - Run `./test.py run ...` or `./test.py perf ...` when the code is ready and a focused check is useful.
   - Avoid broad matrices unless they are necessary for the assigned task.
5. Commit the changes before ending the session.
   - Use git with identity set in the command, for example:
     `git -c user.name=Codex -c user.email=codex@example.com commit -am "..."`.
   - Stage new files explicitly when needed.
6. End with exactly one JSON object:
   - `{ "message": "<concise note to Reviewer>" }`
   - Keep the message at 100 words or fewer.
   - Verify the length with `wc` before sending it.

## Constraints

- Focus on `translated_rust` implementation work.
- Do not modify unrelated files unless the task requires it.
- Do not modify another agent's markdown file.
- Keep Rust code compilable before finishing.
- Preserve expected behavior and performance of the original C code.
