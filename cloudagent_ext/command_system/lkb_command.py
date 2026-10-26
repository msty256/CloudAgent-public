"""Compatibility alias for the optional LKB slash-command integration."""

import sys

from lkb import cloudagent_commands as _implementation

sys.modules[__name__] = _implementation
