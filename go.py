

# go.py
"""
Simple launcher script for your FastAPI application using Uvicorn.
Run with: python go.py
"""

import uvicorn
import sys
from pathlib import Path

# Optional: Automatically detect the project root and adjust sys.path if needed
project_root = Path(__file__).parent.resolve()
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

def main():
    # ┌──────────────────────────────────────────────────────────────┐
    # │                  Configuration goes here                     │
    # └──────────────────────────────────────────────────────────────┘

    APP_MODULE = "app.main:app"      # ← change only if your structure is different
    HOST = "127.0.0.1"                # "0.0.0.0" if you want network access
    PORT = 8000
    RELOAD = True                     # Set to False in production
    LOG_LEVEL = "info"                # debug / info / warning / error / critical

    # ┌──────────────────────────────────────────────────────────────┐
    # │                     Don't change below                       │
    # └──────────────────────────────────────────────────────────────┘

    print(f"Starting server at http://{HOST}:{PORT}")
    if RELOAD:
        print("→ Auto-reload is ENABLED (development mode)")
    else:
        print("→ Auto-reload is DISABLED")

    try:
        uvicorn.run(
            APP_MODULE,
            host=HOST,
            port=PORT,
            reload=RELOAD,
            log_level=LOG_LEVEL,
            # Optional extra settings you might want to enable later:
            # workers=1,                    # only meaningful when reload=False
            # factory=False,                # set True if your app is a factory function
            # timeout_keep_alive=65,
            # limit_concurrency=1000,
        )
    except KeyboardInterrupt:
        print("\nServer stopped by user")
    except Exception as e:
        print(f"Server failed to start: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()