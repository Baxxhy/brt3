"""Compatibility wrapper for formal true-patch evaluation.

Preferred command:
    python -m evaluation.direct_eval
"""

try:
    from .evaluation.direct_eval import main
except ImportError:  # Allows `python direct_eval.py` from brt3.
    from evaluation.direct_eval import main


if __name__ == "__main__":
    main()
