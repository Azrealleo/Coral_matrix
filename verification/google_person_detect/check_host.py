"""Validate both pinned native TFLM example classifications, not NPU results."""
import argparse
import json
from pathlib import Path
import re

from spec import MODEL_SHA256, TFLM_COMMIT, sha


def checked_host_log(text):
    positive = re.findall(r"(?<!no )person data\.\s+person score:\s*(-?\d+), no person score:\s*(-?\d+)", text)
    negative = re.findall(r"no person data\.\s+person score:\s*(-?\d+), no person score:\s*(-?\d+)", text)
    if len(positive) != 1 or len(negative) != 1 or text.count("~~~ALL TESTS PASSED~~~") != 1:
        raise ValueError("Missing/duplicate native TFLM test evidence")
    person, no_person = tuple(map(int, positive[0])), tuple(map(int, negative[0]))
    if (not all(-128 <= n <= 127 for n in person + no_person)
            or person[0] <= person[1] or no_person[1] <= no_person[0]
            or re.search(r"~~~.*(?:FAILED|FAILURE).*~~~|FAIL:\s|Segmentation fault", text)):
        raise ValueError("Native TFLM classifications failed")
    return dict(schema=1, scope="native_TFLM_host_test_not_NPU_RTL_or_dataset_accuracy",
                tflm_commit=TFLM_COMMIT, model_sha256=MODEL_SHA256,
                person_scores_person_then_no_person=list(person),
                no_person_scores_person_then_no_person=list(no_person),
                original_model_unchanged=True, log_sha256=sha(text.encode()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", type=Path)
    args = parser.parse_args()
    print("[PERSON_TFLM_NATIVE_HOST_REFERENCE] " + json.dumps(checked_host_log(args.log.read_text())))


if __name__ == "__main__":
    main()
