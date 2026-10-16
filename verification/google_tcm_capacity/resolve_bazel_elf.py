#!/usr/bin/env python3
"""Resolve the exact configured firmware output, not a bazel-bin guess."""
import argparse
from pathlib import Path, PurePosixPath


def resolve_elf(execroot, output_text):
    root = Path(execroot).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("execution_root is not a directory")
    candidates = set()
    for line in output_text.splitlines():
        if not line.strip():
            continue
        relative = PurePosixPath(line.strip())
        if (relative.is_absolute() or ".." in relative.parts or
                not relative.parts or relative.parts[0] != "bazel-out" or
                relative.name != "control_program.elf"):
            raise ValueError("unexpected cquery firmware output: " + line)
        path = root.joinpath(*relative.parts).resolve(strict=True)
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError("firmware output escapes execution_root or is not a file")
        candidates.add(path)
    if len(candidates) != 1:
        raise ValueError("expected exactly one configured firmware ELF; got " + str(len(candidates)))
    selected = candidates.pop()
    with selected.open("rb") as stream:
        header = stream.read(20)
    # ELF32, little-endian, EM_RISCV=243. Do not accept an unrelated host ELF.
    if (len(header) < 20 or header[:6] != b"\x7fELF\x01\x01" or
            int.from_bytes(header[18:20], "little") != 243):
        raise ValueError("output is not a little-endian RISC-V ELF32")
    return selected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execution-root-file", required=True, type=Path)
    parser.add_argument("--outputs-file", required=True, type=Path)
    args = parser.parse_args()
    root_lines = [s.strip() for s in args.execution_root_file.read_text().splitlines() if s.strip()]
    if len(root_lines) != 1 or not Path(root_lines[0]).is_absolute():
        raise ValueError("expected one absolute execution_root")
    print(resolve_elf(root_lines[0], args.outputs_file.read_text()))


if __name__ == "__main__":
    main()
