"""Standard-library integrity checks for immutable, standalone TCM VCS packages."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import zipfile

UPSTREAM = "8e4df09b4ea7e065e02d14ce3ae033d40dfd973a"
CAPACITIES = (1024, 2048, 4096)
DEFINES = ("USE_GENERIC", "TB_SUPPORT", "ZVE32F_ON", "VLEN_128", "ZVT_ON", "ZVTBF16FMM_ON")
ZIP_DEFINES = set(DEFINES) - {"ZVTBF16FMM_ON"}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(part)
    return h.hexdigest()


def relative(name):
    p = PurePosixPath(name)
    if (not name or p.is_absolute() or ".." in p.parts or p.as_posix() != name or
            any(c.isspace() or c in '\\:"\'`$+;' for c in name)):
        raise ValueError("unsafe package path: " + name)
    return p


def write_json(path, value):
    path.write_bytes((json.dumps(value, indent=2, sort_keys=True) + "\n").encode())


def zip_contents(path):
    result, seen = {}, set()
    with zipfile.ZipFile(path) as archive:
        for item in archive.infolist():
            if item.is_dir():
                relative(item.filename.rstrip("/"))
                continue
            name = relative(item.filename).as_posix()
            if name.casefold() in seen or (item.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError("duplicate/case-colliding/symlink ZIP entry: " + name)
            seen.add(name.casefold())
            result[name] = archive.read(item)
    return result


def compilation_inputs(contents, top):
    names, defines, include_dirs = [], set(), {"."}
    for raw in contents["filelist.f"].decode().splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", "//")):
            continue
        if line.startswith("+define+"):
            defines.update(line[8:].split("+"))
        elif line.startswith("+incdir+"):
            directory = line[8:]
            if directory != ".":
                relative(directory)
            include_dirs.add(directory)
        else:
            relative(line)
            if line not in contents or line in names:
                raise ValueError("missing/duplicate ZIP source: " + line)
            names.append(line)
    if defines != ZIP_DEFINES or top + ".sv" not in names or "Sram.v" not in names:
        raise ValueError("unexpected upstream ZIP filelist/top/RAM/defines")
    # Only the original monolithic SV is compiled; extracted ZIP modules are NOT
    # separately compiled (which would duplicate module/package definitions).
    include_dirs.update(str(PurePosixPath(n).parent) for n in contents)
    return sorted(include_dirs)


def checked_header(text, kib):
    found = dict(re.findall(r"^#define\s+KP_(\w+)\s+(\S+)", text, re.M))
    expected = dict(xlen="32", itcmSizeKBytes="8", dtcmSizeKBytes=str(kib), axi2IdBits="6",
                    rvvVlen="128", fetchDataBits="128", lsuDataBits="128", enableFetchL0="false",
                    enableRvv="true", enableVme="true", enableFloat="true", enableZfbfmin="true",
                    enableVectorBf16="true", enableAxiInstructionFetch="true", enableVerification="false")
    if any(found.get(k) != v for k, v in expected.items()):
        raise ValueError("wrong hardware parameters")
    return expected


def file_hashes(root):
    result = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("symlink in immutable package: " + str(path))
        if path.is_file() and path.relative_to(root).as_posix() not in ("manifest.json", "SHA256SUMS"):
            name = path.relative_to(root).as_posix()
            relative(name)
            result[name] = sha(path)
    return result


def seal(root, manifest):
    manifest["files"] = file_hashes(root)
    write_json(root / "manifest.json", manifest)
    checks = dict(manifest["files"], **{"manifest.json": sha(root / "manifest.json")})
    (root / "SHA256SUMS").write_bytes("".join(f"{h}  {n}\n" for n, h in sorted(checks.items())).encode())


def verify(root):
    root = Path(root).resolve(strict=True)
    manifest = json.loads((root / "manifest.json").read_text())
    kib = manifest["dtcm_kib"]
    if (manifest["schema"] != 1 or manifest["upstream"] != UPSTREAM or kib not in CAPACITIES or
            manifest["itcm_kib"] != 8 or manifest["defines"] != list(DEFINES) or
            manifest["hdl_top"] != f"VmeCoreMini_ITCM8KB_DTCM{kib}KBAxi" or
            manifest["rtl_mode"] != "original_monolithic_sv_no_rewrite" or
            manifest["clock_ns"] != "1.25" or manifest["memory_map"] !=
            dict(itcm=0, dtcm=0x01000000, csr=0x02000000, external=0x20000000) or
            manifest["export_validation"] != "bytes_equal_passed_control_rtl_not_vcs_simulated"):
        raise ValueError("wrong standalone package identity")
    if file_hashes(root) != manifest["files"]:
        raise ValueError("missing/extra/changed immutable package files")
    if manifest["dpi_source_sha256"] != {n: sha(root / "dpi" / n) for n in ("sram_backdoor.cc", "sram_backdoor.h")}:
        raise ValueError("original SRAM DPI source missing/changed")
    checks = {}
    for line in (root / "SHA256SUMS").read_text().splitlines():
        h, n = line.split("  ", 1)
        relative(n)
        if n in checks or not re.fullmatch("[a-f0-9]{64}", h):
            raise ValueError("invalid checksum entry")
        checks[n] = h
    if checks != dict(manifest["files"], **{"manifest.json": sha(root / "manifest.json")}):
        raise ValueError("checksum list mismatch")
    top = manifest["hdl_top"]
    checked_header((root / "rtl" / f"V{top}_parameters.h").read_text(), kib)
    if sha(root / "rtl" / (top + ".sv")) != manifest["passed_control_rtl_sha256"]:
        raise ValueError("RTL differs from recorded passing control")
    contents = zip_contents(root / "original" / (top + ".zip"))
    if compilation_inputs(contents, top) != manifest["zip_include_dirs"]:
        raise ValueError("include paths changed")
    for name, data in contents.items():
        if (root / "rtl_dependencies" / name).read_bytes() != data:
            raise ValueError("ZIP extraction changed: " + name)
    header = (root / "firmware/workset_program.elf").read_bytes()[:20]
    if (len(header) != 20 or header[:6] != b"\x7fELF\x01\x01" or
            int.from_bytes(header[18:20], "little") != 243 or
            sha(root / "firmware/workset_program.elf") != manifest["passed_workset_elf_sha256"]):
        raise ValueError("not the tested RISC-V ELF32")
    return manifest
