import sys

from map_overlay import OVERLAY_FLAG, run_overlay_process
from scum_gui_app import run_scum_gui


if __name__ == "__main__":
    # Child process for F1 map overlay (separate UI thread from tkinter).
    if len(sys.argv) >= 3 and sys.argv[1] == OVERLAY_FLAG:
        raise SystemExit(run_overlay_process(sys.argv[2]))
    run_scum_gui()
