"""Facade — token_estimation.py moved to cloudagent_ext/utils/.

The full F-83-era token estimation implementation now lives in
:mod:`cloudagent_ext.utils.token_estimation`. This module re-exports
it verbatim so existing ``from src.token_estimation import ...``
callers keep working without modification.
"""

from cloudagent_ext.utils.token_estimation import *  # noqa: F401,F403

import sys

from cloudagent_ext.utils import token_estimation as _implementation

sys.modules[__name__] = _implementation
