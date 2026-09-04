"""Make the report-slides script package importable from any pytest rootdir.

The modules in this directory are plain top-level modules, not an installed
package, and the tests import them by bare name (`import presentation_gates`).
Collecting the directory happens to work because pytest prepends the argument's
basedir, but collecting a single test file under `tests/` does not, because
`tests/` is not a package: the inserted basedir is `tests/`, not this directory.
Anchoring sys.path here makes every invocation behave the same, which is what
lets the plans' per-file `Run:` commands work without a bootstrap preamble in
each test module.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
