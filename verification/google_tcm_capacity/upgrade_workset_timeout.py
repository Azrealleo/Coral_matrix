#!/usr/bin/env python3
"""Migrate only the fingerprinted, pre-execution cocotb timeout-unit typo."""
import argparse
import json
import os
from pathlib import Path
import tempfile

import prepare_workset as installer
from prepare import digest

OLD_SHA = "032faeff95adc4080c117f332c8f15ef664288e86bfa5c1cc6218944a91cd992"
OLD_LINE = b'@cocotb.test(timeout_time=2, timeout_unit="s")'
NEW_LINE = b'@cocotb.test(timeout_time=2000, timeout_unit="ms")'
MIGRATION = "cocotb_timeout_seconds_to_ms_v1"


def benchmark_versions():
    new = (installer.HERE / "workset_bench.py").read_bytes()
    if new.count(NEW_LINE) != 1:
        raise ValueError("unexpected timeout fix; refusing migration")
    old = new.replace(NEW_LINE, OLD_LINE)
    if digest(old) != OLD_SHA:
        raise ValueError("benchmark differs beyond the known timeout typo")
    return old, new


def atomic_write(path, data):
    # Temp file is in the same directory/filesystem; never expose a partial file.
    fd, name = tempfile.mkstemp(prefix=".tcm-timeout-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def upgrade(root):
    root = root.resolve()
    manifest_path = root / installer.MANIFEST
    if not manifest_path.exists():
        return None  # Fresh install is handled by the ordinary strict installer.
    if manifest_path.is_symlink():
        raise ValueError("refusing symlink manifest")
    installer.verify_control(root)
    old, new = benchmark_versions()
    original = manifest_path.read_bytes()
    manifest = json.loads(original)
    current_files = installer.expected_files(root)
    current_hashes = {n: digest(b) for n, b in current_files.items()}
    if manifest["files"] == current_hashes:
        installer.verify(root)
        return None  # Already upgraded: fully verify, do not rewrite/back up again.
    if (manifest["schema"] != 1 or manifest["upstream"] != installer.UPSTREAM or
            manifest["scope"] != installer.SCOPE or manifest["control_manifest_sha256"] !=
            digest((root / "tcm_control_manifest.json").read_bytes())):
        raise ValueError("workset/base identity mismatch; nothing overwritten")
    names = [f"{installer.PACKAGE}/d{kib}/workset_bench.py" for kib in installer.CAPACITIES]
    old_files = dict(current_files)
    for name in names:
        if current_files[name] != new:
            raise ValueError("unexpected generated benchmark")
        old_files[name] = old
    old_tools = {n: digest((installer.HERE / n).read_bytes()) for n in installer.TOOLS}
    old_tools["workset_bench.py"] = OLD_SHA
    if (manifest["files"] != {n: digest(b) for n, b in old_files.items()} or
            manifest["tools"] != old_tools):
        raise ValueError("not the exact known old workset version; nothing overwritten")
    for name, data in old_files.items():
        path = root / name
        if path.is_symlink() or path.read_bytes() != data:
            raise ValueError("changed/missing workset file; nothing overwritten: " + name)
    # All baseline, tool, manifest and 33 installed file checks precede any writes.
    backup = Path(tempfile.mkdtemp(prefix="workset_timeout_upgrade.", dir=root.parent))
    (backup / installer.MANIFEST).write_bytes(original)
    (backup / "workset_bench.old.py").write_bytes(old)
    record = dict(migration=MIGRATION, old_sha256=OLD_SHA, new_sha256=digest(new),
                  changed_files=names, source=str(root), backup=str(backup),
                  change="timeout spelling only; RTL, firmware and BUILD unchanged")
    (backup / "migration.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    manifest["files"] = current_hashes
    manifest["tools"]["workset_bench.py"] = digest(new)
    manifest.setdefault("harness_migrations", []).append(record)
    print("[TCM_WORKSET_TIMEOUT_UPGRADE_BACKUP] " + str(backup), flush=True)
    for name in names:
        atomic_write(root / name, new)
    # Manifest is committed last; an interrupted/partial migration fails strict checks.
    atomic_write(manifest_path, (json.dumps(manifest, indent=2) + "\n").encode())
    installer.verify(root)
    print(f"[TCM_WORKSET_TIMEOUT_UPGRADE] files={len(names)} backup={backup}")
    return backup


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream", required=True, type=Path)
    upgrade(parser.parse_args().upstream)
