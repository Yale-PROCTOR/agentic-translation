# Goal

Translate `c` from C to Rust in `translated_rust`.

## Validation

Use `test.py` to build, run, and measure the performance of the translated Rust code. For exact usage, run `./test.py --help`. Never modify `test.py` or `test_vectors`.

## Rust Constraints

`translated_rust/Cargo.toml` already includes `bytemuck`, `lazy_static`, and `xj_scanf`. Do not modify `Cargo.toml` and do not add any dependencies. You may use those existing libraries for safe transmutation, initializing global variables, and safe simulation of `scanf`, respectively.

The original program is sequential, and the translated program must remain sequential. Do not use concurrency to improve performance. Do not use concurrency primitives such as `Mutex`. `thread_local!` is allowed for global variables because the program is assumed to be sequential.
