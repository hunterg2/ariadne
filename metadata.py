"""Compatibility shim. The module now lives at ariadne/metadata.py; this keeps
``python metadata.py IMAGE ...`` working from the repository root."""

import sys

from ariadne.metadata import main

if __name__ == "__main__":
    sys.exit(main())
