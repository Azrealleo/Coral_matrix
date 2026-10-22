"""Export one actually linked ELF, native evidence and standalone tools; no RTL."""
import argparse
import json
from pathlib import Path
import shutil
import tarfile
import prepare
import lv_spec as spec
import lv_audit as audit
import lv_packet

HERE=Path(__file__).resolve().parent


def export(root,job):
    source=prepare.prepare(root)
    if json.loads((job/'source-manifest.json').read_text())!=source:raise ValueError("Build source identity differs")
    data=(job/'probe_program.elf').read_bytes();report=audit.inspect(data)
    if report!=json.loads((job/'resources.json').read_text()):raise ValueError("Actual ELF report differs")
    spec.checked_host((job/'host.log').read_text())
    identity=json.loads((job/'rtl-identity.json').read_text())
    if identity['rtl_sha256']!=spec.RTL_SHA or identity['parameters']!=audit.checked_header((job/'parameters.h').read_text()):
        raise ValueError("RTL/header differs from qualified server model")
    packet=job/'coral_llm_vme_i256_d512_v1';packet.mkdir(exist_ok=False);(packet/'source').mkdir()
    for name in ('probe_program.elf','resources.json','parameters.h','host.log','build.log','source-manifest.json','rtl-identity.json'):
        shutil.copyfile(job/name,packet/name)
    for name,digest in source['files'].items():
        lv_packet.safe_name(name);target=packet/'source'/Path(name).name
        if target.exists() or spec.sha(root/name)!=digest:raise ValueError("Source changed/ambiguous")
        shutil.copyfile(root/name,target)
    for name in ('lv_spec.py','lv_audit.py','lv_packet.py','server.py','lv_bench.py','README.md'):
        shutil.copyfile(HERE/name,packet/name)
    shutil.copyfile(spec.reference_path(),packet/'baseline_spec.py')
    helper=HERE.parent/'google_person_pool/model_runner.py'
    if spec.sha(helper)!=spec.QUALIFIED_SHA:raise ValueError("Qualified checker changed")
    shutil.copyfile(helper,packet/'qualified_model.py');shutil.copyfile(root/'LICENSE',packet/'LICENSE')
    (packet/'NOTICES.txt').write_text('Official CoralNPU RVV and VME encodings: Google LLC, Apache-2.0.\n'
        'VME schedule adapted from team fa4b83e4; signed-input correction/packing from qualified project candidate.\n'
        'Firmware-only experiment. No RTL or model weights. NOT an RTL PASS.\n',encoding='utf-8')
    lv_packet.seal(packet,dict(schema=1,kind='llm_vme_linear_firmware_packet_v1',upstream=spec.UPSTREAM,
        hdl_top=spec.TOP,itcm_kib=256,dtcm_kib=512,rtl_sha256=spec.RTL_SHA,elf_sha256=report['elf_sha256'],simulation='NOT_RUN'))
    lv_packet.load(packet);prepare.prepare(root)
    archive=job/(packet.name+'.tar.gz')
    with tarfile.open(archive,'x:gz') as f:f.add(packet,arcname=packet.name)
    digest=spec.sha(archive)
    with (job/(archive.name+'.sha256')).open('x',encoding='utf-8') as f:f.write(digest+'  '+archive.name+'\n')
    print('[LLM_VME_PACKET_READY] RTL_included=false previous_packages_unchanged=true simulation=NOT_RUN')
    print('[LLM_VME_PACKET_ARCHIVE] '+str(archive));print('[LLM_VME_PACKET_SHA256] '+digest)
    print('[LLM_VME_PACKET_BYTES] '+str(archive.stat().st_size))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--upstream',type=Path,required=True);p.add_argument('--job',type=Path,required=True)
    a=p.parse_args();export(a.upstream.resolve(strict=True),a.job.resolve(strict=True))
