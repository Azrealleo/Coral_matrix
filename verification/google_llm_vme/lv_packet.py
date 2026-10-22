"""Immutable firmware-only packet. Integrity checks do not claim RTL PASS."""
import hashlib
import json
from pathlib import Path,PurePosixPath
from types import SimpleNamespace
import lv_spec as spec
import lv_audit as audit


def safe_name(name):
    p=PurePosixPath(name)
    if not name or p.is_absolute() or '..' in p.parts or '\\' in name or ':' in name:raise ValueError("Unsafe packet filename")


def inventory(root):
    result={}
    for p in sorted(root.rglob('*')):
        if p.is_symlink():raise ValueError("Symlink in immutable packet")
        if p.is_file():
            name=p.relative_to(root).as_posix();safe_name(name)
            if name not in ('manifest.json','SHA256SUMS'):result[name]=spec.sha(p)
    return result


def seal(root,manifest):
    manifest=dict(manifest,files=inventory(root))
    with (root/'manifest.json').open('x',encoding='utf-8') as f:json.dump(manifest,f,indent=2)
    checks=dict(manifest['files'],**{'manifest.json':spec.sha(root/'manifest.json')})
    with (root/'SHA256SUMS').open('x',encoding='utf-8') as f:f.write(''.join(h+'  '+n+'\n' for n,h in sorted(checks.items())))
    return manifest


def load(root):
    root=Path(root).resolve(strict=True);m=json.loads((root/'manifest.json').read_text())
    required=dict(schema=1,kind='llm_vme_linear_firmware_packet_v2',upstream=spec.UPSTREAM,hdl_top=spec.TOP,
        itcm_kib=256,dtcm_kib=512,rtl_sha256=spec.RTL_SHA,simulation='NOT_RUN')
    if any(m.get(k)!=v for k,v in required.items()):raise ValueError("Wrong VME packet identity")
    for name in m['files']:safe_name(name)
    if inventory(root)!=m['files']:raise ValueError("Missing/extra/changed packet files")
    checks={}
    for line in (root/'SHA256SUMS').read_text().splitlines():
        digest,name=line.split('  ',1);safe_name(name)
        if name in checks:raise ValueError("Duplicate checksum entry")
        checks[name]=digest
    if checks!=dict(m['files'],**{'manifest.json':spec.sha(root/'manifest.json')}):raise ValueError("Checksum index differs")
    if spec.sha(root/'qualified_model.py')!=spec.QUALIFIED_SHA:raise ValueError("Qualified model checker changed")
    audit.checked_header((root/'parameters.h').read_text())
    data=(root/'probe_program.elf').read_bytes();report=audit.inspect(data)
    if report!=json.loads((root/'resources.json').read_text()) or report['elf_sha256']!=m['elf_sha256']:
        raise ValueError("Actual ELF/resources differ")
    spec.checked_host((root/'host.log').read_text())
    source=json.loads((root/'source-manifest.json').read_text())
    if source['upstream']!=spec.UPSTREAM or source['scope']!=spec.SCOPE or source['hardware_tile_sha256']!=spec.TILE_SHA or source['vector_reference_sha256']!=spec.REFERENCE_SHA:
        raise ValueError("Wrong compiled source identity")
    seen=set()
    for name,digest in source['files'].items():
        safe_name(name);basename=PurePosixPath(name).name
        if basename in seen:raise ValueError("Ambiguous source snapshot")
        seen.add(basename)
        if spec.sha(root/'source'/basename)!=digest:raise ValueError("Compiled source snapshot changed")
    for name in ('lv_spec.py','lv_audit.py','baseline_spec.py'):
        if (root/name).read_bytes()!=(root/'source'/name).read_bytes():raise ValueError("Runtime/source differs")
    if spec.sha(root/'source/vme_tile.h')!=spec.TILE_SHA:raise ValueError("HardwareTile no longer original")
    if spec.sha(root/'baseline_spec.py')!=spec.REFERENCE_SHA:raise ValueError("Original vector source differs")
    return SimpleNamespace(root=root,manifest=m,report=report)
