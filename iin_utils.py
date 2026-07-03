"""Шим совместимости: код перенесён в mektep_core/iin_utils.py. Не редактируйте этот файл."""
import sys

from mektep_core import iin_utils as _impl

sys.modules[__name__] = _impl
