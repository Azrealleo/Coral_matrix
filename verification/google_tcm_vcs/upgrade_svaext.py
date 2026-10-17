#!/usr/bin/env python3
"""Copy a verified v1 VCS package and add -assert svaext, never edit the source."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys

sys.dont_write_bytecode = True
ORIGINAL_RUNTIME_SHA256 = "2393ed9e106c90c71d0b604fcf55392f0a18be9dd790811731aeb02f4d8f6ac0"
ORIGINAL_LIBRARY_SHA256 = "d5673e81b49c75a7630aa54f365f1dd9d5a606aa771b5b6021daa5e335fa864d"
OLD_ARGS = b'BUILD_ARGS = ["-timescale=1ns/1ps", "-O3", "+define+VCS"] + ["+define+" + n for n in DEFINES]'
NEW_ARGS = b'BUILD_ARGS = ["-timescale=1ns/1ps", "-O3", "-assert", "svaext", "+define+VCS"] + ["+define+" + n for n in DEFINES]'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def upgrade(source):
    source = Path(source).resolve(strict=True)
    # Authenticate the verifier bytes before importing code from the source.
    library_path = source / "package_lib.py"
    if digest(library_path.read_bytes()) != ORIGINAL_LIBRARY_SHA256:
        raise ValueError("unknown package_lib.py; no copy created")
    spec = importlib.util.spec_from_file_location("tcm_svaext_verified_package_lib", library_path)
    library = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(library)
    manifest = library.verify(source)
    original = (source / "runtime.py").read_bytes()
    if digest(original) != ORIGINAL_RUNTIME_SHA256 or original.count(OLD_ARGS) != 1:
        raise ValueError("not the exact original v1 runtime.py; no copy created")
    parent_manifest = (source / "manifest.json").read_bytes()
    parent_checks = (source / "SHA256SUMS").read_bytes()
    destination = source.with_name(source.name + "_svaext_v1")
    if destination.exists() or destination.is_symlink():
        raise ValueError("destination exists; nothing overwritten: " + str(destination))
    shutil.copytree(source, destination)
    (destination / "runtime.py").write_bytes(original.replace(OLD_ARGS, NEW_ARGS))
    evidence = "evidence/vcs_svaext_parent_manifest.json"
    if (destination / evidence).exists():
        raise ValueError("unexpected upgrade evidence; partial copy retained, do not use")
    (destination / evidence).write_bytes(parent_manifest)
    manifest["vcs_launcher_upgrade"] = dict(
        schema=1, name="svaext_v1", added_build_args=["-assert", "svaext"],
        reason="VCS2020 requires svaext to parse original elaboration system tasks",
        parent_directory=str(source), parent_manifest_sha256=digest(parent_manifest),
        parent_runtime_sha256=digest(original),
        new_runtime_sha256=library.sha(destination / "runtime.py"),
        applied_utc=datetime.now(timezone.utc).isoformat(), vcs_simulation="NOT_RUN")
    # Detect source mutation during copying and require all existing payload bytes
    # (including RTL, ELF, DPI, fixture and workload) to remain identical.
    if (library.verify(source)["files"] != manifest["files"] or
            (source / "manifest.json").read_bytes() != parent_manifest or
            (source / "SHA256SUMS").read_bytes() != parent_checks):
        raise ValueError("source changed during copy; partial copy retained, do not use")
    for name, expected in manifest["files"].items():
        if name != "runtime.py" and library.sha(destination / name) != expected:
            raise ValueError("payload changed during copy: " + name)
    library.seal(destination, manifest)
    library.verify(destination)
    print("[TCM_VCS_SVAEXT_UPGRADE_PASS] " + json.dumps(dict(
        package=str(destination), parent_manifest_sha256=digest(parent_manifest),
        rtl_and_firmware_unchanged=True, original_package_unchanged=True,
        added_build_args=["-assert", "svaext"], vcs_simulation="NOT_RUN")))
    return destination


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path)
    args = parser.parse_args()
    try:
        upgrade(args.package)
    except Exception as error:
        print("[TCM_VCS_SVAEXT_UPGRADE_STOP] " + str(error), file=sys.stderr)
        sys.exit(1)
