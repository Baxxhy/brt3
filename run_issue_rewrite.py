"""Compatibility wrapper for the issue rewrite CLI.

Preferred command:
    python -m cli.run_issue_rewrite
"""

try:
    from .cli.run_issue_rewrite import main
except ImportError:  # Allows `python run_issue_rewrite.py` from brt3.
    from cli.run_issue_rewrite import main


if __name__ == "__main__":
    main()
