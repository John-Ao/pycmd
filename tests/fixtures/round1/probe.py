"""Deterministic stream helper; does not inspect the host environment."""
import os
import sys

if sys.argv[1:] != ["streams"]:
    raise SystemExit("Expected streams mode")
os.write(1, b"OUT\r\n")
os.write(2, b"ERR\r\n")
