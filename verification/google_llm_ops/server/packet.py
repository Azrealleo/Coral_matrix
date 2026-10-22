"""Read-only firmware packet verification and isolated helper imports."""
import ast
from contextlib import contextmanager
import hashlib
import importlib.util
import json
from pathlib import Path,PurePosixPath
import re
import sys
from types import SimpleNamespace

UPSTREAM="8e4df09b4ea7e065e02d14ce3ae033d40dfd973a"
RTL_SHA="477aa4d097b1ac7c35f98cb95fe9ba841082a8a10afde6f39dea70959300bfe2"
TOP="VmeCoreMini_ITCM256KB_DTCM512KBAxi"
HELPER_SHA="3d6753e12b348d8816ca377156233f9ce0b544c773ece8b4376e54b1b78d8d7e"


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def safe_name(name):
    p=PurePosixPath(name)
    if not name or p.is_absolute() or any(x in ("..",".") for x in p.parts) or "\\" in name or ":" in name:
        raise ValueError("Unsafe packet filename")


def inventory(root):
    result={}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():raise ValueError("Symlink in immutable packet")
        if path.is_file() and path.relative_to(root).as_posix() not in ("manifest.json","SHA256SUMS"):
            name=path.relative_to(root).as_posix();safe_name(name);result[name]=sha(path)
    return result


def seal(root,manifest):
    manifest=dict(manifest,files=inventory(root))
    with (root/"manifest.json").open("x",encoding="utf-8") as stream:json.dump(manifest,stream,indent=2)
    checks=dict(manifest["files"],**{"manifest.json":sha(root/"manifest.json")})
    with (root/"SHA256SUMS").open("x",encoding="utf-8") as stream:
        stream.write(''.join(h+"  "+n+"\n" for n,h in sorted(checks.items())))
    return manifest


@contextmanager
def isolated_modules(values):
    old={name:sys.modules.get(name) for name in values}
    sys.modules.update(values)
    try:yield
    finally:
        for name,value in old.items():
            if value is None:sys.modules.pop(name,None)
            else:sys.modules[name]=value


def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result);return result


def helpers(root):
    # The qualified old Person producer also has a module named 'spec'. Never
    # let imports overwrite its semantics or contaminate the LLM resource audit.
    linear=module("_llm_packet_linear_spec",root/"linear/spec.py")
    tx=module("_llm_packet_tx_spec",root/"transformer/tx_spec.py")
    with isolated_modules(dict(spec=linear,tx_spec=tx)):
        la=module("_llm_packet_linear_audit",root/"linear/audit.py")
        ta=module("_llm_packet_tx_audit",root/"transformer/tx_audit.py")
    return SimpleNamespace(linear=linear,tx=tx,linear_audit=la,tx_audit=ta)


def checked_host(h,family,text):
    with isolated_modules(dict(spec=h.linear,tx_spec=h.tx)):
        (h.linear_audit if family=="int8" else h.tx_audit).checked_host(text)


def verify(root):
    root=Path(root).resolve(strict=True);m=json.loads((root/"manifest.json").read_text())
    required=dict(schema=1,kind="llm_operator_firmware_packet_v1",upstream=UPSTREAM,
        itcm_kib=256,dtcm_kib=512,rtl_sha256=RTL_SHA,hdl_top=TOP,simulation="NOT_RUN")
    if any(m.get(k)!=v for k,v in required.items()):raise ValueError("Wrong LLM packet identity")
    for n in m["files"]:safe_name(n)
    if inventory(root)!=m["files"]:raise ValueError("LLM packet missing/extra/changed files")
    checks={}
    for line in (root/"SHA256SUMS").read_text().splitlines():
        value,name=line.split("  ",1);safe_name(name)
        if name in checks or not re.fullmatch("[a-f0-9]{64}",value):raise ValueError("Bad checksum index")
        checks[name]=value
    if checks!=dict(m["files"],**{"manifest.json":sha(root/"manifest.json")}):raise ValueError("Checksum index differs")
    if sha(root/"qualified_model.py")!=HELPER_SHA:raise ValueError("Qualified build checker changed")
    return m


def load(root):
    root=Path(root).resolve(strict=True);m=verify(root);h=helpers(root);reports={}
    h.tx_audit.checked_header((root/"parameters.h").read_text())
    for family,audit in (("int8",h.linear_audit),("fp32",h.tx_audit)):
        directory=root/"firmware"/family
        report=audit.inspect((directory/"probe_program.elf").read_bytes())
        if report!=json.loads((directory/"resources.json").read_text()) or report["elf_sha256"]!=m["firmwares"][family]:
            raise ValueError("ELF/resource identity changed: "+family)
        checked_host(h,family,(directory/"host.log").read_text())
        source=json.loads((directory/"source-manifest.json").read_text())
        if source["upstream"]!=UPSTREAM:raise ValueError("Wrong source revision")
        basenames=set()
        for name,digest in source["files"].items():
            safe_name(name)
            if Path(name).name in basenames:raise ValueError("Ambiguous source snapshot name")
            basenames.add(Path(name).name)
            if sha(root/"source"/family/Path(name).name)!=digest:raise ValueError("Compiled source snapshot changed")
        reports[family]=report
    # Runtime scripts are verbatim snapshots of the audited candidate sources.
    for directory,names,family in (("linear",("spec.py","audit.py","linear_rtl_bench.py"),"int8"),
        ("transformer",("tx_spec.py","tx_audit.py","tx_bench.py"),"fp32")):
        for name in names:
            if (root/directory/name).read_bytes()!=(root/"source"/family/name).read_bytes():
                raise ValueError("Runtime/candidate source differs: "+name)
    return SimpleNamespace(root=root,manifest=m,helpers=h,reports=reports)


def projected_bench(source,helper_names):
    """Only replace Bazel path resolution/test entry, never the measured body."""
    tree=ast.parse(source)
    keep={"run_case",*helper_names}
    body=[]
    for node in tree.body:
        if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)):
            if node.name not in keep:continue
            if node.decorator_list:raise ValueError("Unexpected measured helper decorator")
        body.append(node)
    result=ast.Module(body=body,type_ignores=[])
    if {n.name for n in body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))}!=keep:
        raise ValueError("Changed canonical test helper structure")
    return ast.fix_missing_locations(result)
