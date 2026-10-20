"""Synthetic export tests, not generated-RTL or NPU validation."""
import io
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import numpy as np
from PIL import Image

import export_person as export
import portable
import reference
import spec


def bmp():
    stream = io.BytesIO()
    pixels = np.arange(9216, dtype=np.uint16).reshape(96, 96).astype(np.uint8)
    Image.fromarray(pixels).save(stream, format="BMP")
    return stream.getvalue()


class ExportChecks(unittest.TestCase):
    def test_bmp_decoder_matches_official_byte_semantics(self):
        data = bmp()
        self.assertEqual(export.fixture_bytes(data), reference.fixture(data).tobytes())
        root = Path(__file__).resolve().parents[2] / ".upstream-git/model-cache/person_detect_b75c6ff4"
        for name in ("person.bmp", "no_person.bmp"):
            if (root / name).exists():
                original = spec.checked_asset(root, name)
                self.assertEqual(export.fixture_bytes(original), reference.fixture(original).tobytes())

    def test_bmp_rejects_geometry_palette_truncation(self):
        data = bmp()
        bad_size = bytearray(data)
        struct.pack_into("<i", bad_size, 18, 95)
        bad_palette = bytearray(data)
        bad_palette[54] = 1
        for value in (data[:-1], data + b"x", bad_size, bad_palette):
            with self.assertRaises(ValueError):
                export.fixture_bytes(value)

    def test_generator_and_parameter_checks(self):
        self.assertIn("--itcmSizeKBytes=256", export.build_text())
        self.assertIn("--dtcmSizeKBytes=512", export.build_text())
        self.assertIn(export.TOP, export.build_text())
        self.assertNotIn("cocotb_test_suite", export.build_text())
        values = dict(xlen="32", itcmSizeKBytes="256", dtcmSizeKBytes="512", axi2IdBits="6",
                      rvvVlen="128", fetchDataBits="128", lsuDataBits="128", enableFetchL0="false",
                      enableRvv="true", enableVme="true", enableFloat="true", enableZfbfmin="true",
                      enableVectorBf16="true", enableAxiInstructionFetch="true", enableVerification="false")
        text = "\n".join("#define KP_" + k + " " + v for k, v in values.items())
        self.assertEqual(export.checked_header(text), values)
        for wrong in (text.replace("KBytes 256", "KBytes 8"),
                      text.replace("InstructionFetch true", "InstructionFetch false")):
            with self.assertRaises(ValueError):
                export.checked_header(wrong)

    def test_configured_outputs_reject_missing_duplicate_and_escape(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            paths = ["bazel-out/cfg/bin/" + n for n in
                     (export.TOP + ".sv", export.TOP + ".zip", "V" + export.TOP + "_parameters.h")]
            for name in paths:
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"synthetic")
            self.assertEqual(len(export.configured_outputs(root, "\n".join(paths))), 3)
            for listing in ("\n".join(paths[:2]), "\n".join(paths + paths[:1]),
                            "../" + export.TOP + ".sv", str(root / paths[0])):
                with self.assertRaises(ValueError):
                    export.configured_outputs(root, listing)

    def test_prepare_refuses_unowned_or_changed_directory(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(export, "evidence", return_value=({}, {})), \
             patch.object(export.prepare_person.capacity, "verify", return_value={}):
            root = Path(directory)
            (root / export.prepare_person.MANIFEST).write_bytes(b"synthetic")
            export.prepare(root, root, root)
            export.prepare(root, root, root)
            (root / export.PACKAGE / "BUILD").write_bytes(b"KEEP USER CHANGE")
            with self.assertRaises(ValueError):
                export.prepare(root, root, root)
            self.assertEqual((root / export.PACKAGE / "BUILD").read_bytes(), b"KEEP USER CHANGE")
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(export, "evidence", return_value=({}, {})):
            root = Path(directory)
            (root / export.prepare_person.MANIFEST).write_bytes(b"synthetic")
            (root / export.PACKAGE).mkdir(parents=True)
            with self.assertRaises(ValueError):
                export.prepare(root, root, root)
            self.assertFalse((root / export.MANIFEST).exists())

    def test_evidence_requires_host_results_same_elf_and_fits_selected_capacity(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(export.prepare_person, "prepare", return_value={}), \
             patch.object(export.firmware_report, "inspect_elf") as inspect:
            root = Path(directory)
            (root / "manifest.json").write_text("{}")
            (root / "host-pass.log").write_text("[PERSON_TFLM_NATIVE_HOST_TEST_PASS] NPU_RTL=NOT_RUN\n")
            text = ("person data. person score: 113, no person score: -113\n"
                    "no person data. person score: -57, no person score: 57\n~~~ALL TESTS PASSED~~~\n")
            (root / "host-test-command.log").write_text(text)
            host = export.check_host.checked_host_log(text)
            (root / "host-reference.json.log").write_text("[PERSON_TFLM_NATIVE_HOST_REFERENCE] " + json.dumps(host))
            (root / "person_program.elf").write_bytes(b"SYNTHETIC NOT EXECUTABLE")
            report = dict(candidate_itcm_kib_with_25pct_margin=256, entry=0,
                          segments=[dict(address=0, bytes=136080),
                                    dict(address=spec.DTCM_BASE, bytes=512 * 1024)])
            inspect.return_value = report
            (root / "resources.json").write_text(json.dumps(report))
            self.assertEqual(export.evidence(root, root, root), (host, report))
            report["segments"][0]["bytes"] = 256 * 1024 + 1
            (root / "resources.json").write_text(json.dumps(report))
            with self.assertRaises(ValueError):
                export.evidence(root, root, root)
            report["segments"][0]["bytes"] = 136080
            with self.assertRaises(ValueError):
                export.evidence(root, root, root)  # Recorded resources changed.

    def test_full_synthetic_export_seals_and_rejects_modification(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(export, "prepare"), patch.object(export, "evidence") as evidence, \
             patch.object(export.prepare_person.capacity, "git", return_value=b"SYNTHETIC LICENSE/SOURCE"), \
             patch.object(export, "checked_asset") as asset:
            root = Path(directory).resolve()
            run, job, generated = root / "run", root / "job", root / "bazel-out/cfg/bin"
            for path in (run, job, generated):
                path.mkdir(parents=True)
            elf = b"SYNTHETIC NOT EXECUTABLE"
            (run / "person_program.elf").write_bytes(elf)
            for name in ("manifest.json", "resources.json", "host-test-command.log", "host-reference.json.log",
                         "host-pass.log", "build.log"):
                (run / name).write_text("synthetic evidence")
            for name in (export.prepare_person.MANIFEST, export.MANIFEST, "tcm_capacity_manifest.json"):
                (root / name).write_text("synthetic manifest")
            for name in ("build.log", "build-command.txt", "export_rtl.sh"):
                (job / name).write_text("synthetic command")
            names = [export.TOP + ".sv", export.TOP + ".zip", "V" + export.TOP + "_parameters.h"]
            (generated / names[0]).write_bytes(b"SYNTHETIC RTL NOT SIMULATED")
            (generated / names[2]).write_text("SYNTHETIC HEADER")
            with zipfile.ZipFile(generated / names[1], "w") as stream:
                stream.writestr("filelist.f", "+define+" + "+".join(sorted(set(export.DEFINES) - {"ZVTBF16FMM_ON"}))
                                + "\n" + export.TOP + ".sv\nSram.v\n")
                stream.writestr(export.TOP + ".sv", b"synthetic")
                stream.writestr("Sram.v", b"synthetic")
            (job / "execution-root.txt").write_text(str(root) + "\n")
            (job / "rtl-outputs.txt").write_text("\n".join("bazel-out/cfg/bin/" + n for n in names))
            evidence.return_value = (dict(tflm_commit=spec.TFLM_COMMIT,
                                          person_scores_person_then_no_person=[113, -113],
                                          no_person_scores_person_then_no_person=[-57, 57]),
                                     dict(elf_sha256=spec.sha(elf)))
            asset.side_effect = lambda _, name: bmp() if name.endswith(".bmp") else b"synthetic model"
            with patch.object(export, "checked_header", return_value={}):
                export.export(root, root, run, job)
            package = job / "coral_person_i256_d512"
            manifest = portable.verify(package)
            self.assertEqual(manifest["reference_scores_no_person_then_person"]["person"], [-113, 113])
            self.assertEqual(manifest["simulation"], "NOT_RUN")
            self.assertTrue((job / "coral_person_i256_d512.tar.gz.sha256").exists())
            (package / "firmware/person_program.elf").write_bytes(b"KEEP USER CHANGE")
            with self.assertRaises(ValueError):
                portable.verify(package)
            with self.assertRaises(ValueError):
                export.export(root, root, run, job)


if __name__ == "__main__":
    unittest.main()
