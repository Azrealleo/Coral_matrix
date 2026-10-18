#!/usr/bin/env python3
"""Add independently fingerprinted ITCM tests to the existing fixed experiment.

Never alter old DTCM files/manifests, upstream RTL logic or the team repository.
"""
import argparse
import json
from pathlib import Path
import re
import sys

HERE = Path(__file__).resolve().parent
BASE_TOOLS = HERE.parent / "google_tcm_capacity"
sys.path.insert(0, str(BASE_TOOLS))
from capacity_spec import UPSTREAM as BASE_UPSTREAM
from prepare import build_text, digest, git, verify as verify_dtcm
from prepare_control import stage1_evidence

from itcm_spec import CAPACITIES, DTCM_KIB, SCOPE, UPSTREAM, checked_parameters
from itcm_spec import geometry, mask_addresses, probes

MANIFEST = "itcm_geometry_manifest.json"
TOOLS = ("itcm_spec.py", "itcm_bench.py", "prepare_itcm.py", "run.sh")


def itcm_build(kib):
    g = geometry(kib)
    old_top = geometry(8)["hdl_top"]
    text = build_text(DTCM_KIB)
    text = text.replace(old_top, g["hdl_top"])
    text = text.replace("--itcmSizeKBytes=8", f"--itcmSizeKBytes={kib}")
    text = text.replace('name = "capacity",', 'name = "geometry",')
    text = text.replace("tcm_capacity_test", "itcm_geometry_test")
    text = text.replace("capacity_spec.py", "itcm_spec.py")
    text = text.replace("capacity_bench.py", "itcm_bench.py")
    text = text.replace(f"TCM_DTCM_KIB={DTCM_KIB}", f"TCM_ITCM_KIB={kib}")
    return text.replace("# Generated capacity-only experiment", "# Generated ITCM geometry experiment")


def expected_files():
    files = {}
    for kib in CAPACITIES:
        prefix = geometry(kib)["package"] + "/"
        files[prefix + "BUILD"] = itcm_build(kib).encode()
        for name in ("itcm_spec.py", "itcm_bench.py"):
            files[prefix + name] = (HERE / name).read_bytes()
    return files


def base_identity(root):
    if BASE_UPSTREAM != UPSTREAM:
        raise ValueError("different upstream baselines")
    verify_dtcm(root)
    return digest((root / "tcm_capacity_manifest.json").read_bytes())


def verify(root):
    base = base_identity(root)
    data = json.loads((root / MANIFEST).read_text(encoding="utf-8"))
    files = expected_files()
    if (data.get("schema") != 1 or data.get("upstream") != UPSTREAM or
            data.get("scope") != SCOPE or data.get("dtcm_kib") != DTCM_KIB or
            data.get("base_manifest_sha256") != base or
            data.get("capacities") != [geometry(k) for k in CAPACITIES] or
            data.get("files") != {n: digest(b) for n, b in files.items()} or
            data.get("tools") != {n: digest((HERE / n).read_bytes()) for n in TOOLS}):
        raise ValueError("ITCM experiment identity changed; preserve old evidence")
    for name, expected in data["files"].items():
        path = root / name
        if path.is_symlink() or digest(path.read_bytes()) != expected:
            raise ValueError("ITCM test file changed: " + name)
    # Re-check that the original passed DTCM evidence has not changed.
    evidence = data["dtcm_stage1_evidence"]
    evidence_path = Path(evidence["directory"]).resolve()
    if evidence_path.parent != root.parent or not evidence_path.name.startswith("run_d2048."):
        raise ValueError("DTCM evidence is outside this experiment")
    from prepare import checked_log
    log = (evidence_path / "test.log").read_bytes()
    if digest(log) != evidence["test_log_sha256"]:
        raise ValueError("DTCM evidence log changed")
    checked_log(log.decode(), DTCM_KIB)
    return data


def prepare(root):
    base = base_identity(root)
    if (root / MANIFEST).exists():
        return verify(root)
    evidence = stage1_evidence(root, DTCM_KIB)
    files = expected_files()
    if (root / "tests/cocotb/itcm_capacity").exists():
        raise ValueError("ITCM package exists without manifest; refusing overwrite")
    # Validate everything before adding separate untracked packages only.
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(content)
    data = dict(schema=1, upstream=UPSTREAM, scope=SCOPE, dtcm_kib=DTCM_KIB,
                capacities=[geometry(k) for k in CAPACITIES],
                base_manifest_sha256=base, dtcm_stage1_evidence=evidence,
                files={n: digest(b) for n, b in files.items()},
                tools={n: digest((HERE / n).read_bytes()) for n in TOOLS})
    with (root / MANIFEST).open("x", encoding="utf-8") as stream:
        json.dump(data, stream, indent=2)
        stream.write("\n")
    return verify(root)


def checked_log(text, kib):
    marker = "[GOOGLE_ITCM_GEOMETRY] "
    rows = [json.loads(line.split(marker, 1)[1]) for line in text.splitlines() if marker in line]
    summaries = re.findall(r"TESTS=(\d+)\s+PASS=(\d+)\s+FAIL=(\d+)\s+SKIP=(\d+)", text)
    if (len(rows) != 1 or not summaries or summaries[-1] != ("1", "1", "0", "0") or
            text.count("[GOOGLE_ITCM_GEOMETRY_CHECK] passed") != 1):
        raise ValueError("missing/duplicate/failed ITCM result")
    expected = dict(geometry(kib), schema=1, scope=SCOPE, status="PASS", core_started=False,
                    checked_words=len(probes(kib)), checked_bytes=16 * len(probes(kib)),
                    byte_mask_cases=len(mask_addresses(kib)))
    row = rows[0]
    for key, value in expected.items():
        if type(row.get(key)) is not type(value) or row[key] != value:
            raise ValueError("wrong ITCM result field: " + key)
    return row


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    for name in ("prepare", "verify"):
        sub.add_parser(name).add_argument("--upstream", type=Path, required=True)
    for name in ("header", "log"):
        child = sub.add_parser(name)
        child.add_argument("--file", type=Path, required=True)
        child.add_argument("--kib", type=int, choices=CAPACITIES, required=True)
    a = p.parse_args()
    if a.command in ("prepare", "verify"):
        root = a.upstream.resolve()
        data = prepare(root) if a.command == "prepare" else verify(root)
        print("[ITCM_EXPERIMENT_VERIFIED] upstream=" + data["upstream"])
    elif a.command == "header":
        print("[ITCM_PARAMETERS] " + json.dumps(checked_parameters(a.file.read_text(), a.kib), sort_keys=True))
    else:
        print("[ITCM_GEOMETRY_SUMMARY] " + json.dumps(checked_log(a.file.read_text(), a.kib), sort_keys=True))


if __name__ == "__main__":
    main()
