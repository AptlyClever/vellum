"""Re-vendor ctrl-alt-axiom/backend/auth into vellum/backend/auth.

Deterministic so re-running it after upstream changes produces exactly the vendored
tree again — a vendoring step that cannot be repeated is a vendoring step that drifts.
"""
from pathlib import Path
import re

SRC = Path(r"C:\dev\ctrl-alt-axiom\backend\auth")
DST = Path(r"C:\dev\vellum\backend\auth")

HEADER = """\
# ---------------------------------------------------------------------------
# VENDORED - DO NOT EDIT HERE.
#
# Source of truth: C:\\dev\\ctrl-alt-axiom\\backend\\auth\\{name}
# (repo `ctrl-alt-axiom`, path `backend/auth/{name}`)
#
# This file is a verbatim copy carried into Vellum so that every service in the
# fleet decides "is this token good?" with identical code. A divergent copy is
# worse than no copy: two validators that disagree about audience or algorithm
# produce a boundary that holds in one service and not the other, and nobody
# finds out until the weaker one is the one that matters.
#
# If this needs to change, change it upstream in ctrl-alt-axiom and re-vendor
# into every consumer. Fixing it only here is how the fleet acquires a security
# control that is true in one repo and false in three.
#
# ONE intentional deviation from upstream, and the only one permitted:
# intra-package imports are RELATIVE (`from .jwt_validator import ...`) instead
# of upstream's absolute `from auth.jwt_validator import ...`. Axiom puts its
# `backend/` directory on `sys.path`, so `auth` is a top-level package there.
# Vellum imports its code as `backend.*` (pyproject `pythonpath = ["."]`,
# Dockerfile `PYTHONPATH=/app`), so the same absolute import would raise
# ModuleNotFoundError at startup. Relative imports resolve correctly under
# either layout, so this deviation cannot drift back into a bug.
#
# Re-vendor with: python tools/vendor_auth.py (see that script's docstring).
# ---------------------------------------------------------------------------

"""

FILES = ["__init__.py", "jwt_validator.py", "client_credentials.py", "dependencies.py"]

DST.mkdir(parents=True, exist_ok=True)
for name in FILES:
    text = (SRC / name).read_text(encoding="utf-8")
    text = re.sub(r"^from auth\.", "from .", text, flags=re.MULTILINE)
    (DST / name).write_text(HEADER.format(name=name) + text, encoding="utf-8")
    print(f"vendored {name}: {len(text)} bytes")
