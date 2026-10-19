"""Synthetic/local checks; neither NPU execution nor native TFLM test PASS."""
import io
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

import check_host
import firmware_report as report
import prepare_person as prepare
import reference
import spec


def synthetic_elf(model=b"x" * 32, architecture=243, input_in_bss=False):
    """ELF32 tables/load data for the resource checker, NOT executable firmware."""
    align = lambda n: (n + 15) // 16 * 16
    input_offset = align(len(model))
    output_offset = align(input_offset + spec.INPUT_BYTES)
    file_data = model + bytes(input_offset - len(model)) + bytes([1]) + bytes(spec.INPUT_BYTES - 1)
    file_data += bytes(output_offset - len(file_data)) + bytes([37, 53])
    arena_offset = align(len(file_data))
    static_end = spec.DTCM_BASE + arena_offset + spec.ARENA_BYTES
    stack_end = spec.DTCM_BASE + 512 * 1024
    stack_start = stack_end - spec.STACK_BYTES
    entries = {
        "pd_model": (spec.DTCM_BASE, len(model)),
        "pd_input": (spec.DTCM_BASE + (arena_offset if input_in_bss else input_offset), spec.INPUT_BYTES),
        "pd_output": (spec.DTCM_BASE + output_offset, 2),
        "pd_tensor_arena": (spec.DTCM_BASE + arena_offset, spec.ARENA_BYTES),
        "pd_status": (static_end, 4), "pd_arena_used": (static_end + 4, 4),
        "pd_invoke_cycles": (static_end + 8, 4),
        "__heap_start__": (align(static_end + 12), 0), "__heap_end__": (stack_start, 0),
        "__stack_start__": (stack_start, 0), "__stack_end__": (stack_end, 0),
        "__stack_size": (spec.STACK_BYTES, 0),
    }
    names, symbols = b"\0", bytes(16)
    for name, (address, size) in entries.items():
        index = len(names)
        names += name.encode() + b"\0"
        symbols += struct.pack("<IIIBBH", index, address, size, 17, 0,
                               0xFFF1 if name == "__stack_size" else 2)
    blob = bytearray(0x2000)
    blob[0x1000:0x1080] = bytes([0x13, 0, 0, 0]) * 32
    blob.extend(file_data)
    names_at = len(blob)
    blob.extend(names)
    symbols_at = len(blob)
    blob.extend(symbols)
    section_names = b"\0.text\0.data\0.strtab\0.symtab\0.shstrtab\0"
    section_names_at = len(blob)
    blob.extend(section_names)
    sections_at = len(blob)
    sections = [bytes(40)]
    def section(name, typ, flags, address, offset, size, link=0, info=0, alignment=1, entry_size=0):
        return struct.pack("<IIIIIIIIII", section_names.index(name.encode() + b"\0"), typ, flags,
                           address, offset, size, link, info, alignment, entry_size)
    sections += [section(".text", 1, 6, 0, 0x1000, 128, alignment=16),
                 section(".data", 1, 3, spec.DTCM_BASE, 0x2000, len(file_data), alignment=16),
                 section(".strtab", 3, 0, 0, names_at, len(names)),
                 section(".symtab", 2, 0, 0, symbols_at, len(symbols), link=3, info=1, alignment=4, entry_size=16),
                 section(".shstrtab", 3, 0, 0, section_names_at, len(section_names))]
    blob.extend(b"".join(sections))
    ident = b"\x7fELF\x01\x01\x01" + bytes(9)
    blob[:52] = struct.pack("<16sHHIIIIIHHHHHH", ident, 2, architecture, 1, 0, 52, sections_at,
                            0, 52, 32, 2, 40, len(sections), 5)
    blob[52:84] = struct.pack("<IIIIIIII", 1, 0x1000, 0, 0, 128, 128, 5, 16)
    blob[84:116] = struct.pack("<IIIIIIII", 1, 0x2000, spec.DTCM_BASE, spec.DTCM_BASE,
                              len(file_data), spec.DTCM_KIB * 1024, 6, 16)
    return bytes(blob)


class HostChecks(unittest.TestCase):
    text = "person data.  person score: 90, no person score: -90\nno person data.  person score: -100, no person score: 100\n~~~ALL TESTS PASSED~~~\n"

    def test_two_classes(self):
        result = check_host.checked_host_log(self.text)
        self.assertEqual(result["person_scores_person_then_no_person"], [90, -90])
        self.assertIn("not_NPU", result["scope"])

    def test_missing_duplicate_wrong_class(self):
        for value in ("", self.text * 2, self.text.replace("90, no person score: -90", "-90, no person score: 90"),
                      self.text.replace("~~~ALL TESTS PASSED~~~", ""), self.text + "FAIL: test\n"):
            with self.assertRaises(ValueError):
                check_host.checked_host_log(value)

    def test_fixture_preserves_official_encoded_bytes(self):
        image = Image.fromarray(np.full((96, 96), 255, dtype=np.uint8))
        stream = io.BytesIO()
        image.save(stream, format="BMP")
        data = reference.fixture(stream.getvalue())
        self.assertEqual(data.shape, (1, 96, 96, 1))
        self.assertTrue(np.all(data == -1))  # No second subtraction of 128.

    def test_fixture_rejects_wrong_geometry(self):
        stream = io.BytesIO()
        Image.new("L", (95, 96)).save(stream, format="BMP")
        with self.assertRaises(ValueError):
            reference.fixture(stream.getvalue())


class ResourceChecks(unittest.TestCase):
    def test_candidate_margin(self):
        self.assertEqual(report.recommend_itcm(8192), 16)
        self.assertEqual(report.recommend_itcm(100), 8)
        self.assertIsNone(report.recommend_itcm(512 * 1024))
        for bad in (0, 512 * 1024 + 1):
            with self.assertRaises(ValueError):
                report.recommend_itcm(bad)

    def test_synthetic_resources_and_model_identity(self):
        with patch.multiple(report, MODEL_BYTES=32, MODEL_SHA256=spec.sha(b"x" * 32)):
            result = report.inspect_elf(synthetic_elf())
        self.assertEqual(result["itcm_occupied_extent_bytes"], 128)
        self.assertEqual(result["stack_reserved_bytes"], 16384)
        self.assertEqual(result["arena_actual_used_bytes"], "NOT_RUN")
        self.assertIn("NOT_INFERENCE", result["status"])
        self.assertTrue(result["original_model_bytes_equal"])

    def test_wrong_architecture(self):
        with self.assertRaises(ValueError):
            report.inspect_elf(synthetic_elf(architecture=62))

    def test_changed_model_is_rejected(self):
        with patch.multiple(report, MODEL_BYTES=32, MODEL_SHA256=spec.sha(b"y" * 32)):
            with self.assertRaises(ValueError):
                report.inspect_elf(synthetic_elf())

    def test_crt_would_erase_input_is_rejected(self):
        with patch.multiple(report, MODEL_BYTES=32, MODEL_SHA256=spec.sha(b"x" * 32)):
            with self.assertRaises(ValueError):
                report.inspect_elf(synthetic_elf(input_in_bss=True))

    def test_resolve_exact_configured_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "bazel-out/config/bin/tests/person_program.elf"
            path.parent.mkdir(parents=True)
            path.write_bytes(synthetic_elf())
            relative = path.relative_to(root).as_posix()
            self.assertEqual(report.resolve(root, relative), path.resolve())
            for listing in ("", "../person_program.elf", "/tmp/person_program.elf", "bazel-out/else.elf"):
                with self.assertRaises(ValueError):
                    report.resolve(root, listing)


class SourceChecks(unittest.TestCase):
    def test_installer_owns_only_new_package_and_refuses_changed_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "tcm_capacity_manifest.json").write_text("{}")
            files = {prepare.PACKAGE + "/BUILD": b"synthetic build\n",
                     prepare.PACKAGE + "/person_program.cc": b"synthetic source\n"}
            with patch.object(prepare.capacity, "verify", return_value={}), \
                 patch.object(prepare.capacity, "git", return_value=("tflite-micro/archive/" + spec.TFLM_COMMIT + ".zip").encode()), \
                 patch.object(prepare, "checked_asset", return_value=b"synthetic"), \
                 patch.object(prepare, "expected_files", return_value=files), \
                 patch.object(prepare, "evidence", return_value={"synthetic_test_only": True}):
                first = prepare.prepare(root, root)
                self.assertEqual(first, prepare.prepare(root, root))
                target = root / prepare.PACKAGE / "person_program.cc"
                target.write_bytes(b"KEEP_USER_CHANGE")
                with self.assertRaises(ValueError):
                    prepare.prepare(root, root)
                self.assertEqual(target.read_bytes(), b"KEEP_USER_CHANGE")

    def test_installer_refuses_unowned_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "tcm_capacity_manifest.json").write_text("{}")
            (root / prepare.PACKAGE).mkdir(parents=True)
            with patch.object(prepare.capacity, "verify", return_value={}), \
                 patch.object(prepare.capacity, "git", return_value=("tflite-micro/archive/" + spec.TFLM_COMMIT + ".zip").encode()), \
                 patch.object(prepare, "checked_asset", return_value=b"synthetic"), \
                 patch.object(prepare, "expected_files", return_value={}):
                with self.assertRaises(ValueError):
                    prepare.prepare(root, root)
                self.assertFalse((root / prepare.MANIFEST).exists())

    def test_firmware_baseline_is_explicit(self):
        text = (Path(__file__).parent / "person_program.cc").read_text()
        self.assertIn("Register_DEPTHWISE_CONV_2D_INT8", text)
        self.assertIn("pd_input[kPersonInputBytes] = {1}", text)
        self.assertNotIn("ZvtMatmul", text)
        self.assertIn("arena_used_bytes", text)
        self.assertIn("itcm_size_kbytes = 512", prepare.build_text())
        self.assertIn("dtcm_size_kbytes = 512", prepare.build_text())

    def test_model_source_refuses_substitution(self):
        with self.assertRaises(ValueError):
            prepare.model_source(b"not the model")

    def test_actual_pinned_assets_if_downloaded(self):
        root = Path(__file__).resolve().parents[2] / ".upstream-git/model-cache/person_detect_b75c6ff4"
        if not (root / spec.MODEL_NAME).is_file():
            self.skipTest("Original assets not downloaded")
        for name in spec.ASSETS:
            spec.checked_asset(root, name)
        source = prepare.model_source(spec.checked_asset(root, spec.MODEL_NAME)).decode()
        self.assertIn('.data.pd_model', source)
        values = source.split("= {\n", 1)[1].rsplit("\n};", 1)[0]
        self.assertEqual(bytes(int(n) for n in values.replace("\n", "").split(",")),
                         spec.checked_asset(root, spec.MODEL_NAME))
        inventory = reference.inspect_bytes(spec.checked_asset(root, spec.MODEL_NAME))
        self.assertEqual(inventory["outputs"][0]["shape"], [1, 2])
        self.assertEqual(inventory["operator_counts"]["DEPTHWISE_CONV_2D"], 14)
        self.assertEqual(inventory["largest_nonconstant_tensor"]["bytes"], 36864)


if __name__ == "__main__":
    unittest.main()
