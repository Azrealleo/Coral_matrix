#!/usr/bin/env python3
"""Create a new documentation revision of a verified RTL package.

Only HANDOFF.md, manifest.json, and SHA256SUMS may change. No RTL is generated,
modified, or simulated; the input directory and archive are preserved.
"""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import tarfile

from export_simulated_google_rtl import sha256, verify, write_checksums


def file_hashes(root):
    return {path.relative_to(root).as_posix(): sha256(path)
            for path in root.rglob("*") if path.is_file()}


def refresh(package, output, document, input_archive=None):
    package, output, document = map(lambda value: Path(value).resolve(), (package, output, document))
    verify(package)
    archive = output.with_name(output.name + ".tar.gz")
    if output.exists() or archive.exists():
        raise ValueError("Output already exists; nothing overwritten: " + str(output))
    if package in output.parents:
        raise ValueError("Output must not be inside the input package")
    if not document.is_file():
        raise ValueError("Documentation file missing: " + str(document))
    before = file_hashes(package)
    shutil.copytree(package, output)
    shutil.copy2(document, output / "HANDOFF.md")
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    update = {"version": "v2", "updated_at_utc": datetime.now(timezone.utc).isoformat(),
              "mode": "documentation_only_no_rtl_changes", "input_manifest_sha256": before["manifest.json"],
              "changed_files": ["HANDOFF.md", "manifest.json", "SHA256SUMS"]}
    if input_archive is not None:
        update["input_archive_sha256"] = sha256(Path(input_archive).resolve())
    manifest["documentation_update"] = update
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_checksums(output)
    after = file_hashes(output)
    if before.keys() != after.keys():
        raise ValueError("Documentation refresh unexpectedly changed package file set")
    allowed = {"HANDOFF.md", "manifest.json", "SHA256SUMS"}
    changed = {name for name in before if before[name] != after[name]}
    if not changed.issubset(allowed) or file_hashes(package) != before:
        raise ValueError("Unexpected file modification during documentation refresh")
    result = verify(output)
    with tarfile.open(archive, "x:gz") as stream:
        stream.add(output, arcname=output.name)
    print("[SIM_RTL_DOCS_VERIFIED] " + json.dumps(result, sort_keys=True))
    print("[SIM_RTL_DOCS_CHANGED] " + ",".join(sorted(changed)))
    print("[SIM_RTL_DOCS_ARCHIVE] {} sha256={}".format(archive, sha256(archive)))
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--document", type=Path, default=Path(__file__).with_name("HANDOFF-simulated-rtl.md"))
    parser.add_argument("--input-archive", type=Path)
    args = parser.parse_args()
    try:
        refresh(args.package, args.output, args.document, args.input_archive)
    except (ValueError, OSError, KeyError) as error:
        parser.exit(1, "[SIM_RTL_DOCS_ERROR] {}\n".format(error))


if __name__ == "__main__":
    main()
