"""Fetch hash-pinned official assets, never overwrite an existing file."""
import argparse
from pathlib import Path
from urllib.request import urlopen

from spec import ASSETS, asset_url, checked_asset, sha


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    args.directory.mkdir(parents=True, exist_ok=True)
    for name, (_, expected) in ASSETS.items():
        path = args.directory / name
        if path.exists():
            checked_asset(args.directory, name)
            print("[PERSON_ASSET_REUSED] " + name)
            continue
        # Numeric fixtures/model only; preserve original bytes. No code executes.
        with urlopen(asset_url(name), timeout=90) as response:
            data = response.read(2 * 1024 * 1024 + 1)
        if len(data) > 2 * 1024 * 1024 or sha(data) != expected:
            raise ValueError("Download size/hash mismatch: " + name)
        with path.open("xb") as stream:
            stream.write(data)
        checked_asset(args.directory, name)
        print("[PERSON_ASSET_VERIFIED] " + name + " sha256=" + expected)


if __name__ == "__main__":
    main()
