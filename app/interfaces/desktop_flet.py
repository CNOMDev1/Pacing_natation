"""Shim de compatibilité — lancer ``python -m pacing.ui.desktop.app``."""
from pacing.ui.desktop.app import *  # noqa: F401,F403

if __name__ == "__main__":
    import flet as ft
    from pacing.ui.desktop.app import main

    ft.run(main)
