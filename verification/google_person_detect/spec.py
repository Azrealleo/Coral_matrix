"""Fixed pretrained two-class model identity. No training or model conversion."""
import hashlib
from pathlib import Path

TFLM_COMMIT = "b75c6ff4e2270047f2b48fa01f833c8101c31f43"
UPSTREAM = "8e4df09b4ea7e065e02d14ce3ae033d40dfd973a"
MODEL_NAME = "person_detect.tflite"
MODEL_SHA256 = "808cfdfc0cf3a6fa6f6fa26bfa379ea97c16d5db7334637766e39c3408502e9d"
MODEL_BYTES = 300568
INPUT_BYTES = 96 * 96
DTCM_BASE = 0x01000000
DTCM_KIB = 512
ITCM_LINK_KIB = 512  # Link ceiling for measurement, NOT a chosen RTL capacity.
ARENA_BYTES = 160 * 1024
STACK_BYTES = 16 * 1024
LABELS = ("no_person", "person")
ASSETS = {
    MODEL_NAME: ("tensorflow/lite/micro/models/" + MODEL_NAME, MODEL_SHA256),
    "person.bmp": ("tensorflow/lite/micro/examples/person_detection/testdata/person.bmp",
                   "b50a4d51e86551ea13038c96c222b9c3aaf653f5946211e5e5fd3e60b029e4d2"),
    "no_person.bmp": ("tensorflow/lite/micro/examples/person_detection/testdata/no_person.bmp",
                      "2322df94e6788b05e4051e531f7a3a95b6db54624d170ebc9af2f1d5a73e9f79"),
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def checked_asset(directory, name):
    data = (Path(directory) / name).read_bytes()
    if sha(data) != ASSETS[name][1]:
        raise ValueError("Pinned asset hash mismatch: " + name)
    if name == MODEL_NAME and len(data) != MODEL_BYTES:
        raise ValueError("Pinned model size mismatch")
    return data


def asset_url(name):
    return "https://raw.githubusercontent.com/tensorflow/tflite-micro/" + TFLM_COMMIT + "/" + ASSETS[name][0]
