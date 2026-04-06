import os
import logging
from unittest.mock import patch

# Must be set before recordimporter is imported during collection.
os.environ.setdefault("PIHOLE_API_KEY", "test-secret-key")

# Patch logging.FileHandler so the module-level handler for /opt/pihole-api.log
# doesn't fail on machines where that path doesn't exist.
_fh_patcher = patch("logging.FileHandler", return_value=logging.NullHandler())
_fh_patcher.start()

import recordimporter  # noqa: E402 — triggers import under patches

_fh_patcher.stop()
