"""Шим совместимости: код перенесён в mektep_core/scrape_mektep.py. Не редактируйте этот файл."""
import sys

from mektep_core import scrape_mektep as _impl

sys.modules[__name__] = _impl

if __name__ == "__main__":
    raise SystemExit(_impl.main())
