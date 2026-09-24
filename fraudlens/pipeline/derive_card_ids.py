"""Compatibility entry point for the validated card-map derivation.

Use :mod:`pipeline.derive_card_ids_final`; this wrapper prevents the old
hypothesis-only script from accidentally replacing the validated map.
"""
from __future__ import annotations

from derive_card_ids_final import main


if __name__ == "__main__":
    raise SystemExit(main())
