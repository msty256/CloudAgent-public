"""``python -m cloudagent_ext.cli`` — parity with the old ``python -m src.cli``."""

from __future__ import annotations

import sys

from cloudagent_ext.cli._legacy_surface import main

if __name__ == "__main__":
    sys.exit(main())
