"""One-off: split webapp/views/admin.py into admin/ package."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
src = ROOT / "webapp/views/admin.py"
lines = src.read_text(encoding="utf-8").splitlines(keepends=True)

header = "".join(lines[0:96])
helpers = "".join(lines[99:150])
mgmt = "".join(lines[151:723])
reports = "".join(lines[723:])

init_body = """bp = Blueprint("admin", __name__, url_prefix="/admin")

from . import exports, management, reports  # noqa: E402, F401
"""

init_content = header + "\n" + init_body + "\n" + helpers

sub_header = header.replace(
    'bp = Blueprint("admin", __name__, url_prefix="/admin")\n\n',
    "from . import bp\n\n",
)

out = ROOT / "webapp/views/admin"
out.mkdir(exist_ok=True)
(out / "__init__.py").write_text(init_content, encoding="utf-8")
(out / "management.py").write_text(sub_header + helpers + mgmt, encoding="utf-8")
(out / "reports.py").write_text(sub_header + helpers + reports, encoding="utf-8")
print("Wrote", out)
