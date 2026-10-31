"""Pin the installed direct/transitive dependency closure for the documented Python 3.11 environment."""

import importlib.metadata as metadata
from pathlib import Path
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOTS = ["streamlit", "pydantic", "ruff", "bandit", "openai", "pytest", "reportlab"]


def generate():
    pending = list(ROOTS)
    locked = {}
    conflicts = []
    while pending:
        name = canonicalize_name(pending.pop())
        if name in locked:
            continue
        dist = metadata.distribution(name)
        locked[name] = dist.version
        for text in dist.requires or []:
            requirement = Requirement(text)
            if requirement.marker and not requirement.marker.evaluate({"extra": ""}):
                continue
            installed = metadata.version(requirement.name)
            if requirement.specifier and installed not in requirement.specifier:
                conflicts.append(
                    requirement.name + " does not satisfy " + str(requirement.specifier)
                )
            pending.append(requirement.name)
    if conflicts:
        raise RuntimeError("; ".join(conflicts))
    header = [
        "# Fully pinned installed dependency closure for Python 3.11.",
        "# Generated with python -m scripts.lock_dependencies; roots: "
        + ", ".join(ROOTS),
        "# Resolution is verified against installed package metadata; wheels are not hash-locked.",
        "# Re-run clean CI on the target OS. No unrelated environment packages are included.",
    ]
    Path("requirements.lock").write_text(
        "\n".join(
            header + [f"{name}=={version}" for name, version in sorted(locked.items())]
        )
        + "\n"
    )
    print("Pinned", len(locked), "direct/transitive dependencies")


if __name__ == "__main__":
    generate()
