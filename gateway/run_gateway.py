"""Launcher script for the MT5 gateway under Wine.

Wine does not pass PYTHONPATH through to the Windows Python process,
and the CWD is not automatically added to sys.path.  This script
injects the `src/` directory into sys.path before handing off to uvicorn.
"""

import os
import sys

# Add the `src/` directory (relative to this script) to the front of sys.path
src_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "src")
if src_dir not in sys.path:
    sys.path.insert(0, src_dir)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "gateway.main:app",
        host=os.environ.get("GATEWAY_HOST", "127.0.0.1"),
        port=int(os.environ.get("GATEWAY_PORT", "8787")),
    )
