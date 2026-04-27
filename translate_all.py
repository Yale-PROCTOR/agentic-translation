#!/usr/bin/env python3
import subprocess
import sys
import time
from pathlib import Path


def main() -> None:
    public_dir = Path("Test-Corpus/Public-Tests")
    bundle_dir = Path("Test-Corpus/bundles/Public-Tests")

    for test_dir in sorted(path for path in public_dir.glob("*/*") if path.is_dir()):
        if "P01_" in test_dir.as_posix():
            continue
        if (test_dir / "translated_rust").exists():
            continue

        bundle = bundle_dir / test_dir.relative_to(public_dir).with_suffix(".tar.gz")
        if bundle.is_file():
            start = time.monotonic()
            result = subprocess.run(
                ["./translate.py", str(bundle), str(test_dir / "translated_rust")]
            )
            elapsed = time.monotonic() - start
            if result.returncode == 0:
                with Path("times.txt").open("a") as file:
                    file.write(f"{test_dir} {elapsed:.3f}\n")
            else:
                print(f"failed: {bundle}", file=sys.stderr)


if __name__ == "__main__":
    main()
