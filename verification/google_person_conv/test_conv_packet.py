"""Synthetic firmware export/acceptance tests; NO measured NPU speedup here."""
import copy
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import conv_contract as contract
import export_conv as exporter
import server_conv as server


def cases():
    return [dict(id=i,name="op"+str(op)+"_m"+str(m)+"_k"+str(k)+"_n"+str(n),
        original_operator_index=op,M=m,K=k,N=n,useful_macs=m*k*n,derived_model_sha256="m"*64,input_sha256="i"*64)
        for i,(op,m,k,n) in enumerate(contract.SHAPES)]


class ConvPacketTests(unittest.TestCase):
    def test_actual_rv32_case_table_contract_and_checksum_rejects_bad_fixture(self):
        class Symbol(dict):
            name="kConvCases"
        class Segment(dict):
            def data(self):return bytes(image)
        image=bytearray(65536);metadata=cases();base=0x01000000
        for i,c in enumerate(metadata):
            model=0x1000+i*0x2000;input_data=model+0x1000;raw=("synthetic model "+str(i)).encode()
            inputs=bytes([i])*c["M"]*c["K"]
            image[model:model+len(raw)]=raw;image[input_data:input_data+len(inputs)]=inputs
            c["derived_model_sha256"]=hashlib.sha256(raw).hexdigest();c["input_sha256"]=hashlib.sha256(inputs).hexdigest()
            struct.pack_into("<9I",image,36*i,base+model,base+input_data,len(raw),len(inputs),
                c["original_operator_index"],c["M"],c["K"],c["N"],0)
        sym=Symbol(st_value=base,st_size=180,st_shndx=2)
        elf=SimpleNamespace(get_section_by_name=lambda _:SimpleNamespace(iter_symbols=lambda:[sym]),
            iter_segments=lambda:[Segment(p_type="PT_LOAD",p_paddr=base,p_filesz=len(image))])
        with patch.object(contract,"ELFFile",return_value=elf):
            linked=contract.layout(b"synthetic",metadata)
            self.assertEqual(linked["0"]["input"]["bytes"],128)
            image[0x1000]^=1
            with self.assertRaisesRegex(ValueError,"fixture bytes differ"):contract.layout(b"synthetic",metadata)
            sym["st_size"]=179
            with self.assertRaisesRegex(ValueError,"ConvCase table"):contract.layout(b"synthetic",metadata)

    def test_export_complete_synthetic_packet_without_rtl_and_preserves_source(self):
        with tempfile.TemporaryDirectory() as directory:
            top=Path(directory);root=top/"source";root.mkdir();run=top/"run";run.mkdir();job=top/"job";job.mkdir()
            elf=b"synthetic ELF only, not actual NPU";digest=hashlib.sha256(elf).hexdigest();metadata=cases()
            rel="tests/cocotb/person_conv_bench_v1/conv_bench.cc"
            path=root/rel;path.parent.mkdir(parents=True);path.write_bytes(b"synthetic source")
            identity=dict(cases=metadata,files={rel:hashlib.sha256(path.read_bytes()).hexdigest()},
                upstream=contract.common.UPSTREAM,source_model_sha256=contract.common.MODEL_SHA,scope=contract.SCOPE)
            (root/"LICENSE").write_text("synthetic license fixture")
            report=dict(elf_sha256=digest,NPU_RTL="NOT_RUN")
            host={c["name"]:dict(checked_elements=4*c["M"]*c["N"],signature=137) for c in metadata}
            text=''.join("[PERSON_CONV_HOST_CASE] id="+str(c["id"])+" name="+c["name"]+" checked="+
                str(4*c["M"]*c["N"])+" signature=137 ref_and_emulated_vme_equal=true\n" for c in metadata)
            text+="[PERSON_CONV_HOST_PASS] cases=5 complete_model=NOT_RUN hardware=NOT_RUN\n"
            for n,value in (("manifest.json",identity),("resources.json",report),("host-signatures.json",host)):
                (run/n).write_text(json.dumps(value))
            (run/"conv_program.elf").write_bytes(elf);(run/"host-test.log").write_text(text);(run/"build.log").write_text("synthetic link")
            before={str(p):contract.sha(p) for p in root.rglob("*") if p.is_file()}
            with patch.object(exporter.prepare_conv,"prepare",return_value=identity), \
                 patch.object(exporter.audit_conv,"inspect",return_value=report), \
                 patch.object(contract,"ELF_SHA",digest),patch.object(contract,"layout",return_value={"synthetic":"no addresses"}):
                exporter.export(root,top,run,job)
                packet=job/"coral_person_conv_v1"
                manifest=contract.verify(packet);self.assertEqual(manifest["cases"],metadata)
                self.assertFalse((packet/"rtl").exists())
                self.assertEqual(server.load_packet(packet).native,host)
                cli=subprocess.run([sys.executable,"-B",str(packet/"server_conv.py"),"--help"],
                    cwd=top,capture_output=True,text=True,timeout=30)
                self.assertEqual(cli.returncode,0,cli.stderr)
                self.assertEqual(before,{str(p):contract.sha(p) for p in root.rglob("*") if p.is_file()})
                self.assertTrue((job/"coral_person_conv_v1.tar.gz.sha256").is_file())
                (packet/"conv_program.elf").write_bytes(b"changed")
                with self.assertRaisesRegex(ValueError,"missing/extra/changed"):contract.verify(packet)

    def test_real_cycle_acceptance_requires_exact_path_correctness_and_samples(self):
        with tempfile.TemporaryDirectory() as directory:
            xml=Path(directory)/"results.xml";xml.write_text('<testsuites><testcase name="conv_rtl_test"/></testsuites>')
            metadata=cases();c=metadata[0]
            packet=SimpleNamespace(manifest=dict(cases=metadata,elf_sha256=contract.ELF_SHA,source_model_sha256=contract.common.MODEL_SHA),
                native={c["name"]:dict(checked_elements=1024,signature=137)})
            rtl=SimpleNamespace(manifest={"rtl_sha256":"r"*64})
            row=dict(schema=1,scope=contract.SCOPE,case_id=0,case=c["name"],M=16,K=8,N=16,useful_macs_per_call=2048,
                elf_sha256=contract.ELF_SHA,rtl_sha256="r"*64,source_model_sha256=contract.common.MODEL_SHA,
                derived_model_sha256="m"*64,input_sha256="i"*64,fixture_model_readback_equal=True,input_readback_equal=True,
                itcm_kib=256,dtcm_kib=512,fault=False,natural_halt=True,firmware_status=3,stack_low_canary_intact=True,
                requested_cycles=2000000,cases=1,checked=1024,signature=137,mismatches=0,commands=8,
                vme_calls=4,vme_fallbacks=0,vme_mismatches=0,vme_internal_validations=0,vme_commands=8,
                observation_elapsed_cycles=20000,empty_boundary_cycles=4,reference_cycles=[1000,1000,1000,1000],
                vme_cycles=[500,500,500,500],arena_used_reference=4096,arena_used_vme=4096)
            check=lambda r:server.checked_results(server.MARKER+json.dumps(r),xml,packet,rtl,0,2000000)
            self.assertEqual(check(row),row);self.assertEqual(server.summary(row)["steady_ref_over_vme"],2)
            # Slower optimization is a valid measurement, not a failed result.
            slow=dict(row,vme_cycles=[2000,2000,2000,2000])
            self.assertEqual(server.summary(check(slow))["steady_ref_over_vme"],0.5)
            for change in (dict(natural_halt=False),dict(fault=True),dict(firmware_status=2),dict(firmware_status=True),
                           dict(mismatches=1),dict(signature=0),dict(vme_calls=3),dict(vme_fallbacks=1),
                           dict(vme_internal_validations=1),dict(commands=9),dict(vme_commands=0),
                           dict(vme_cycles=[0,0,0,0]),dict(reference_cycles=[1,2,3]),dict(checked=256),
                           dict(reference_cycles=[20000]*4),dict(arena_used_vme=65537),dict(case_id=1)):
                with self.subTest(change=change),self.assertRaises(ValueError):check(dict(row,**change))
            xml.write_text('<testsuites><testcase name="conv_rtl_test"><failure/></testcase></testsuites>')
            with self.assertRaises(ValueError):check(row)

    def test_command_counts_cover_tails_and_do_not_claim_retirement(self):
        self.assertEqual([server.commands_per_case(c) for c in cases()],[8,128,2048,4096,256])
        self.assertEqual(server.helper().BASE_SHA,"597dfe711e95ee9168be7c77b32a39c0ebc02a97444a6fe8fa5025210914593a")
        bench=(Path(__file__).parent/"conv_rtl_bench.py").read_text()
        self.assertNotIn("model_runner.py infer",bench)
        self.assertIn('fixture.write_word("pd_conv_case",case_id)',bench)


if __name__=="__main__":unittest.main()
