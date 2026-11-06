"""PyInstaller entry point. bchat.__main__ uses relative imports, so it can't be the script itself."""
import sys

from bchat.__main__ import main

sys.exit(main())
