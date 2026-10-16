# Copyright © 2026 CunaWare.Lab
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QSettings, QStandardPaths
from PySide6.QtWidgets import QApplication, QMessageBox

from tubiblia.main_window import MainWindow
from tubiblia.module_store import ModuleStore


def main() -> int:
    application = QApplication(sys.argv)
    application.setOrganizationName("TuBiblia")
    application.setApplicationName("TuBiblia")
    application.setApplicationVersion("0.1.0")

    data_directory = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.AppDataLocation
    )
    if not data_directory:
        QMessageBox.critical(
            None, "Error de configuración", "Qt no pudo determinar el directorio local."
        )
        return 1
    try:
        store = ModuleStore(Path(data_directory))
    except OSError as exc:
        QMessageBox.critical(
            None,
            "Error de almacenamiento",
            f"No se pudo preparar el directorio de datos:\n{exc}",
        )
        return 1

    window = MainWindow(store, QSettings())
    window.show()
    return application.exec()
