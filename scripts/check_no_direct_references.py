"""Assert the built distributions carry no PEP 508 direct references.

    python check_no_direct_references.py dist/*

What this measures: that no entry in `Requires-Dist` has a URL.

Why it is not covered by anything else here. A single direct reference makes
warehouse reject `requires_dist`, and it rejects the *whole distribution*, not
just the extra that carries it. Every existing check in this family passes with
one present -- measured, not assumed, on 2026-08-30 against a real tree:

    hatchling build                     fails -- but the error names the flag
      + allow-direct-references = true  builds
    twine check                         PASSED
    "the dependency count is zero"      PASS  (it filters out `extra ==`)
    "assert nothing came with it"       PASS  (it installs without extras)

The build error is the only local signal, and the shortest way to silence it is
to set the flag it names. After that nothing here says a word until upload.

This asks a different question from the dependency-count checks. Those ask how
many dependencies there are. This asks whether the result can be published.
"""

from __future__ import annotations

import re
import sys
import tarfile
import zipfile
from email.parser import BytesParser
from pathlib import Path

# PEP 508 spells a direct reference `name [extras] @ URL ; marker`. Neither a
# version specifier nor an environment marker can contain a top-level `@`, so
# an `@` before the first `;` identifies one unambiguously.
_DIRECT = re.compile(r"^[^;]*?\s@\s")


def _metadata_of(path: Path) -> bytes:
    if path.suffix == ".whl":
        with zipfile.ZipFile(path) as archive:
            name = next(n for n in archive.namelist() if n.endswith(".dist-info/METADATA"))
            return archive.read(name)
    if path.name.endswith(".tar.gz"):
        with tarfile.open(path) as archive:
            member = next(m for m in archive.getmembers() if m.name.endswith("/PKG-INFO"))
            handle = archive.extractfile(member)
            assert handle is not None, f"unreadable PKG-INFO in {path}"
            return handle.read()
    raise ValueError(f"neither a wheel nor an sdist: {path}")


def main(argv: list[str]) -> int:
    paths = [Path(a) for a in argv[1:]]

    # An empty argument list must not report zero violations. A glob that
    # matched nothing is an unproven result, not a negative one.
    if not paths:
        print("FATAL: no distributions given; this is not a pass", file=sys.stderr)
        return 2

    failed = False
    for path in paths:
        if not path.exists():
            print(f"FATAL: {path} does not exist; this is not a pass", file=sys.stderr)
            return 2
        requirements = BytesParser().parsebytes(_metadata_of(path))
        reqs = requirements.get_all("Requires-Dist") or []
        bad = [r for r in reqs if _DIRECT.match(r)]
        if bad:
            failed = True
            print(f"FAIL {path.name}: {len(bad)} direct reference(s)")
            for requirement in bad:
                print(f"       {requirement}")
        else:
            print(f"ok   {path.name}: {len(reqs)} requirements, no direct references")

    if failed:
        print()
        print("PyPI rejects the whole distribution for this, not just the extra.")
        print("Fix: take the dependency out of pyproject.toml and name it in the")
        print("CI job's install step instead. Do not set")
        print("`tool.hatch.metadata.allow-direct-references`.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
