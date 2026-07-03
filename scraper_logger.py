"""Шим совместимости: код перенесён в mektep_core/scraper_logger.py. Не редактируйте этот файл."""
import sys

from mektep_core import scraper_logger as _impl

sys.modules[__name__] = _impl
