# Copyright © 2026 CunaWare.Lab
# SPDX-License-Identifier: GPL-3.0-only

import io
import json
import zipfile

import pytest

from tubiblia.module_catalog import CatalogError, parse_registry
from tubiblia.module_store import ModuleFormatError, ModuleStore
from tests.helpers import create_test_module


def registry_archive(registry):
    contents = json.dumps(registry).encode("utf-8")
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("registry.json", b"\xef\xbb\xbf" + contents)
    return archive.getvalue()


def test_parses_catalog_modules_and_skips_non_bible_entries():
    registry = {
        "hosts": [
            {
                "alias": "main",
                "path": "https://mybible.zone/repository/modules/%s.zip",
            }
        ],
        "downloads": [
            {
                "abr": "TEST",
                "fil": "TestModule",
                "lng": "es",
                "des": "<b>Traducción de prueba</b>",
                "inf": "Aviso <i>de derechos</i>",
                "upd": "2026-01-02",
                "siz": "1 MB",
                "bkq": "66",
                "url": ["{main}TestModule"],
            },
            {
                "abr": "PLAN",
                "fil": "Plan",
                "lng": "es",
                "des": "Plan de lectura",
                "bkq": "0",
                "url": ["{main}Plan"],
            },
        ],
    }

    modules = parse_registry(registry_archive(registry))

    assert len(modules) == 1
    module = modules[0]
    assert module.abbreviation == "TEST"
    assert module.description == "Traducción de prueba"
    assert module.information == "Aviso de derechos"
    assert module.book_count == 66
    assert module.download_url == (
        "https://mybible.zone/repository/modules/TestModule.zip"
    )


def test_derives_language_from_real_registry_lds_translations():
    registry = {
        "hosts": [
            {
                "alias": "main",
                "path": "https://mybible.zone/repository/modules/%s.zip",
            }
        ],
        "downloads": [
            {
                "abr": "BLP",
                "fil": "BLP",
                "des": "La Palabra (BLP), versión española, 2010",
                "lds": [
                    {"lng": "es", "des": "La Palabra (BLP), versión española, 2010"},
                    {"lng": "en", "des": "La Palabra (BLP), Spanish version, 2010"},
                ],
                "bkq": "66",
                "url": ["{main}BLP"],
            },
            {
                "abr": "ESE",
                "fil": "ESE",
                "des": "Español Sagradas Escrituras (1569)",
                "lds": None,
                "lng": "es",
                "bkq": "66",
                "url": ["{main}ESE"],
            },
            {
                "abr": "NONLANG",
                "fil": "NonLang",
                "des": "Sin idioma usable",
                "lds": [{"lng": "  ", "des": "vacío"}, "no-es-dict"],
                "bkq": "66",
                "url": ["{main}NonLang"],
            },
        ],
    }

    modules = parse_registry(registry_archive(registry))
    by_abbreviation = {module.abbreviation: module for module in modules}

    assert by_abbreviation["BLP"].language == "es"
    assert by_abbreviation["ESE"].language == "es"
    assert by_abbreviation["NONLANG"].language == ""
    # Sin licencia en el registro: el aviso legal queda vacío y el diálogo
    # muestra su mensaje de "comprueba los permisos".
    assert by_abbreviation["BLP"].information == ""


@pytest.mark.parametrize(
    "host_template",
    [
        "http://mybible.zone/modules/%s.zip",
        "https://evil.example/modules/%s.zip",
        "https://mybible.zone:444/modules/%s.zip",
        "https://user@mybible.zone/modules/%s.zip",
    ],
)
def test_rejects_untrusted_catalog_download_hosts(host_template):
    registry = {
        "hosts": [{"alias": "main", "path": host_template}],
        "downloads": [],
    }

    with pytest.raises(CatalogError, match="servidor HTTPS"):
        parse_registry(registry_archive(registry))


def test_rejects_module_stem_mismatch_in_catalog_url():
    registry = {
        "hosts": [
            {
                "alias": "main",
                "path": "https://mybible.zone/repository/modules/%s.zip",
            }
        ],
        "downloads": [
            {
                "abr": "TEST",
                "fil": "TestModule",
                "lng": "es",
                "des": "Traducción",
                "bkq": "66",
                "url": ["{main}AnotherModule"],
            }
        ],
    }

    with pytest.raises(CatalogError, match="no contiene módulos"):
        parse_registry(registry_archive(registry))


def test_imports_validated_sqlite_module_from_archive(tmp_path):
    source = create_test_module(tmp_path / "TestModule.SQLite3")
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.write(source, "modules/TestModule.SQLite3")

    store = ModuleStore(tmp_path / "app-data")
    imported = store.import_module_archive(archive.getvalue(), "TestModule")

    assert imported.name == "Módulo de prueba"
    assert imported.path.parent == store.modules_directory
    assert imported.path.read_bytes() == source.read_bytes()
    assert not tuple(store.modules_directory.glob(".module-download-*"))


def test_imports_generic_mybible_module_filename_from_archive(tmp_path):
    source = create_test_module(tmp_path / "RVR60.SQLite3")
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.write(source, ".SQLite3")
        zipped.writestr(".commentaries.SQLite3", b"commentary companion")

    store = ModuleStore(tmp_path / "app-data")
    imported = store.import_module_archive(archive.getvalue(), "RVR60")

    assert imported.name == "Módulo de prueba"
    assert imported.path.read_bytes() == source.read_bytes()


def test_archive_import_rejects_mismatched_module_and_cleans_temporary_file(
    tmp_path,
):
    source = create_test_module(tmp_path / "Different.SQLite3")
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.write(source, "Different.SQLite3")

    store = ModuleStore(tmp_path / "app-data")
    with pytest.raises(ModuleFormatError, match="no contiene exactamente"):
        store.import_module_archive(archive.getvalue(), "Expected")

    assert not tuple(store.modules_directory.iterdir())
