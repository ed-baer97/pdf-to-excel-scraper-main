"""Шим совместимости: код перенесён в mektep_core/grade_table_signals.py. Не редактируйте этот файл."""
import sys

from mektep_core import grade_table_signals as _impl

sys.modules[__name__] = _impl
