# Copyright © 2026 CunaWare.Lab
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import logging
from collections.abc import Callable

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtWidgets import (
    QDialog,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)
from PySide6.QtCore import QRunnable, QObject, QThreadPool

from tubiblia.module_catalog import (
    CatalogModule,
    download_module_archive,
    fetch_catalog,
)
from tubiblia.module_store import ModuleMetadata, ModuleStore


class _TaskSignals(QObject):
    succeeded = Signal(str, object)
    failed = Signal(str, object)


class _CatalogTask(QRunnable):
    def __init__(self, name: str, operation: Callable[[], object]):
        super().__init__()
        self.name = name
        self.operation = operation
        self.signals = _TaskSignals()

    @Slot()
    def run(self) -> None:
        try:
            result = self.operation()
        except Exception as exc:
            logging.exception("Falló la operación del catálogo de módulos")
            self.signals.failed.emit(self.name, exc)
        else:
            self.signals.succeeded.emit(self.name, result)


class ModuleCatalogDialog(QDialog):
    module_installed = Signal(object)

    def __init__(self, store: ModuleStore, parent=None):
        super().__init__(parent)
        self.store = store
        self.modules: tuple[CatalogModule, ...] = ()
        self._worker: _CatalogTask | None = None
        self._thread_pool = QThreadPool(self)

        self.setWindowTitle("Descargar módulos bíblicos")
        self.resize(760, 560)
        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                "Catálogo oficial de módulos MyBible. La lectura descargada se "
                "guardará localmente en este equipo."
            )
        )

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Filtrar por nombre, sigla o idioma…")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self._populate_modules)
        layout.addWidget(self.search_edit)

        language_filter = QHBoxLayout()
        language_filter.addWidget(QLabel("Idioma:"))
        self.language_combo = QComboBox()
        self.language_combo.addItem("Español (es)", "es")
        self.language_combo.addItem("Todos los idiomas", None)
        self.language_combo.currentIndexChanged.connect(self._populate_modules)
        language_filter.addWidget(self.language_combo, 1)
        layout.addLayout(language_filter)

        self.module_list = QListWidget()
        self.module_list.currentItemChanged.connect(self._selection_changed)
        layout.addWidget(self.module_list, 1)

        self.details_label = QLabel("Conectando con el catálogo oficial…")
        self.details_label.setWordWrap(True)
        self.details_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(self.details_label)

        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        buttons = QHBoxLayout()
        self.refresh_button = QPushButton("Actualizar catálogo")
        self.refresh_button.clicked.connect(self._refresh_catalog)
        buttons.addWidget(self.refresh_button)
        buttons.addStretch(1)
        self.download_button = QPushButton("Descargar e instalar")
        self.download_button.setEnabled(False)
        self.download_button.clicked.connect(self._confirm_download)
        buttons.addWidget(self.download_button)
        self.close_button = QPushButton("Cerrar")
        self.close_button.clicked.connect(self.reject)
        buttons.addWidget(self.close_button)
        layout.addLayout(buttons)

        self._refresh_catalog()

    def _set_busy(self, busy: bool) -> None:
        self.refresh_button.setEnabled(not busy)
        self.search_edit.setEnabled(not busy)
        self.language_combo.setEnabled(not busy)
        self.module_list.setEnabled(not busy)
        self.download_button.setEnabled(
            not busy and self.module_list.currentItem() is not None
        )
        self.close_button.setEnabled(not busy)

    def _start_task(self, name: str, operation: Callable[[], object]) -> None:
        worker = _CatalogTask(name, operation)
        worker.signals.succeeded.connect(self._task_succeeded)
        worker.signals.failed.connect(self._task_failed)
        self._worker = worker
        self._set_busy(True)
        self._thread_pool.start(worker)

    def _refresh_catalog(self) -> None:
        if self._worker is not None:
            return
        self.status_label.setText("Consultando el catálogo oficial de MyBible…")
        self.details_label.setText("")
        self._start_task("catalog", fetch_catalog)

    @Slot(str, object)
    def _task_succeeded(self, name: str, result: object) -> None:
        self._worker = None
        self._set_busy(False)
        if name == "catalog":
            self.modules = result
            selected_language = self.language_combo.currentData()
            self.language_combo.blockSignals(True)
            self.language_combo.clear()
            self.language_combo.addItem("Español (es)", "es")
            self.language_combo.addItem("Todos los idiomas", None)
            languages = sorted(
                {
                    module.language
                    for module in self.modules
                    if module.language
                    and module.language.casefold() != "es"
                },
                key=str.casefold,
            )
            for language in languages:
                self.language_combo.addItem(language, language)
            selected_index = self.language_combo.findData(selected_language)
            self.language_combo.setCurrentIndex(
                selected_index if selected_index >= 0 else 0
            )
            self.language_combo.blockSignals(False)
            self._populate_modules()
            self.status_label.setText(f"Catálogo actualizado: {len(self.modules)} módulos.")
            return
        if name == "install" and isinstance(result, ModuleMetadata):
            self.module_installed.emit(result)
            self.accept()

    @Slot(str, object)
    def _task_failed(self, name: str, error: object) -> None:
        self._worker = None
        self._set_busy(False)
        message = str(error)
        self.status_label.setText("No se pudo completar la operación.")
        title = "No se pudo cargar el catálogo" if name == "catalog" else "No se pudo instalar"
        QMessageBox.warning(self, title, message)

    def _populate_modules(self) -> None:
        query = self.search_edit.text().strip().casefold()
        selected_language = self.language_combo.currentData()
        self.module_list.clear()
        for module in self.modules:
            if (
                selected_language is not None
                and module.language.casefold() != selected_language.casefold()
            ):
                continue
            searchable = " ".join(
                (module.description, module.abbreviation, module.language)
            ).casefold()
            if query and query not in searchable:
                continue
            language = f" · {module.language}" if module.language else ""
            size = f" · {module.size}" if module.size else ""
            item = QListWidgetItem(
                f"{module.description} ({module.abbreviation})"
                f"{language}{size} · {module.book_count} libros"
            )
            item.setData(Qt.ItemDataRole.UserRole, module)
            self.module_list.addItem(item)
        self.download_button.setEnabled(self.module_list.currentItem() is not None)

    def _selection_changed(self, current, _previous) -> None:
        module = current.data(Qt.ItemDataRole.UserRole) if current else None
        if not isinstance(module, CatalogModule):
            self.details_label.setText("")
            self.download_button.setEnabled(False)
            return
        details = [
            f"{module.description} ({module.abbreviation})",
            f"Idioma: {module.language or 'no especificado'}",
            f"Libros: {module.book_count}",
        ]
        if module.updated:
            details.append(f"Actualización publicada: {module.updated}")
        if module.size:
            details.append(f"Tamaño publicado: {module.size}")
        if module.information:
            details.append(f"Información y derechos: {module.information}")
        else:
            details.append(
                "El registro no especifica una licencia. Comprueba los permisos "
                "aplicables a este módulo."
            )
        self.details_label.setText("\n".join(details))
        self.download_button.setEnabled(self._worker is None)

    def _confirm_download(self) -> None:
        item = self.module_list.currentItem()
        module = item.data(Qt.ItemDataRole.UserRole) if item else None
        if not isinstance(module, CatalogModule):
            return
        confirmation = QMessageBox.question(
            self,
            "Descargar módulo",
            f"Se descargará «{module.description}» desde el catálogo de MyBible "
            "y se instalará en el almacenamiento local de TuBiblia.\n\n"
            "La inclusión en el catálogo no concede derechos de redistribución. "
            "Revisa la información y las condiciones del módulo.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirmation != QMessageBox.StandardButton.Yes:
            return
        self.status_label.setText(f"Descargando e instalando {module.abbreviation}…")

        def download_and_install() -> ModuleMetadata:
            archive = download_module_archive(module)
            return self.store.import_module_archive(archive, module.file_stem)

        self._start_task("install", download_and_install)

    def closeEvent(self, event) -> None:
        if self._worker is not None:
            event.ignore()
            return
        super().closeEvent(event)
