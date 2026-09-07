"""``python -m mamori`` -- the same command line as the ``mamori`` script.

Not decoration. Sora's rule, arrived at from two libraries at once, is that a
program is asked about itself by running the program: `mamori errors --json`
has to be the program, not a command line assembled from a manifest that was
written for something else. The console script needs the environment's
``bin``/``Scripts`` directory on ``PATH``; ``python -m`` needs only an
interpreter that can import this package, which is one fewer thing that can be
set up wrongly in a container or a CI job.

The exit code is the one :func:`~mamori.interfaces.cli.main.main` returns, so
the catalogue in `mamori errors --json` describes this entry point too.
"""

from __future__ import annotations

import sys

from .interfaces.cli.main import main

if __name__ == "__main__":
    sys.exit(main())
