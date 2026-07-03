"""Шим совместимости: код перенесён в mektep_core/build_report.py. Не редактируйте этот файл."""
import sys

from mektep_core import build_report as _impl

sys.modules[__name__] = _impl

if __name__ == "__main__":
    raise SystemExit(_impl.main())
