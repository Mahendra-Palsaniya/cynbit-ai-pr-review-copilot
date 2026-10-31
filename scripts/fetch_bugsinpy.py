"""Fetch a bounded pinned BugsInPy selection; never import or execute corpus code."""

import argparse
import json
from pathlib import Path
import urllib.request

COMMITS = {
    1: "26c9465a22c732ab1e17b0dec578fa3432e9b558",
    2: "c8ca6b2b9ff3510bee12129824cebfc2fc51e5b2",
    3: "8126b4f6a9342290de4655e6a8a78cd288ce7daa",
    4: "65ea568e3301951f26e0e3b98f6d5dc80132e917",
    5: "1bbb01b854d168d76ebe4bf78961c2152ae075d9",
}


def fetch(url):
    if not url.startswith("https://raw.githubusercontent.com/"):
        raise ValueError("Unsupported source host")
    with urllib.request.urlopen(url, timeout=20) as response:  # nosec B310
        data = response.read(400001)
    if len(data) > 400000:
        raise ValueError("Response exceeds bounded source-file limit")
    return data.decode("utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    rows = []
    for ident, commit in COMMITS.items():
        base = f"https://raw.githubusercontent.com/soarsmu/BugsInPy/master/projects/black/bugs/{ident}/"
        info = fetch(base + "bug.info")
        if f'buggy_commit_id="{commit}"' not in info:
            raise ValueError("Upstream metadata changed; inspect before proceeding")
        rows.append(
            {
                "id": ident,
                "info": info,
                "patch": fetch(base + "bug_patch.txt"),
                "source": fetch(
                    f"https://raw.githubusercontent.com/psf/black/{commit}/black.py"
                ),
            }
        )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(rows), encoding="utf-8")
    print("Fetched five pinned buggy sources and metadata; no code executed.")
