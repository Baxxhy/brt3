"""Compatibility wrapper for the BRT3 generation CLI.

Preferred command:
    python -m cli.run
"""

try:
    from .cli.run import main
except ImportError:  # Allows `python run.py` from the brt3 directory.
    from cli.run import main


if __name__ == "__main__":
    main()
