from __future__ import annotations

import os
import sys
import tkinter as tk
from pathlib import Path
from tkinter import messagebox


def _show_startup_error(title: str, message: str) -> None:
    root = tk.Tk()
    root.withdraw()
    root.after(50, lambda: messagebox.showerror(title, message))
    root.after(250, root.destroy)
    root.mainloop()


def main() -> None:
    project_root = Path(__file__).resolve().parent
    src_dir = project_root / "src"

    os.chdir(project_root)
    if str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))

    try:
        from gui import main as gui_main
    except SystemExit as error:
        _show_startup_error("Inicio GUI", str(error))
        return
    except Exception as error:
        _show_startup_error(
            "Inicio GUI",
            "No fue posible iniciar la interfaz grafica.\n\n"
            f"Detalle: {error}"
        )
        return

    gui_main()


if __name__ == "__main__":
    main()
