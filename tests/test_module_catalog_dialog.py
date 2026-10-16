# Copyright © 2026 CunaWare.Lab
# SPDX-License-Identifier: GPL-3.0-only

import io
import time
import zipfile

from PySide6.QtWidgets import QMessageBox

from tubiblia import module_catalog_dialog
from tubiblia.module_catalog import CatalogModule
from tubiblia.module_catalog_dialog import ModuleCatalogDialog
from tubiblia.module_store import ModuleStore
from tests.helpers import create_test_module


def wait_for_worker(qapp, dialog):
    deadline = time.monotonic() + 3
    while dialog._worker is not None and time.monotonic() < deadline:
        qapp.processEvents()
        qapp.processEvents()
        time.sleep(0.01)
    qapp.processEvents()
    assert dialog._worker is None


def test_dialog_loads_filters_and_displays_catalog_metadata(qapp, tmp_path, monkeypatch):
    spanish_module = CatalogModule(
        abbreviation="TEST",
        file_stem="TestModule",
        language="es",
        description="Traducción de prueba",
        information="Uso sujeto a permiso",
        updated="2026-01-02",
        size="1 MB",
        book_count=66,
        download_url="https://mybible.zone/repository/modules/TestModule.zip",
    )
    afrikaans_module = CatalogModule(
        abbreviation="AFR",
        file_stem="Afrikaans",
        language="af",
        description="Afrikaanse Bybel",
        information="",
        updated="",
        size="",
        book_count=66,
        download_url="https://mybible.zone/repository/modules/Afrikaans.zip",
    )
    monkeypatch.setattr(
        module_catalog_dialog,
        "fetch_catalog",
        lambda: (afrikaans_module, spanish_module),
    )

    dialog = ModuleCatalogDialog(ModuleStore(tmp_path / "app-data"))
    wait_for_worker(qapp, dialog)

    assert dialog.module_list.count() == 1
    assert dialog.module_list.item(0).text().startswith("Traducción de prueba")
    dialog.module_list.setCurrentRow(0)
    assert "Idioma: es" in dialog.details_label.text()
    assert "Uso sujeto a permiso" in dialog.details_label.text()
    assert dialog.download_button.isEnabled()

    dialog.language_combo.setCurrentIndex(1)
    assert dialog.module_list.count() == 2
    dialog.language_combo.setCurrentIndex(
        dialog.language_combo.findData("af")
    )
    assert dialog.module_list.count() == 1
    assert dialog.module_list.item(0).text().startswith("Afrikaanse Bybel")

    dialog.search_edit.setText("no existe")
    assert dialog.module_list.count() == 0
    assert not dialog.download_button.isEnabled()
    dialog.close()


def test_dialog_downloads_and_installs_selected_module(
    qapp, tmp_path, monkeypatch
):
    module = CatalogModule(
        abbreviation="TEST",
        file_stem="TestModule",
        language="es",
        description="Traducción de prueba",
        information="Uso sujeto a permiso",
        updated="",
        size="",
        book_count=66,
        download_url="https://mybible.zone/repository/modules/TestModule.zip",
    )
    monkeypatch.setattr(module_catalog_dialog, "fetch_catalog", lambda: (module,))
    monkeypatch.setattr(
        module_catalog_dialog,
        "download_module_archive",
        lambda _module: archive_for(tmp_path),
    )
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes,
    )
    store = ModuleStore(tmp_path / "app-data")
    dialog = ModuleCatalogDialog(store)
    installed = []
    dialog.module_installed.connect(installed.append)
    dialog.show()
    wait_for_worker(qapp, dialog)

    dialog.module_list.setCurrentRow(0)
    dialog.download_button.click()
    wait_for_worker(qapp, dialog)

    modules, errors = store.scan_modules()
    assert not errors
    assert len(modules) == 1
    assert len(installed) == 1
    assert installed[0].sha256 == modules[0].sha256
    assert dialog.result() == dialog.DialogCode.Accepted


def archive_for(tmp_path):
    source = create_test_module(tmp_path / "TestModule.SQLite3")
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.write(source, "TestModule.SQLite3")
    return archive.getvalue()
