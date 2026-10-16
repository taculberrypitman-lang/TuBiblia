# Copyright © 2026 CunaWare.Lab
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import html
import re
from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QColor,
    QIcon,
    QKeySequence,
    QPainter,
    QPixmap,
)
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QStackedWidget,
    QProgressBar,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from tubiblia.module_store import (
    BibleModule,
    ModuleError,
    ModuleMetadata,
    ModuleStore,
    SearchResult,
)
from tubiblia.module_catalog_dialog import ModuleCatalogDialog
from tubiblia.assets import asset_path
from tubiblia.pocket_tts import (
    DEFAULT_VOICE_PROFILE,
    VOICE_PROFILES,
    VoiceProfile,
    voice_profile,
)
from tubiblia.reading_controller import PocketTTSController


_MYBIBLE_PARAGRAPH_BREAK = re.compile(r"<pb\s*/>", re.IGNORECASE)
_MYBIBLE_LINE_BREAK = re.compile(r"<(?:pb|br)\s*/?>", re.IGNORECASE)
_MYBIBLE_MARKUP = re.compile(r"</?[\w:-]+(?:\s+[^<>]*?)?\s*/?>", re.IGNORECASE)


def _display_verse_text(text: str) -> str:
    text = _MYBIBLE_PARAGRAPH_BREAK.sub("\n\n", text)
    text = _MYBIBLE_LINE_BREAK.sub("\n", text)
    text = _MYBIBLE_MARKUP.sub("", text)
    return html.unescape(text).strip()


class _ParchmentWidget(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.parchment_color = QColor("#ead9b5")

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), self.parchment_color)


class MainWindow(QMainWindow):
    def __init__(self, store: ModuleStore, settings: QSettings):
        super().__init__()
        self.store = store
        self.settings = settings
        self.modules: tuple[ModuleMetadata, ...] = ()
        self.current_module: BibleModule | None = None
        self._books = ()
        self._chapter_references: tuple[tuple[int, int], ...] = ()
        self._verse_rows: dict[int, QWidget] = {}
        self._comparison_rows: dict[int, QWidget] = {}
        self._comparison_module: BibleModule | None = None
        self._tts_chapter_navigation = False
        self._appearance = str(self.settings.value("appearance", "parchment"))
        if self._appearance not in {"parchment", "light", "dark"}:
            self._appearance = "parchment"

        self.setWindowTitle("TuBiblia")
        self.setWindowIcon(QIcon(str(asset_path("logo_tu_biblia.png"))))
        self.setMinimumSize(860, 560)
        self.resize(1180, 760)
        self._base_stylesheet = """
            QMainWindow { background: #f6f8fc; }
            QWidget#readerPage { background: #ead9b5; }
            QToolBar {
                background: #ffffff;
                border: none;
                border-bottom: 1px solid #dbe2ed;
                spacing: 8px;
                padding: 7px;
                color: #203451;
            }
            QToolButton, QComboBox, QLineEdit {
                color: #203451;
                background: #ffffff;
            }
            QToolBar QLabel { color: #40516a; }
            QToolButton { padding: 4px 7px; }
            QComboBox, QLineEdit {
                border: 1px solid #cbd5e1;
                border-radius: 5px;
                padding: 5px 7px;
            }
            QStatusBar { color: #40516a; background: #ffffff; }
            QListWidget#bookList {
                background: #ffffff;
                border: 1px solid #e0e6ef;
                border-radius: 8px;
                padding: 5px;
                font-size: 14px;
                color: #203451;
            }
            QListWidget#bookList::item { padding: 8px 7px; border-radius: 5px; }
            QListWidget#bookList::item:selected {
                background: #e7eefb;
                color: #183b6b;
            }
            QLabel#bookPanelTitle {
                color: #40516a;
                font-size: 13px;
                font-weight: 700;
                padding: 4px 2px;
            }
            QLabel#chapterTitle {
                color: #000000;
                font-size: 25px;
                font-weight: 700;
                padding: 12px 0 18px;
            }
            QLabel#verseNumber {
                color: #5c4023;
                font-size: 12px;
                font-weight: 700;
                min-width: 30px;
                padding-top: 3px;
            }
            QWidget#verseRow { border-radius: 5px; }
            QWidget#verseRow[selectedVerse="true"] { background: #fff1c7; }
            QLabel#verseText {
                color: #000000;
                font-size: 16px;
                padding: 2px 4px 10px;
            }
            QScrollArea { border: none; }
            """
        self.setStyleSheet(self._base_stylesheet)

        self._build_toolbar()
        self._build_pages()
        self._apply_appearance(self._appearance, persist=False)
        self.tts_controller = PocketTTSController(self)
        self.tts_controller.set_playback_rate(self.tts_speed_spin.value())
        self.tts_speed_spin.valueChanged.connect(self._on_playback_rate_changed)
        self.tts_controller.progress_changed.connect(self._on_tts_progress_changed)
        self._voice_preferences_reset = False
        try:
            selected_profile = voice_profile(
                str(self.settings.value("pocket_tts/language", "spanish")),
                str(self.settings.value("pocket_tts/voice", "lola")),
            )
        except ValueError:
            selected_profile = DEFAULT_VOICE_PROFILE
            self._voice_preferences_reset = True
            self.settings.setValue(
                "pocket_tts/language", selected_profile.language
            )
            self.settings.setValue("pocket_tts/voice", selected_profile.voice)
            self.settings.sync()
        self.tts_controller.select_voice(
            selected_profile.language, selected_profile.voice
        )
        self.tts_controller.state_changed.connect(self._on_tts_state_changed)
        self.tts_controller.error_occurred.connect(self._on_tts_error)
        self.tts_controller.chapter_advanced.connect(self._on_tts_chapter_advanced)
        self.tts_controller.voice_preparation_finished.connect(
            self._on_voice_preparation_finished
        )
        self._voice_dialog = None
        self._voice_status_label = None
        self._voice_prepare_button = None
        self._voice_language_combo = None
        self._voice_combo = None
        self.statusBar().showMessage("Importa un módulo bíblico para comenzar.")
        self.refresh_modules()
        if self._voice_preferences_reset:
            self.statusBar().showMessage(
                "La voz guardada ya no está disponible; se restableció "
                "Español · Lola.",
                8000,
            )

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("Lectura", self)
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        library_button = QToolButton(self)
        library_button.setText("Biblioteca")
        library_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        library_menu = QMenu(library_button)
        import_action = QAction("Importar módulo", self)
        import_action.setShortcut(QKeySequence.StandardKey.Open)
        import_action.triggered.connect(lambda: self.choose_module_file())
        library_menu.addAction(import_action)
        self.import_action = import_action
        catalog_action = QAction("Descargar módulos", self)
        catalog_action.setToolTip("Buscar módulos en el catálogo oficial de MyBible")
        catalog_action.triggered.connect(self.open_module_catalog)
        library_menu.addAction(catalog_action)
        self.catalog_action = catalog_action
        library_menu.addSeparator()
        appearance_menu = library_menu.addMenu("Apariencia")
        appearance_group = QActionGroup(appearance_menu)
        appearance_group.setExclusive(True)
        self.appearance_actions = {}
        for key, label in (
            ("parchment", "Pergamino"),
            ("light", "Claro"),
            ("dark", "Oscuro"),
        ):
            action = QAction(label, appearance_group)
            action.setCheckable(True)
            action.setChecked(key == self._appearance)
            action.triggered.connect(
                lambda checked=False, theme=key: self._apply_appearance(theme)
            )
            appearance_menu.addAction(action)
            self.appearance_actions[key] = action
        voice_menu = library_menu.addMenu("Voces de lectura")
        self.voice_manager_action = QAction("Idiomas y voces de lectura…", self)
        self.voice_manager_action.triggered.connect(self.open_voice_manager)
        voice_menu.addAction(self.voice_manager_action)
        self.library_menu = library_menu
        library_button.setMenu(library_menu)
        toolbar.addWidget(library_button)
        toolbar.addSeparator()

        toolbar.addWidget(QLabel("Traducción"))
        self.module_combo = QComboBox()
        self.module_combo.setMinimumWidth(180)
        self.module_combo.currentIndexChanged.connect(self._on_module_changed)
        toolbar.addWidget(self.module_combo)
        self.compare_action = QAction("Comparar", self)
        self.compare_action.setCheckable(True)
        self.compare_action.setToolTip(
            "Mostrar el pasaje en otra traducción instalada"
        )
        self.compare_action.toggled.connect(self._set_comparison_enabled)
        toolbar.addAction(self.compare_action)
        self.compare_translation_label = QLabel("Con")
        toolbar.addWidget(self.compare_translation_label)
        self.compare_combo = QComboBox()
        self.compare_combo.setMinimumWidth(150)
        self.compare_combo.currentIndexChanged.connect(
            self._on_comparison_module_changed
        )
        toolbar.addWidget(self.compare_combo)
        self.compare_translation_label.setVisible(False)
        self.compare_combo.setVisible(False)
        toolbar.addSeparator()

        self.previous_action = QAction("Anterior", self)
        self.previous_action.setText("|◀")
        self.previous_action.setToolTip("Capítulo anterior")
        self.previous_action.setShortcut(QKeySequence("Alt+Left"))
        self.previous_action.triggered.connect(lambda: self.move_chapter(-1))
        toolbar.addAction(self.previous_action)
        previous_button = toolbar.widgetForAction(self.previous_action)
        if isinstance(previous_button, QToolButton):
            previous_button.setAccessibleName("Capítulo anterior")

        toolbar.addWidget(QLabel("Capítulo"))
        self.chapter_combo = QComboBox()
        self.chapter_combo.setMinimumWidth(74)
        self.chapter_combo.currentIndexChanged.connect(self._on_chapter_changed)
        toolbar.addWidget(self.chapter_combo)

        self.next_action = QAction("Siguiente", self)
        self.next_action.setText("▶|")
        self.next_action.setToolTip("Capítulo siguiente")
        self.next_action.setShortcut(QKeySequence("Alt+Right"))
        self.next_action.triggered.connect(lambda: self.move_chapter(1))
        toolbar.addAction(self.next_action)
        next_button = toolbar.widgetForAction(self.next_action)
        if isinstance(next_button, QToolButton):
            next_button.setAccessibleName("Capítulo siguiente")
        toolbar.addSeparator()

        self.search_edit = self._make_search_edit()
        self.search_edit.returnPressed.connect(self.run_search)
        toolbar.addWidget(self.search_edit)
        self.search_action = QAction("Buscar", self)
        self.search_action.setShortcut(QKeySequence.StandardKey.Find)
        self.search_action.triggered.connect(lambda: self.run_search())
        toolbar.addAction(self.search_action)
        toolbar.addSeparator()

        self.addToolBarBreak(Qt.ToolBarArea.TopToolBarArea)
        voice_toolbar = QToolBar("Lectura en voz alta", self)
        voice_toolbar.setMovable(False)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, voice_toolbar)

        self.tts_play_pause_button = QToolButton(self)
        self.tts_play_pause_button.setObjectName("playPauseButton")
        self.tts_play_pause_button.setText("▶")
        self.tts_play_pause_button.setAccessibleName("Leer capítulo")
        self.tts_play_pause_button.setToolTip("Leer capítulo en voz alta")
        self.tts_play_pause_button.setMinimumSize(38, 32)
        self.tts_play_pause_button.clicked.connect(self._toggle_reading)
        voice_toolbar.addWidget(self.tts_play_pause_button)

        self.tts_stop_button = QToolButton(self)
        self.tts_stop_button.setObjectName("stopReadingButton")
        self.tts_stop_button.setText("■")
        self.tts_stop_button.setAccessibleName("Detener lectura")
        self.tts_stop_button.setToolTip("Detener lectura en voz alta")
        self.tts_stop_button.setMinimumSize(38, 32)
        self.tts_stop_button.clicked.connect(self.stop_reading)
        voice_toolbar.addWidget(self.tts_stop_button)
        voice_toolbar.addSeparator()

        self.voice_toolbar_button = QToolButton(self)
        self.voice_toolbar_button.setText("Voz…")
        self.voice_toolbar_button.setToolTip("Elegir idioma y voz")
        self.voice_toolbar_button.clicked.connect(self.open_voice_manager)
        voice_toolbar.addWidget(self.voice_toolbar_button)

        voice_toolbar.addWidget(QLabel("Velocidad"))
        self.tts_speed_spin = QDoubleSpinBox(self)
        self.tts_speed_spin.setObjectName("ttsPlaybackRate")
        self.tts_speed_spin.setRange(0.5, 2.0)
        self.tts_speed_spin.setSingleStep(0.1)
        self.tts_speed_spin.setDecimals(1)
        self.tts_speed_spin.setSuffix("×")
        self.tts_speed_spin.setValue(
            self.settings.value("pocket_tts/playback_rate", 1.0, type=float)
        )
        self.tts_speed_spin.setToolTip("Velocidad de reproducción, de 0.5× a 2.0×")
        self.tts_speed_spin.setMaximumWidth(90)
        voice_toolbar.addWidget(self.tts_speed_spin)
        voice_toolbar.addSeparator()

        self.tts_progress_label = QLabel("Detenida", self)
        self.tts_progress_label.setObjectName("ttsProgressLabel")
        voice_toolbar.addWidget(self.tts_progress_label)
        self.tts_progress_bar = QProgressBar(self)
        self.tts_progress_bar.setObjectName("ttsProgress")
        self.tts_progress_bar.setRange(0, 1)
        self.tts_progress_bar.setValue(0)
        self.tts_progress_bar.setFormat("%v / %m versículos")
        self.tts_progress_bar.setMaximumWidth(180)
        voice_toolbar.addWidget(self.tts_progress_bar)
        self._set_tts_controls_enabled(False)

    @staticmethod
    def _make_search_edit() -> QLineEdit:
        search_edit = QLineEdit()
        search_edit.setObjectName("searchEdit")
        search_edit.setPlaceholderText("Buscar palabra o frase…")
        search_edit.setClearButtonEnabled(True)
        search_edit.setMinimumWidth(190)
        return search_edit

    def _build_pages(self) -> None:
        self.pages = QStackedWidget()
        self.setCentralWidget(self.pages)

        self.empty_page = _ParchmentWidget()
        self.empty_page.setObjectName("emptyPage")
        empty_layout = QVBoxLayout(self.empty_page)
        empty_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.setContentsMargins(40, 40, 40, 40)
        self.logo_label = QLabel()
        self.logo_label.setObjectName("appLogo")
        self.logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.logo_label.setPixmap(
            QPixmap(str(asset_path("logo_tu_biblia.png"))).scaledToWidth(
                250, Qt.TransformationMode.SmoothTransformation
            )
        )
        title = QLabel("TuBiblia")
        title.setStyleSheet("font-size: 30px; font-weight: 700; color: #203451;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        explanation = QLabel(
            "Todavía no hay una Biblia instalada.\n\n"
            "Importa un módulo bíblico SQLite de MyBible (.SQLite3) que tengas "
            "derecho a utilizar, o busca módulos en el catálogo oficial de MyBible."
        )
        explanation.setWordWrap(True)
        explanation.setAlignment(Qt.AlignmentFlag.AlignCenter)
        explanation.setMaximumWidth(560)
        explanation.setStyleSheet("font-size: 15px; color: #52657e;")
        self.empty_import_button = QPushButton("Importar módulo bíblico")
        self.empty_import_button.setMinimumHeight(42)
        self.empty_import_button.clicked.connect(self.choose_module_file)
        self.empty_catalog_button = QPushButton("Buscar módulos para descargar")
        self.empty_catalog_button.setMinimumHeight(42)
        self.empty_catalog_button.clicked.connect(self.open_module_catalog)
        empty_layout.addWidget(self.logo_label)
        empty_layout.addSpacing(6)
        empty_layout.addWidget(title)
        empty_layout.addSpacing(12)
        empty_layout.addWidget(explanation)
        empty_layout.addSpacing(20)
        empty_layout.addWidget(
            self.empty_import_button, alignment=Qt.AlignmentFlag.AlignHCenter
        )
        empty_layout.addSpacing(8)
        empty_layout.addWidget(
            self.empty_catalog_button, alignment=Qt.AlignmentFlag.AlignHCenter
        )
        self.pages.addWidget(self.empty_page)

        self.reader_page = _ParchmentWidget()
        self.reader_page.setObjectName("readerPage")
        reader_layout = QHBoxLayout(self.reader_page)
        reader_layout.setContentsMargins(16, 14, 16, 16)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        sidebar = QWidget()
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(0, 0, 10, 0)
        sidebar_layout.addWidget(QLabel("LIBROS", objectName="bookPanelTitle"))
        self.book_list = QListWidget()
        self.book_list.setObjectName("bookList")
        self.book_list.currentRowChanged.connect(self._on_book_changed)
        sidebar_layout.addWidget(self.book_list)
        splitter.addWidget(sidebar)

        self.verse_scroll = QScrollArea()
        self.verse_scroll.setObjectName("verseScroll")
        self.verse_scroll.setWidgetResizable(True)
        self.verse_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.verse_scroll.setStyleSheet(
            "QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; }"
        )
        self.verse_scroll.viewport().setAutoFillBackground(False)
        self.verse_content = _ParchmentWidget()
        self.verse_content.setObjectName("verseContent")
        self.verses_layout = QVBoxLayout(self.verse_content)
        self.verses_layout.setContentsMargins(24, 12, 24, 24)
        self.verses_layout.setSpacing(4)
        self.verse_scroll.setWidget(self.verse_content)
        self.compare_scroll = QScrollArea()
        self.compare_scroll.setObjectName("comparisonScroll")
        self.compare_scroll.setWidgetResizable(True)
        self.compare_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.compare_scroll.setStyleSheet(
            "QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; }"
        )
        self.compare_scroll.viewport().setAutoFillBackground(False)
        self.compare_content = _ParchmentWidget()
        self.compare_content.setObjectName("comparisonContent")
        self.comparison_layout = QVBoxLayout(self.compare_content)
        self.comparison_layout.setContentsMargins(24, 12, 24, 24)
        self.comparison_layout.setSpacing(4)
        self.compare_scroll.setWidget(self.compare_content)
        self.compare_scroll.hide()

        self.reading_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.reading_splitter.setChildrenCollapsible(False)
        self.reading_splitter.addWidget(self.verse_scroll)
        self.reading_splitter.addWidget(self.compare_scroll)
        self.reading_splitter.setStretchFactor(0, 1)
        self.reading_splitter.setStretchFactor(1, 1)
        splitter.addWidget(self.reading_splitter)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([250, 850])
        self.verse_scroll.verticalScrollBar().valueChanged.connect(
            self.compare_scroll.verticalScrollBar().setValue
        )
        self.compare_scroll.verticalScrollBar().valueChanged.connect(
            self.verse_scroll.verticalScrollBar().setValue
        )

        reader_layout.addWidget(splitter)
        self.pages.addWidget(self.reader_page)

    def _apply_appearance(self, appearance: str, *, persist: bool = True) -> None:
        palettes = {
            "parchment": ("#ead9b5", "#000000", "#5c4023", "#fff1c7"),
            "light": ("#faf9f5", "#171717", "#594b36", "#efe5ce"),
            "dark": ("#292b2e", "#eeeeee", "#d9c39b", "#45413a"),
        }
        if appearance not in palettes:
            raise ValueError(f"Apariencia desconocida: {appearance}")
        background, text_color, number_color, selected_color = palettes[appearance]
        self._appearance = appearance
        stylesheet = self._base_stylesheet
        for original, replacement in (
            ("#ead9b5", background),
            ("#000000", text_color),
            ("#5c4023", number_color),
            ("#fff1c7", selected_color),
        ):
            stylesheet = stylesheet.replace(original, replacement)
        stylesheet += (
            "\nQLabel#verseMissing { color: "
            + number_color
            + "; font-style: italic; }\n"
        )
        self.setStyleSheet(stylesheet)
        for widget in self.findChildren(_ParchmentWidget):
            widget.parchment_color = QColor(background)
            widget.update()
        if persist:
            self.settings.setValue("appearance", appearance)
            self.settings.sync()

    def open_voice_manager(self) -> None:
        if self._voice_dialog is None:
            dialog = QDialog(self)
            dialog.setWindowTitle("Voces de lectura")
            dialog.setMinimumWidth(430)
            layout = QVBoxLayout(dialog)
            description = QLabel(
                "Pocket TTS está integrado en TuBiblia. Elige un idioma y una "
                "voz predefinida disponible. Al prepararla se descargan o "
                "recuperan de la caché local de Kyutai el modelo y los recursos "
                "de esa voz. La primera preparación requiere Internet; después "
                "puede generarse audio sin conexión. Las licencias varían por "
                "voz: consulta sus condiciones antes de cualquier redistribución."
            )
            description.setWordWrap(True)
            layout.addWidget(description)
            layout.addWidget(QLabel("Idioma"))
            self._voice_language_combo = QComboBox(dialog)
            self._voice_language_combo.setObjectName("voiceLanguageCombo")
            languages = tuple(dict.fromkeys(p.language for p in VOICE_PROFILES))
            for language in languages:
                profile = next(p for p in VOICE_PROFILES if p.language == language)
                self._voice_language_combo.addItem(
                    profile.language_name, profile.language
                )
            language_index = self._voice_language_combo.findData(
                self.tts_controller.selected_voice_profile.language
            )
            self._voice_language_combo.setCurrentIndex(language_index)
            layout.addWidget(self._voice_language_combo)
            layout.addWidget(QLabel("Voz disponible para este idioma"))
            self._voice_combo = QComboBox(dialog)
            self._voice_combo.setObjectName("voiceCombo")
            self._populate_voice_choices(
                self.tts_controller.selected_voice_profile
            )
            layout.addWidget(self._voice_combo)
            self._voice_status_label = QLabel()
            self._voice_status_label.setWordWrap(True)
            layout.addWidget(self._voice_status_label)
            self._voice_prepare_button = QPushButton("Descargar / preparar voz")
            self._voice_prepare_button.clicked.connect(
                self._start_voice_preparation
            )
            layout.addWidget(self._voice_prepare_button)
            self._voice_language_combo.currentIndexChanged.connect(
                self._on_voice_language_changed
            )
            self._voice_combo.currentIndexChanged.connect(
                self._on_voice_changed
            )
            buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
            buttons.rejected.connect(dialog.reject)
            layout.addWidget(buttons)
            self._voice_dialog = dialog
        self._update_voice_dialog()
        self._voice_dialog.exec()

    def _populate_voice_choices(self, selected: VoiceProfile) -> None:
        if self._voice_combo is None:
            return
        was_blocked = self._voice_combo.blockSignals(True)
        self._voice_combo.clear()
        for profile in VOICE_PROFILES:
            if profile.language == selected.language:
                self._voice_combo.addItem(profile.voice_name, profile.voice)
        index = self._voice_combo.findData(selected.voice)
        self._voice_combo.setCurrentIndex(index)
        self._voice_combo.blockSignals(was_blocked)

    def _on_voice_language_changed(self, _index: int) -> None:
        if self._voice_language_combo is None:
            return
        language = str(self._voice_language_combo.currentData())
        profile = next(p for p in VOICE_PROFILES if p.language == language)
        self._populate_voice_choices(profile)
        self._apply_voice_selection()

    def _on_voice_changed(self, _index: int) -> None:
        self._apply_voice_selection()

    def _apply_voice_selection(self) -> None:
        if self._voice_language_combo is None or self._voice_combo is None:
            return
        language = str(self._voice_language_combo.currentData())
        voice = str(self._voice_combo.currentData())
        profile = voice_profile(language, voice)
        if not self.tts_controller.select_voice(language, voice):
            return
        self.settings.setValue("pocket_tts/language", language)
        self.settings.setValue("pocket_tts/voice", voice)
        self.settings.sync()
        self.statusBar().showMessage(
            f"Voz seleccionada: {profile.display_name}. Prepárala desde "
            "Biblioteca → Voces de lectura."
        )
        self._update_voice_dialog()

    def _start_voice_preparation(self) -> None:
        if self._voice_prepare_button is None or self._voice_status_label is None:
            return
        profile = self.tts_controller.selected_voice_profile
        self._voice_prepare_button.setEnabled(False)
        self._voice_status_label.setText(
            f"Preparando el modelo {profile.language_name} y la voz "
            f"{profile.voice_name}. La primera descarga puede tardar; "
            "no cierres TuBiblia."
        )
        if not self.tts_controller.prepare_voice():
            return
        self._update_voice_dialog()

    def _on_voice_preparation_finished(self, success: bool, message: str) -> None:
        if self._voice_status_label is not None:
            self._voice_status_label.setText(message)
        if self._voice_prepare_button is not None:
            self._voice_prepare_button.setEnabled(True)
        self.statusBar().showMessage(
            (
                f"Voz {self.tts_controller.selected_voice_profile.display_name} "
                "preparada."
                if success
                else message
            ),
            5000 if success else 10000,
        )

    def _update_voice_dialog(self) -> None:
        if self._voice_status_label is None or self._voice_prepare_button is None:
            return
        profile = self.tts_controller.selected_voice_profile
        if self.tts_controller.voice_ready:
            self._voice_status_label.setText(
                f"{profile.display_name} está preparada en esta sesión. "
                "Los archivos permanecen en la caché local de Pocket TTS."
            )
        elif self.tts_controller.state == "preparing_voice":
            self._voice_status_label.setText(
                f"Preparando {profile.display_name}…"
            )
        else:
            self._voice_status_label.setText(
                f"{profile.display_name} aún no está preparada en esta sesión. "
                "Pulsa «Descargar / preparar voz» para cargarla."
            )
        idle = self.tts_controller.state == "stopped"
        self._voice_prepare_button.setEnabled(idle)
        if self._voice_language_combo is not None:
            self._voice_language_combo.setEnabled(idle)
        if self._voice_combo is not None:
            self._voice_combo.setEnabled(idle)

    def refresh_modules(self, preferred_sha256: str | None = None) -> None:
        modules, errors = self.store.scan_modules()
        self.modules = modules
        previous_signals = self.module_combo.blockSignals(True)
        self.module_combo.clear()
        for module in modules:
            language = f" ({module.language})" if module.language else ""
            self.module_combo.addItem(f"{module.name}{language}", module.sha256)
        selected_sha256 = preferred_sha256 or str(
            self.settings.value("last_module_sha256", "")
        )
        selected_index = next(
            (
                index
                for index, module in enumerate(modules)
                if module.sha256 == selected_sha256
            ),
            0,
        )
        if modules:
            self.module_combo.setCurrentIndex(selected_index)
        self.module_combo.blockSignals(previous_signals)

        selected_primary = modules[selected_index].sha256 if modules else None
        comparison_modules = self._populate_comparison_modules(selected_primary)
        was_comparison_enabled = self.settings.value(
            "comparison_enabled", False, type=bool
        )
        self.compare_action.setChecked(
            was_comparison_enabled and bool(comparison_modules)
        )

        if errors:
            QMessageBox.warning(
                self,
                "Módulos no válidos",
                "Se encontraron archivos que no se pudieron abrir como módulos "
                "bíblicos:\n\n" + "\n".join(errors),
            )

        if modules:
            self._activate_module(selected_index)
        else:
            self.current_module = None
            self._chapter_references = ()
            self.pages.setCurrentWidget(self.empty_page)
            self._set_reading_controls_enabled(False)
            self._set_tts_controls_enabled(False)

    def _populate_comparison_modules(
        self, primary_sha256: str | None
    ) -> tuple[ModuleMetadata, ...]:
        selected_sha256 = self.compare_combo.currentData()
        if selected_sha256 == primary_sha256 or selected_sha256 is None:
            selected_sha256 = str(
                self.settings.value("comparison_module_sha256", "")
            )
        comparison_modules = tuple(
            module
            for module in self.modules
            if module.sha256 != primary_sha256
        )
        previous_signals = self.compare_combo.blockSignals(True)
        self.compare_combo.clear()
        for module in comparison_modules:
            language = f" ({module.language})" if module.language else ""
            self.compare_combo.addItem(
                f"{module.name}{language}", module.sha256
            )
        comparison_index = next(
            (
                index
                for index, module in enumerate(comparison_modules)
                if module.sha256 == selected_sha256
            ),
            0,
        )
        if comparison_modules:
            self.compare_combo.setCurrentIndex(comparison_index)
        self.compare_combo.blockSignals(previous_signals)
        self.compare_action.setEnabled(bool(comparison_modules))
        return comparison_modules

    def _activate_module(self, index: int) -> None:
        if not 0 <= index < len(self.modules):
            return
        metadata = self.modules[index]
        try:
            module = BibleModule(metadata.path)
            books = module.books()
            chapter_references = module.chapter_references()
        except ModuleError as exc:
            QMessageBox.critical(self, "No se pudo abrir el módulo", str(exc))
            return

        self.current_module = module
        self._books = books
        self._chapter_references = chapter_references
        self._comparison_module = None
        self._populate_comparison_modules(metadata.sha256)
        self._on_comparison_module_changed(self.compare_combo.currentIndex())
        previous_signals = self.book_list.blockSignals(True)
        self.book_list.clear()
        for book in books:
            item = QListWidgetItem(book.long_name or book.short_name)
            item.setData(Qt.ItemDataRole.UserRole, book.number)
            self.book_list.addItem(item)
        self.book_list.blockSignals(previous_signals)
        self.pages.setCurrentWidget(self.reader_page)
        self._set_reading_controls_enabled(True)
        self._set_tts_controls_enabled(True)

        saved_book = self.settings.value(
            f"reading/{metadata.sha256}/book", 0, type=int
        )
        saved_chapter = self.settings.value(
            f"reading/{metadata.sha256}/chapter", 1, type=int
        )
        saved_verse = self.settings.value(
            f"reading/{metadata.sha256}/verse", 1, type=int
        )
        available_references = set(chapter_references)
        if (saved_book, saved_chapter) not in available_references:
            saved_book, saved_chapter = chapter_references[0]
        self.navigate_to(saved_book, saved_chapter, saved_verse)

    def _set_reading_controls_enabled(self, enabled: bool) -> None:
        self.module_combo.setEnabled(enabled)
        self.chapter_combo.setEnabled(enabled)
        self.search_edit.setEnabled(enabled)
        self.search_action.setEnabled(enabled)
        self.previous_action.setEnabled(enabled)
        self.next_action.setEnabled(enabled)
        self.book_list.setEnabled(enabled)

    def _set_tts_controls_enabled(self, enabled: bool) -> None:
        self.tts_play_pause_button.setEnabled(enabled)
        self.tts_stop_button.setEnabled(False)
        self.voice_toolbar_button.setEnabled(True)
        self.tts_speed_spin.setEnabled(True)

    def choose_module_file(self) -> None:
        source, _ = QFileDialog.getOpenFileName(
            self,
            "Importar módulo bíblico de MyBible",
            str(Path.home()),
            "Módulos bíblicos SQLite (*.SQLite3 *.sqlite3);;Todos los archivos (*)",
        )
        if not source:
            return
        try:
            metadata = self.store.import_module(Path(source))
        except (ModuleError, OSError) as exc:
            QMessageBox.critical(self, "No se pudo importar el módulo", str(exc))
            return
        self.refresh_modules(metadata.sha256)
        self.statusBar().showMessage(f"Módulo importado: {metadata.name}", 5000)

    def open_module_catalog(self) -> None:
        dialog = ModuleCatalogDialog(self.store, self)
        dialog.module_installed.connect(self._on_catalog_module_installed)
        dialog.exec()

    def _on_catalog_module_installed(self, metadata: ModuleMetadata) -> None:
        self.refresh_modules(metadata.sha256)
        self.statusBar().showMessage(f"Módulo instalado: {metadata.name}", 5000)

    def _on_module_changed(self, index: int) -> None:
        if not 0 <= index < len(self.modules):
            return
        self._activate_module(index)

    def _on_comparison_module_changed(self, index: int) -> None:
        self._comparison_module = None
        if not 0 <= index < self.compare_combo.count():
            return
        sha256 = self.compare_combo.itemData(index)
        if self.current_module is not None and sha256 == self.current_module.metadata.sha256:
            return
        metadata = next(
            (module for module in self.modules if module.sha256 == sha256),
            None,
        )
        if metadata is None:
            return
        try:
            self._comparison_module = BibleModule(metadata.path)
        except ModuleError as exc:
            QMessageBox.critical(self, "No se pudo abrir la traducción", str(exc))
            return
        self.settings.setValue("comparison_module_sha256", metadata.sha256)
        if self.compare_action.isChecked():
            self._rerender_current_chapter()

    def _set_comparison_enabled(self, enabled: bool) -> None:
        enabled = enabled and self.compare_combo.count() > 0
        self.compare_translation_label.setVisible(enabled)
        self.compare_combo.setVisible(enabled)
        self.compare_scroll.setVisible(enabled)
        self.settings.setValue("comparison_enabled", enabled)
        self.settings.sync()
        if enabled and self._comparison_module is None:
            self._on_comparison_module_changed(self.compare_combo.currentIndex())
        elif not enabled:
            self._clear_layout(self.comparison_layout)
            self._comparison_rows.clear()
        if enabled:
            self._rerender_current_chapter()

    def _rerender_current_chapter(self) -> None:
        if self.current_module is None or not self.compare_action.isChecked():
            return
        item = self.book_list.currentItem()
        chapter = self.chapter_combo.currentData()
        if item is None or chapter is None:
            return
        book_number = int(item.data(Qt.ItemDataRole.UserRole))
        book = next(
            (book for book in self._books if book.number == book_number), None
        )
        if book is None:
            return
        selected_verse = next(
            (
                number
                for number, row in self._verse_rows.items()
                if row.property("selectedVerse")
            ),
            1,
        )
        self._render_comparison(book, int(chapter), selected_verse)

    @staticmethod
    def _clear_layout(layout: QVBoxLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _on_book_changed(self, row: int) -> None:
        if self.current_module is None or row < 0:
            return
        item = self.book_list.item(row)
        if item is None:
            return
        book_number = int(item.data(Qt.ItemDataRole.UserRole))
        chapters = self.current_module.chapters(book_number)
        if chapters:
            self.navigate_to(book_number, chapters[0])

    def _on_chapter_changed(self, index: int) -> None:
        if self.current_module is None or index < 0:
            return
        item = self.book_list.currentItem()
        if item is None:
            return
        chapter = self.chapter_combo.itemData(index)
        if chapter is not None:
            self.navigate_to(int(item.data(Qt.ItemDataRole.UserRole)), int(chapter))

    def navigate_to(
        self, book_number: int, chapter: int, verse_number: int = 1
    ) -> None:
        if self.current_module is None:
            raise ModuleError("Importa un módulo bíblico antes de navegar.")
        if (
            not self._tts_chapter_navigation
            and hasattr(self, "tts_controller")
            and self.tts_controller.is_active
        ):
            self.tts_controller.stop()
        book = next((book for book in self._books if book.number == book_number), None)
        if book is None or chapter not in self.current_module.chapters(book_number):
            raise ValueError("La referencia no existe en el módulo instalado.")

        previous_signals = self.book_list.blockSignals(True)
        for row in range(self.book_list.count()):
            item = self.book_list.item(row)
            if int(item.data(Qt.ItemDataRole.UserRole)) == book_number:
                self.book_list.setCurrentRow(row)
                break
        self.book_list.blockSignals(previous_signals)

        previous_signals = self.chapter_combo.blockSignals(True)
        self.chapter_combo.clear()
        chapters = self.current_module.chapters(book_number)
        for chapter_number in chapters:
            self.chapter_combo.addItem(str(chapter_number), chapter_number)
        self.chapter_combo.setCurrentIndex(chapters.index(chapter))
        self.chapter_combo.blockSignals(previous_signals)

        self._render_chapter(book, chapter, verse_number)
        self.settings.setValue("last_module_sha256", self.current_module.metadata.sha256)
        self.settings.setValue(
            f"reading/{self.current_module.metadata.sha256}/book", book_number
        )
        self.settings.setValue(
            f"reading/{self.current_module.metadata.sha256}/chapter", chapter
        )
        self.settings.setValue(
            f"reading/{self.current_module.metadata.sha256}/verse", verse_number
        )
        self.settings.sync()

    def _render_chapter(self, book, chapter: int, selected_verse: int) -> None:
        while self.verses_layout.count():
            item = self.verses_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._verse_rows.clear()

        heading = QLabel(f"{book.long_name or book.short_name} {chapter}")
        heading.setObjectName("chapterTitle")
        self.verses_layout.addWidget(heading)

        try:
            verses = self.current_module.verses(book.number, chapter)
        except ModuleError as exc:
            QMessageBox.critical(self, "Error de lectura", str(exc))
            return
        for verse in verses:
            row = QWidget()
            row.setObjectName("verseRow")
            row.setProperty("selectedVerse", verse.verse == selected_verse)
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(8, 7, 8, 1)
            number = QLabel(str(verse.verse))
            number.setObjectName("verseNumber")
            number.setAlignment(
                Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight
            )
            text = QLabel(_display_verse_text(verse.text))
            text.setObjectName("verseText")
            text.setTextFormat(Qt.TextFormat.PlainText)
            text.setWordWrap(True)
            text.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
            )
            row_layout.addWidget(number)
            row_layout.addWidget(text, 1)
            self.verses_layout.addWidget(row)
            self._verse_rows[verse.verse] = row
        self.verses_layout.addStretch(1)
        if self.compare_action.isChecked():
            self._render_comparison(book, chapter, selected_verse)
        verse_label = "versículo" if len(verses) == 1 else "versículos"
        self.statusBar().showMessage(
            f"{book.long_name or book.short_name} {chapter} · "
            f"{len(verses)} {verse_label}"
        )
        selected = self._verse_rows.get(selected_verse)
        if selected is not None:
            self.verse_scroll.ensureWidgetVisible(selected, 0, 24)

    def _render_comparison(self, book, chapter: int, selected_verse: int) -> None:
        if self.current_module is None or self._comparison_module is None:
            return
        try:
            primary_verses = self.current_module.verses(book.number, chapter)
            comparison_verses = self._comparison_module.verses(
                book.number, chapter
            )
        except ModuleError as exc:
            QMessageBox.critical(self, "Error al comparar traducciones", str(exc))
            return

        primary_text = {
            verse.verse: _display_verse_text(verse.text)
            for verse in primary_verses
        }
        comparison_text = {
            verse.verse: _display_verse_text(verse.text)
            for verse in comparison_verses
        }
        references = sorted(set(primary_text) | set(comparison_text))
        self._clear_layout(self.verses_layout)
        self._clear_layout(self.comparison_layout)
        self._verse_rows.clear()
        self._comparison_rows.clear()

        reference = f"{book.long_name or book.short_name} {chapter}"
        for layout, title in (
            (
                self.verses_layout,
                f"{reference} · {self.current_module.metadata.name}",
            ),
            (
                self.comparison_layout,
                f"{reference} · {self._comparison_module.metadata.name}",
            ),
        ):
            heading = QLabel(title)
            heading.setObjectName("chapterTitle")
            heading.setWordWrap(True)
            layout.addWidget(heading)

        for verse_number in references:
            left_row = self._make_verse_row(
                verse_number,
                primary_text.get(
                    verse_number, "Este versículo no está disponible en esta traducción."
                ),
                verse_number == selected_verse,
                missing=verse_number not in primary_text,
            )
            right_row = self._make_verse_row(
                verse_number,
                comparison_text.get(
                    verse_number, "Este versículo no está disponible en esta traducción."
                ),
                verse_number == selected_verse,
                missing=verse_number not in comparison_text,
            )
            self.verses_layout.addWidget(left_row)
            self.comparison_layout.addWidget(right_row)
            self._verse_rows[verse_number] = left_row
            self._comparison_rows[verse_number] = right_row
        if not references:
            no_text = "No hay versículos para este libro y capítulo en esta traducción."
            self.verses_layout.addWidget(QLabel(no_text))
            self.comparison_layout.addWidget(QLabel(no_text))
        self.verses_layout.addStretch(1)
        self.comparison_layout.addStretch(1)
        primary_row = self._verse_rows.get(selected_verse)
        comparison_row = self._comparison_rows.get(selected_verse)
        if primary_row is not None:
            self.verse_scroll.ensureWidgetVisible(primary_row, 0, 24)
        if comparison_row is not None:
            self.compare_scroll.ensureWidgetVisible(comparison_row, 0, 24)

    @staticmethod
    def _make_verse_row(
        verse_number: int,
        verse_text: str,
        selected: bool,
        *,
        missing: bool = False,
    ) -> QWidget:
        row = QWidget()
        row.setObjectName("verseRow")
        row.setProperty("selectedVerse", selected)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(8, 7, 8, 1)
        number = QLabel(str(verse_number))
        number.setObjectName("verseNumber")
        number.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight)
        text = QLabel(verse_text)
        text.setObjectName("verseMissing" if missing else "verseText")
        text.setTextFormat(Qt.TextFormat.PlainText)
        text.setWordWrap(True)
        text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        row_layout.addWidget(number)
        row_layout.addWidget(text, 1)
        return row

    def read_chapter_aloud(self) -> None:
        if self.current_module is None:
            return
        item = self.book_list.currentItem()
        chapter = self.chapter_combo.currentData()
        if item is None or chapter is None:
            return
        book_number = int(item.data(Qt.ItemDataRole.UserRole))
        chapter_number = int(chapter)
        try:
            verses = self.current_module.verses(book_number, chapter_number)
        except ModuleError as exc:
            QMessageBox.critical(self, "Error de lectura", str(exc))
            return
        spoken_segments = tuple(
            f"{verse.verse}. {_display_verse_text(verse.text)}"
            for verse in verses
            if _display_verse_text(verse.text)
        )
        if not spoken_segments:
            self._on_tts_error("El capítulo no contiene texto para leer.")
            return

        try:
            current_index = self._chapter_references.index(
                (book_number, chapter_number)
            )
        except ValueError:
            next_reference = None
        else:
            next_index = current_index + 1
            next_reference = (
                self._chapter_references[next_index]
                if next_index < len(self._chapter_references)
                else None
            )
        self.tts_controller.read_chapter(spoken_segments, next_reference)

    def pause_reading(self) -> None:
        self.tts_controller.pause()

    def resume_reading(self) -> None:
        self.tts_controller.resume()

    def stop_reading(self) -> None:
        self.tts_controller.stop()

    def _toggle_reading(self) -> None:
        state = self.tts_controller.state
        if state == "paused":
            self.resume_reading()
        elif state in {"generating", "playing"}:
            self.pause_reading()
        elif state == "stopped":
            self.read_chapter_aloud()

    def _on_tts_state_changed(self, state: str) -> None:
        active = state in {
            "generating",
            "playing",
            "paused",
            "advancing",
            "preparing_voice",
        }
        can_toggle = state in {"stopped", "generating", "playing", "paused"}
        self.tts_play_pause_button.setEnabled(
            self.current_module is not None and can_toggle
        )
        self.tts_stop_button.setEnabled(active)
        if state in {"generating", "playing"}:
            self.tts_play_pause_button.setText("Ⅱ")
            self.tts_play_pause_button.setAccessibleName("Pausar lectura")
            self.tts_play_pause_button.setToolTip("Pausar lectura")
        elif state == "paused":
            self.tts_play_pause_button.setText("▶")
            self.tts_play_pause_button.setAccessibleName("Reanudar lectura")
            self.tts_play_pause_button.setToolTip("Reanudar lectura")
        else:
            self.tts_play_pause_button.setText("▶")
            self.tts_play_pause_button.setAccessibleName("Leer capítulo")
            self.tts_play_pause_button.setToolTip("Leer capítulo en voz alta")
        labels = {
            "generating": "Generando el siguiente segmento…",
            "playing": "Reproduciendo",
            "paused": "Pausada",
            "advancing": "Preparando el siguiente capítulo…",
            "preparing_voice": "Preparando el modelo y la voz de Pocket TTS…",
            "stopped": "Detenida",
        }
        message = labels.get(state, "")
        self.tts_progress_label.setText(message)
        if state == "stopped":
            self.tts_progress_bar.setRange(0, 1)
            self.tts_progress_bar.setValue(0)
        if message and state != "stopped":
            self.statusBar().showMessage(message)
        self._update_voice_dialog()

    def _on_tts_progress_changed(self, current: int, total: int) -> None:
        self.tts_progress_bar.setRange(0, max(total, 1))
        self.tts_progress_bar.setValue(current)

    def _on_playback_rate_changed(self, rate: float) -> None:
        self.tts_controller.set_playback_rate(rate)
        self.settings.setValue("pocket_tts/playback_rate", rate)

    def _on_tts_error(self, message: str) -> None:
        self.statusBar().showMessage("No se pudo generar o reproducir el audio.")
        QMessageBox.warning(self, "Pocket TTS", message)

    def _on_tts_chapter_advanced(self, book_number: int, chapter: int) -> None:
        if self.current_module is None:
            return
        book = next((book for book in self._books if book.number == book_number), None)
        if book is None:
            self.tts_controller.stop()
            return
        self._tts_chapter_navigation = True
        try:
            self.navigate_to(book_number, chapter)
            self.read_chapter_aloud()
        finally:
            self._tts_chapter_navigation = False

    def move_chapter(self, offset: int) -> None:
        if self.current_module is None or offset not in (-1, 1):
            return
        item = self.book_list.currentItem()
        chapter = self.chapter_combo.currentData()
        if item is None or chapter is None:
            return
        current = (
            int(item.data(Qt.ItemDataRole.UserRole)),
            int(chapter),
        )
        try:
            index = self._chapter_references.index(current)
        except ValueError:
            return
        target_index = index + offset
        if 0 <= target_index < len(self._chapter_references):
            book_number, chapter_number = self._chapter_references[target_index]
            self.navigate_to(book_number, chapter_number)

    def search_text(self, query: str) -> tuple[SearchResult, ...]:
        if self.current_module is None:
            return ()
        return self.current_module.search(query)

    def run_search(self) -> None:
        query = self.search_edit.text().strip()
        if not query or self.current_module is None:
            return
        try:
            results = self.search_text(query)
        except ModuleError as exc:
            QMessageBox.critical(self, "Error de búsqueda", str(exc))
            return
        if not results:
            QMessageBox.information(
                self,
                "Sin resultados",
                f"No se encontraron resultados para «{query}».",
            )
            return

        dialog = QDialog(self)
        dialog.setWindowTitle(f"Resultados de búsqueda · {len(results)}")
        dialog.resize(720, 500)
        layout = QVBoxLayout(dialog)
        layout.addWidget(
            QLabel(f"Resultados para «{query}» (máximo 200 resultados)")
        )
        result_list = QListWidget()
        for result in results:
            item = QListWidgetItem(
                f"{result.book_name} {result.chapter}:{result.verse}  —  "
                f"{_display_verse_text(result.text)}"
            )
            item.setData(
                Qt.ItemDataRole.UserRole,
                (result.book_number, result.chapter, result.verse),
            )
            result_list.addItem(item)
        layout.addWidget(result_list)
        buttons = QDialogButtonBox()
        open_button = buttons.addButton(
            "Abrir referencia", QDialogButtonBox.ButtonRole.AcceptRole
        )
        open_button.setObjectName("openReferenceButton")
        close_button = buttons.addButton(QDialogButtonBox.StandardButton.Close)
        open_button.setEnabled(result_list.count() > 0)

        def open_selected() -> None:
            item = result_list.currentItem()
            if item is None:
                return
            book_number, chapter, verse = item.data(Qt.ItemDataRole.UserRole)
            self.navigate_to(int(book_number), int(chapter), int(verse))
            dialog.accept()

        open_button.clicked.connect(open_selected)
        close_button.clicked.connect(dialog.reject)
        result_list.itemActivated.connect(lambda _item: open_selected())
        layout.addWidget(buttons)
        dialog.exec()

    def closeEvent(self, event) -> None:
        self.tts_controller.stop()
        self.settings.sync()
        super().closeEvent(event)
