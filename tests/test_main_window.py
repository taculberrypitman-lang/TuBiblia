# Copyright © 2026 CunaWare.Lab
# SPDX-License-Identifier: GPL-3.0-only

import sqlite3

from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QLabel,
    QListWidget,
    QPushButton,
    QToolButton,
)

from tubiblia.main_window import MainWindow, _display_verse_text
from tubiblia.assets import asset_path
from tubiblia.module_store import ModuleStore
from tests.helpers import create_test_module


def make_settings(path):
    return QSettings(str(path), QSettings.Format.IniFormat)


def test_empty_state_explains_how_to_import_a_bible(qapp, tmp_path):
    window = MainWindow(
        ModuleStore(tmp_path / "app-data"),
        make_settings(tmp_path / "settings.ini"),
    )

    assert window.pages.currentWidget() is window.empty_page
    assert window.empty_import_button.isEnabled()
    assert not window.search_edit.isEnabled()
    assert asset_path("fondo_pergamo.jpg").is_file()
    assert asset_path("logo_tu_biblia.png").is_file()
    assert not window.windowIcon().isNull()
    assert window.logo_label.pixmap() is not None
    assert not window.logo_label.pixmap().isNull()
    assert "color: #000000" in window.styleSheet()
    assert "QToolBar QLabel { color: #40516a; }" in window.styleSheet()
    window.close()


def test_navigation_search_and_position_persist(qapp, tmp_path):
    source = create_test_module(tmp_path / "source.SQLite3")
    store = ModuleStore(tmp_path / "app-data")
    metadata = store.import_module(source)
    settings_path = tmp_path / "settings.ini"
    window = MainWindow(store, make_settings(settings_path))

    assert window.current_module.metadata.sha256 == metadata.sha256
    assert window.pages.currentWidget() is window.reader_page
    assert window.search_edit.isEnabled()
    assert window.chapter_combo.count() == 2

    results = window.search_text("CAFÉ")
    assert [(result.book_name, result.chapter, result.verse) for result in results] == [
        ("Libro de prueba", 1, 2)
    ]

    window.search_edit.setText("CAFÉ")

    def open_first_search_result():
        dialog = QApplication.activeModalWidget()
        result_list = dialog.findChild(QListWidget)
        result_list.setCurrentRow(0)
        dialog.findChild(QPushButton, "openReferenceButton").click()

    QTimer.singleShot(0, open_first_search_result)
    window.run_search()
    assert window.chapter_combo.currentData() == 1
    assert window._verse_rows[2].property("selectedVerse") is True

    window.navigate_to(1, 2, 1)
    assert window.chapter_combo.currentData() == 2
    assert window.statusBar().currentMessage().endswith("1 versículo")
    window.close()

    reopened = MainWindow(store, make_settings(settings_path))
    assert reopened.current_module.metadata.sha256 == metadata.sha256
    assert reopened.book_list.currentItem().text() == "Libro de prueba"
    assert reopened.chapter_combo.currentData() == 2
    reopened.close()


def test_verse_formatting_removes_mybible_markup_and_decodes_entities():
    assert _display_verse_text(
        "<f>En el principio</f><br/>Dijo &amp; respondió."
    ) == "En el principio\nDijo & respondió."
    assert _display_verse_text("Antes<pb/>Después.") == "Antes\n\nDespués."
    assert _display_verse_text("Texto &lt;literal&gt;") == "Texto <literal>"


def test_reader_uses_solid_parchment_and_preserves_source_module(qapp, tmp_path):
    source = create_test_module(tmp_path / "source.SQLite3")
    original_text = "<pb/><f>Texto</f> &amp; prueba."
    with sqlite3.connect(source) as connection:
        connection.execute(
            "UPDATE verses SET text = ? WHERE book_number = 1 AND chapter = 1 "
            "AND verse = 1",
            (original_text,),
        )
        connection.commit()

    store = ModuleStore(tmp_path / "app-data")
    store.import_module(source)
    window = MainWindow(store, make_settings(tmp_path / "settings.ini"))

    verse_text = window.findChild(QLabel, "verseText")
    assert verse_text is not None
    assert verse_text.text() == "Texto & prueba."
    assert verse_text.textFormat() == Qt.TextFormat.PlainText
    with sqlite3.connect(source) as connection:
        stored_text = connection.execute(
            "SELECT text FROM verses WHERE book_number = 1 AND chapter = 1 "
            "AND verse = 1"
        ).fetchone()[0]
    assert stored_text == original_text

    window.resize(1180, 760)
    window.show()
    qapp.processEvents()
    rendered = window.verse_content.grab().toImage()
    assert rendered.pixelColor(10, rendered.height() - 10).name() == "#ead9b5"
    window.close()


def test_chapter_navigation_crosses_book_boundaries(qapp, tmp_path):
    source = create_test_module(tmp_path / "source.SQLite3")
    store = ModuleStore(tmp_path / "app-data")
    store.import_module(source)
    window = MainWindow(
        store,
        make_settings(tmp_path / "settings.ini"),
    )

    window.navigate_to(1, 2)
    window.move_chapter(1)
    assert window.book_list.currentItem().text() == "Segundo libro"
    assert window.chapter_combo.currentData() == 1

    window.move_chapter(-1)
    assert window.book_list.currentItem().text() == "Libro de prueba"
    assert window.chapter_combo.currentData() == 2
    window.close()


def test_reading_toolbar_uses_accessible_transport_controls(qapp, tmp_path, monkeypatch):
    source = create_test_module(tmp_path / "source.SQLite3")
    store = ModuleStore(tmp_path / "app-data")
    store.import_module(source)
    window = MainWindow(store, make_settings(tmp_path / "settings.ini"))
    controller = window.tts_controller
    calls = []
    monkeypatch.setattr(controller, "read_chapter", lambda *args: calls.append("play"))
    monkeypatch.setattr(controller, "pause", lambda: calls.append("pause"))
    monkeypatch.setattr(controller, "resume", lambda: calls.append("resume"))
    monkeypatch.setattr(controller, "stop", lambda: calls.append("stop"))

    play_pause = window.findChild(QToolButton, "playPauseButton")
    stop = window.findChild(QToolButton, "stopReadingButton")
    assert play_pause is not None
    assert stop is not None
    assert play_pause.text() == "▶"
    assert play_pause.accessibleName() == "Leer capítulo"
    assert not stop.isEnabled()

    play_pause.click()
    assert calls == ["play"]

    controller._state = "playing"
    window._on_tts_state_changed("playing")
    assert play_pause.text() == "Ⅱ"
    assert play_pause.accessibleName() == "Pausar lectura"
    assert stop.isEnabled()
    play_pause.click()
    assert calls[-1] == "pause"

    controller._state = "paused"
    window._on_tts_state_changed("paused")
    assert play_pause.text() == "▶"
    assert play_pause.accessibleName() == "Reanudar lectura"
    play_pause.click()
    assert calls[-1] == "resume"
    stop.click()
    assert calls[-1] == "stop"
    window.close()


def test_voice_language_and_voice_are_persisted(qapp, tmp_path):
    settings_path = tmp_path / "settings.ini"
    window = MainWindow(
        ModuleStore(tmp_path / "app-data"), make_settings(settings_path)
    )

    def select_french_voice():
        language_combo = window.findChild(QComboBox, "voiceLanguageCombo")
        voice_combo = window.findChild(QComboBox, "voiceCombo")
        language_combo.setCurrentIndex(language_combo.findData("french"))
        assert voice_combo.currentData() == "estelle"
        window._voice_dialog.reject()

    QTimer.singleShot(0, select_french_voice)
    window.open_voice_manager()
    assert window.tts_controller.selected_voice_profile.display_name == (
        "Français · Estelle"
    )
    window.close()

    reopened = MainWindow(
        ModuleStore(tmp_path / "app-data"), make_settings(settings_path)
    )
    assert reopened.tts_controller.selected_voice_profile.language == "french"
    assert reopened.tts_controller.selected_voice_profile.voice == "estelle"
    reopened.close()


def test_comparison_aligns_verses_and_marks_missing_text(qapp, tmp_path):
    primary_path = create_test_module(tmp_path / "primary.SQLite3")
    comparison_path = create_test_module(tmp_path / "comparison.SQLite3")
    with sqlite3.connect(comparison_path) as connection:
        connection.execute(
            "UPDATE info SET value = 'Traducción secundaria' "
            "WHERE name = 'description'"
        )
        connection.execute(
            "DELETE FROM verses WHERE book_number = 1 AND chapter = 1 AND verse = 1"
        )
        connection.execute(
            "UPDATE verses SET text = 'Texto de la segunda traducción.' "
            "WHERE book_number = 1 AND chapter = 1 AND verse = 2"
        )
        connection.execute(
            "INSERT INTO verses VALUES (1, 1, 3, 'Versículo adicional.')"
        )
        connection.commit()

    store = ModuleStore(tmp_path / "app-data")
    primary_metadata = store.import_module(primary_path)
    comparison_metadata = store.import_module(comparison_path)
    settings_path = tmp_path / "settings.ini"
    window = MainWindow(store, make_settings(settings_path))
    window.refresh_modules(primary_metadata.sha256)

    comparison_index = window.compare_combo.findData(comparison_metadata.sha256)
    assert comparison_index >= 0
    window.compare_combo.setCurrentIndex(comparison_index)
    window.compare_action.setChecked(True)

    assert not window.compare_scroll.isHidden()
    assert set(window._verse_rows) == {1, 2, 3}
    assert set(window._comparison_rows) == {1, 2, 3}
    assert window._comparison_rows[1].findChild(
        QLabel, "verseMissing"
    ).text().startswith("Este versículo")
    assert window._verse_rows[3].findChild(
        QLabel, "verseMissing"
    ).text().startswith("Este versículo")
    assert window._comparison_rows[2].findChild(
        QLabel, "verseText"
    ).text() == "Texto de la segunda traducción."

    secondary_index = window.module_combo.findData(comparison_metadata.sha256)
    window.module_combo.setCurrentIndex(secondary_index)
    assert window.current_module.metadata.sha256 == comparison_metadata.sha256
    assert window.compare_combo.currentData() == primary_metadata.sha256
    assert window._comparison_module.metadata.sha256 == primary_metadata.sha256

    window.appearance_actions["dark"].trigger()
    window.close()

    reopened = MainWindow(store, make_settings(settings_path))
    assert reopened.compare_action.isChecked()
    assert not reopened.compare_scroll.isHidden()
    assert reopened.current_module.metadata.sha256 == comparison_metadata.sha256
    assert reopened.compare_combo.currentData() == primary_metadata.sha256
    assert reopened.verse_content.parchment_color.name() == "#292b2e"
    reopened.close()


def test_comparison_requires_another_installed_translation(qapp, tmp_path):
    source = create_test_module(tmp_path / "single.SQLite3")
    store = ModuleStore(tmp_path / "app-data")
    store.import_module(source)
    window = MainWindow(store, make_settings(tmp_path / "settings.ini"))

    assert not window.compare_action.isEnabled()
    assert not window.compare_action.isChecked()
    assert window.compare_scroll.isHidden()
    window.close()
