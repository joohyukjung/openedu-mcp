"""
HTTP entrypoint for OpenEdu MCP Server (Goover MCP Hub deployment).

Runs the server over streamable-http transport by invoking main_http()
from main.py. The original stdio entrypoint (main.py's main(), run via
`python src/main.py`) is left completely untouched.

Must be run with the repository root as the working directory, since
config.py resolves "config/default.yaml" relative to the process cwd.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import main

if __name__ == "__main__":
    main.main_http()