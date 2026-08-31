"""Can this package's name actually be uploaded to PyPI?

Everything else the distribution job checks is about the artefact: it builds,
its metadata passes `twine check`, the wheel installs and works. All of that
can pass on a name that belongs to somebody else, and then the only thing that
fails is the upload -- after a GitHub Release has been created and made public.

The check that stops that has to run here, before anything irreversible. No
amount of checking inside `publish.yml` can help: by the time it runs, the
Release exists.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import tomllib

PYPI = "https://pypi.org/pypi/{name}/json"


def main() -> int:
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))["project"]
    name = project["name"]
    ours = {url.rstrip("/").lower() for url in project.get("urls", {}).values()}

    # The name comes from pyproject.toml, so quote it and check the scheme
    # rather than trusting the template: a distribution name is a string
    # somebody edits, and `urlopen` will happily open a `file:` URL.
    url = PYPI.format(name=urllib.parse.quote(name, safe=""))
    if not url.startswith("https://pypi.org/"):
        print(f"refusing to fetch {url!r}", file=sys.stderr)
        return 1

    try:
        with urllib.request.urlopen(url, timeout=30) as response:  # noqa: S310 -- checked above
            payload = json.loads(response.read())
    except urllib.error.HTTPError as error:
        if error.code == 404:
            print(f"ok: '{name}' is unclaimed on PyPI. The first upload takes it.")
            return 0
        print(f"could not check '{name}' on PyPI: HTTP {error.code}", file=sys.stderr)
        return 1
    except urllib.error.URLError as error:
        # Not skipped on a network failure. A check that quietly passes when it
        # could not run is the defect this whole job exists to avoid.
        print(f"could not reach PyPI to check '{name}': {error.reason}", file=sys.stderr)
        return 1

    theirs = {
        str(url).rstrip("/").lower() for url in (payload["info"].get("project_urls") or {}).values()
    }
    theirs.add(str(payload["info"].get("home_page") or "").rstrip("/").lower())

    if ours & theirs:
        print(f"ok: '{name}' is on PyPI and points back at this repository.")
        return 0

    print(
        f"'{name}' is taken on PyPI by a project that does not link to this "
        f"repository.\n"
        f"  it links to: {sorted(u for u in theirs if u)}\n"
        f"  we are:      {sorted(ours)}\n"
        f"Publishing will be refused. Rename the distribution, or claim the name, "
        f"before creating a release -- a GitHub Release is public the moment it is "
        f"made, and nothing in publish.yml runs before that.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
