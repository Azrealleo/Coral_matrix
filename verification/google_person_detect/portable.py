"""Read-only integrity check for the person RTL export; NOT a simulator."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath

TOP = "VmeCoreMini_ITCM256KB_DTCM512KBAxi"


def file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def inventory(root):
    result = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("Symlink in immutable package")
        if path.is_file():
            name = path.relative_to(root).as_posix()
            if name not in ("manifest.json", "SHA256SUMS"):
                result[name] = file_sha(path)
    return result


def safe_name(name):
    path = PurePosixPath(name)
    if not name or path.is_absolute() or ".." in path.parts or "\\" in name or ":" in name:
        raise ValueError("Unsafe manifest path")
    return name


def verify(root):
    root = Path(root).resolve(strict=True)
    manifest = json.loads((root / "manifest.json").read_text())
    if (manifest.get("schema") != 1 or manifest.get("hdl_top") != TOP or
            manifest.get("itcm_kib") != 256 or manifest.get("dtcm_kib") != 512 or
            manifest.get("validation") != "export_integrity_only_NOT_NPU_RTL_PASS"):
        raise ValueError("Wrong person RTL export identity")
    for name in manifest["files"]:
        safe_name(name)
    if inventory(root) != manifest["files"]:
        raise ValueError("Missing/extra/changed package files; do not edit hashes")
    expected = dict(manifest["files"], **{"manifest.json": file_sha(root / "manifest.json")})
    rows = (root / "SHA256SUMS").read_text().splitlines()
    actual = {}
    for row in rows:
        digest, name = row.split("  ", 1)
        safe_name(name)
        if name in actual:
            raise ValueError("Duplicate checksum entry")
        actual[name] = digest
    if actual != expected:
        raise ValueError("Checksum index mismatch")
    for name in ("firmware/person_program.elf", "rtl/" + TOP + ".sv"):
        if file_sha(root / name) != manifest["elf_sha256" if name.endswith(".elf") else "rtl_sha256"]:
            raise ValueError("RTL/ELF identity mismatch")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path)
    args = parser.parse_args()
    value = verify(args.package)
    print("[PERSON_PORTABLE_PACKAGE_VERIFIED] top=" + value["hdl_top"] + " NPU_RTL=NOT_RUN")
