# Copyright © 2026 CunaWare.Lab
# SPDX-License-Identifier: GPL-3.0-only

import sqlite3

import pytest

from tubiblia.module_store import (
    BibleModule,
    ModuleFormatError,
    ModuleStore,
    inspect_module,
)
from tests.helpers import create_test_module


def test_imports_and_reads_module_metadata(tmp_path):
    source = create_test_module(tmp_path / "source.SQLite3")
    store = ModuleStore(tmp_path / "app-data")

    imported = store.import_module(source)

    assert imported.name == "Módulo de prueba"
    assert imported.language == "es"
    assert imported.book_count == 2
    assert imported.verse_count == 4
    assert imported.path.parent == store.modules_directory
    assert imported.path != source
    assert inspect_module(imported.path).sha256 == imported.sha256


def test_import_is_idempotent_and_original_is_unchanged(tmp_path):
    source = create_test_module(tmp_path / "source.SQLite3")
    store = ModuleStore(tmp_path / "app-data")
    original_bytes = source.read_bytes()

    first = store.import_module(source)
    second = store.import_module(source)

    assert first.path == second.path
    assert source.read_bytes() == original_bytes
    assert len(list(store.modules_directory.glob("*.SQLite3"))) == 1


def test_reads_books_chapters_and_verses(tmp_path):
    source = create_test_module(tmp_path / "source.SQLite3")
    module = BibleModule(source)

    assert [(book.number, book.long_name) for book in module.books()] == [
        (1, "Libro de prueba"),
        (2, "Segundo libro"),
    ]
    assert module.chapters(1) == (1, 2)
    assert [verse.verse for verse in module.verses(1, 1)] == [1, 2]
    assert module.chapter_references() == ((1, 1), (1, 2), (2, 1))


def test_search_is_case_insensitive_and_keeps_accents(tmp_path):
    source = create_test_module(tmp_path / "source.SQLite3")
    module = BibleModule(source)

    results = module.search("CAFÉ")

    assert len(results) == 1
    assert (results[0].book_number, results[0].chapter, results[0].verse) == (
        1,
        1,
        2,
    )
    assert module.search("cafe") == ()
    assert module.search("   ") == ()


def test_search_limit_is_respected(tmp_path):
    source = create_test_module(tmp_path / "source.SQLite3")
    module = BibleModule(source)

    results = module.search("muestra", limit=1)

    assert len(results) == 1
    with pytest.raises(ValueError):
        module.search("muestra", limit=0)


def test_rejects_sqlite_file_without_mybible_tables(tmp_path):
    source = tmp_path / "not-a-bible.SQLite3"
    connection = sqlite3.connect(source)
    try:
        connection.execute("CREATE TABLE unrelated (value TEXT)")
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(ModuleFormatError, match="Faltan tablas"):
        inspect_module(source)


def test_scan_reports_invalid_modules_instead_of_hiding_them(tmp_path):
    store = ModuleStore(tmp_path / "app-data")
    invalid = store.modules_directory / "invalid.SQLite3"
    invalid.write_bytes(b"not a SQLite database")

    modules, errors = store.scan_modules()

    assert modules == ()
    assert len(errors) == 1
    assert "invalid.SQLite3" in errors[0]
