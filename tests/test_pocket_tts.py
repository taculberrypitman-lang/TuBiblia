# Copyright © 2026 CunaWare.Lab
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import threading
import time
import sys
from types import ModuleType
from pathlib import Path

import pytest
from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtMultimedia import QMediaPlayer

from tubiblia.pocket_tts import (
    DEFAULT_VOICE_PROFILE,
    PocketTTSGenerator,
    VOICE_PROFILES,
)
from tubiblia.reading_controller import PocketTTSController


class FakeGenerator:
    def __init__(
        self,
        *,
        block_first: bool = False,
        block_text: str | None = None,
        failure: str | None = None,
    ):
        self.calls: list[str] = []
        self.paths: list[Path] = []
        self.thread_ids: list[int] = []
        self.first_started = threading.Event()
        self.release_first = threading.Event()
        self.block_first = block_first
        self.block_text = block_text
        self.failure = failure
        self.preparation_thread_ids: list[int] = []
        self.language = "spanish"
        self.voice = "lola"

    @property
    def voice_ready(self):
        return bool(self.preparation_thread_ids)

    def prepare_voice(self):
        self.preparation_thread_ids.append(threading.get_ident())
        if self.failure is not None:
            raise RuntimeError(self.failure)

    def configure_voice(self, language, voice):
        self.language = language
        self.voice = voice

    def generate_wav(self, text, output_path, cancelled):
        self.calls.append(text)
        self.paths.append(output_path)
        self.thread_ids.append(threading.get_ident())
        if (self.block_first and text == "first") or text == self.block_text:
            self.first_started.set()
            self.release_first.wait(timeout=3)
        if self.failure is not None:
            raise RuntimeError(self.failure)
        output_path.write_bytes(text.encode())
        return output_path


class FakePlayer(QObject):
    mediaStatusChanged = Signal(QMediaPlayer.MediaStatus)
    errorOccurred = Signal(QMediaPlayer.Error, str)

    def __init__(self):
        super().__init__()
        self.source: QUrl | None = None
        self.play_count = 0
        self.pause_count = 0
        self.stop_count = 0
        self.playback_rates: list[float] = []

    def setSource(self, source: QUrl):
        self.source = source

    def play(self):
        self.play_count += 1

    def pause(self):
        self.pause_count += 1

    def stop(self):
        self.stop_count += 1

    def setPlaybackRate(self, rate: float):
        self.playback_rates.append(rate)


def make_controller(tmp_path, monkeypatch, *, generator):
    monkeypatch.setattr(
        "tubiblia.reading_controller.tempfile.gettempdir",
        lambda: str(tmp_path),
    )
    controller = PocketTTSController(generator=generator, player=FakePlayer())
    return controller


def wait_until(qapp, predicate, timeout=3):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.01)
    qapp.processEvents()
    assert predicate()


def finish_controller(qapp, controller, generator):
    generator.release_first.set()
    assert controller._pool.waitForDone(3000)
    qapp.processEvents()
    controller.stop()
    qapp.processEvents()


def test_generation_runs_in_worker_and_advances_after_playback(
    qapp, tmp_path, monkeypatch
):
    generator = FakeGenerator()
    controller = make_controller(tmp_path, monkeypatch, generator=generator)
    advanced = []
    controller.chapter_advanced.connect(
        lambda book, chapter: advanced.append((book, chapter))
    )

    controller.read_chapter("capítulo actual", (2, 1))
    wait_until(qapp, lambda: controller.state == "playing")

    assert len(generator.thread_ids) == 1
    assert generator.thread_ids[0] != threading.get_ident()
    assert controller._player.play_count == 1
    assert controller._player.source is not None

    controller._player.mediaStatusChanged.emit(
        QMediaPlayer.MediaStatus.EndOfMedia
    )
    qapp.processEvents()

    assert advanced == [(2, 1)]
    assert controller.state == "advancing"
    finish_controller(qapp, controller, generator)


def test_chapter_segments_play_before_following_verse_finishes_generating(
    qapp, tmp_path, monkeypatch
):
    generator = FakeGenerator(block_text="second")
    controller = make_controller(tmp_path, monkeypatch, generator=generator)

    controller.read_chapter(("first", "second", "third"), (2, 1))
    wait_until(qapp, generator.first_started.is_set)
    wait_until(
        qapp,
        lambda: controller.state == "playing"
        and controller._player.play_count == 1,
    )

    assert generator.calls == ["first", "second"]
    assert controller._player.source.toLocalFile() == str(generator.paths[0])

    generator.release_first.set()
    wait_until(qapp, lambda: controller._ready_audio_path is not None)
    assert generator.calls == ["first", "second"]
    controller._player.mediaStatusChanged.emit(
        QMediaPlayer.MediaStatus.EndOfMedia
    )
    wait_until(
        qapp,
        lambda: controller._player.source.toLocalFile()
        == str(generator.paths[1]),
    )
    wait_until(qapp, lambda: controller._ready_audio_path is not None)
    assert generator.calls == ["first", "second", "third"]
    controller._player.mediaStatusChanged.emit(
        QMediaPlayer.MediaStatus.EndOfMedia
    )
    wait_until(
        qapp,
        lambda: controller._player.source.toLocalFile()
        == str(generator.paths[2]),
    )

    finish_controller(qapp, controller, generator)


def test_playback_rate_applies_now_and_to_new_segments(
    qapp, tmp_path, monkeypatch
):
    generator = FakeGenerator()
    controller = make_controller(tmp_path, monkeypatch, generator=generator)
    controller.set_playback_rate(1.25)

    controller.read_chapter(("first", "second"))
    wait_until(qapp, lambda: controller.state == "playing")

    assert controller.playback_rate == 1.25
    assert controller._player.playback_rates[0] == 1.25
    controller.set_playback_rate(1.5)
    assert controller._player.playback_rates[-1] == 1.5
    with pytest.raises(ValueError, match="entre 0.5 y 2.0"):
        controller.set_playback_rate(2.1)

    finish_controller(qapp, controller, generator)


def test_pause_during_generation_pauses_audio_before_resume(
    qapp, tmp_path, monkeypatch
):
    generator = FakeGenerator(block_first=True)
    controller = make_controller(tmp_path, monkeypatch, generator=generator)

    controller.read_chapter("first")
    assert generator.first_started.wait(timeout=3)
    controller.pause()
    assert controller.state == "paused"
    generator.release_first.set()
    wait_until(
        qapp,
        lambda: controller.state == "paused"
        and controller._player.play_count == 1,
    )

    assert controller._player.play_count == 1
    assert controller._player.pause_count == 1
    controller.resume()
    assert controller.state == "playing"
    assert controller._player.play_count == 2
    finish_controller(qapp, controller, generator)


def test_new_request_replaces_cancelled_generation_and_clears_pause(
    qapp, tmp_path, monkeypatch
):
    generator = FakeGenerator(block_first=True)
    controller = make_controller(tmp_path, monkeypatch, generator=generator)

    controller.read_chapter("first")
    assert generator.first_started.wait(timeout=3)
    controller.pause()
    controller.read_chapter("second", (1, 2))
    generator.release_first.set()
    wait_until(
        qapp,
        lambda: controller.state == "playing"
        and len(generator.calls) == 2,
    )

    assert generator.calls == ["first", "second"]
    assert controller._player.source is not None
    assert controller._player.source.toLocalFile() == str(generator.paths[1])
    assert controller._player.pause_count == 0
    assert not generator.paths[0].exists()
    finish_controller(qapp, controller, generator)


def test_generation_failure_is_reported_and_stops_playback(
    qapp, tmp_path, monkeypatch
):
    generator = FakeGenerator(failure="modelo no disponible")
    controller = make_controller(tmp_path, monkeypatch, generator=generator)
    errors = []
    controller.error_occurred.connect(errors.append)

    controller.read_chapter("texto")
    wait_until(qapp, lambda: bool(errors))

    assert errors == ["modelo no disponible"]
    assert controller.state == "stopped"
    assert controller._player.play_count == 0
    finish_controller(qapp, controller, generator)


def test_voice_preparation_runs_in_worker_and_reports_success(
    qapp, tmp_path, monkeypatch
):
    generator = FakeGenerator()
    controller = make_controller(tmp_path, monkeypatch, generator=generator)
    results = []
    controller.voice_preparation_finished.connect(
        lambda success, message: results.append((success, message))
    )

    assert controller.prepare_voice()
    wait_until(qapp, lambda: bool(results))

    assert results[0][0] is True
    assert "Lola" in results[0][1]
    assert generator.voice_ready
    assert generator.preparation_thread_ids[0] != threading.get_ident()
    assert controller.state == "stopped"
    finish_controller(qapp, controller, generator)


def test_voice_preparation_reports_model_errors(
    qapp, tmp_path, monkeypatch
):
    generator = FakeGenerator(failure="modelo no disponible")
    controller = make_controller(tmp_path, monkeypatch, generator=generator)
    results = []
    controller.voice_preparation_finished.connect(
        lambda success, message: results.append(
            (success, message, controller.state)
        )
    )

    assert controller.prepare_voice()
    wait_until(qapp, lambda: bool(results))

    assert results == [(False, "modelo no disponible", "stopped")]
    assert controller.state == "stopped"
    finish_controller(qapp, controller, generator)


def test_voice_preparation_is_rejected_while_reading(
    qapp, tmp_path, monkeypatch
):
    generator = FakeGenerator(block_first=True)
    controller = make_controller(tmp_path, monkeypatch, generator=generator)
    results = []
    controller.voice_preparation_finished.connect(
        lambda success, message: results.append((success, message))
    )

    controller.read_chapter("first")
    assert generator.first_started.wait(timeout=3)

    assert not controller.prepare_voice()
    assert results == [
        (False, "Detén la lectura actual antes de preparar la voz.")
    ]
    finish_controller(qapp, controller, generator)


def test_official_voice_catalog_has_language_matched_defaults():
    assert {
        profile.language: profile.voice for profile in VOICE_PROFILES
    } == {
        "english": "alba",
        "french": "estelle",
        "german": "juergen",
        "italian": "giovanni",
        "dutch": "daan",
        "portuguese": "rafael",
        "spanish": "lola",
    }
    assert DEFAULT_VOICE_PROFILE.display_name == "Español · Lola"


def test_generator_switches_profile_and_reuses_model_for_voice_change(
    monkeypatch, tmp_path
):
    calls = []

    class FakeModel:
        sample_rate = 24000

        def get_state_for_audio_prompt(self, voice):
            calls.append(("voice", voice))
            return f"state:{voice}"

    class FakeTTSModel:
        @staticmethod
        def load_model(language):
            calls.append(("language", language))
            return FakeModel()

    pocket_tts = ModuleType("pocket_tts")
    pocket_tts.TTSModel = FakeTTSModel
    monkeypatch.setitem(sys.modules, "pocket_tts", pocket_tts)

    generator = PocketTTSGenerator()
    generator.prepare_voice()
    assert generator.voice_ready
    assert calls == [("language", "spanish"), ("voice", "lola")]

    generator.configure_voice("english", "alba")
    assert not generator.voice_ready
    generator.prepare_voice()
    assert generator.voice_ready
    assert calls[-2:] == [("language", "english"), ("voice", "alba")]

    with pytest.raises(ValueError, match="Voz no disponible"):
        generator.configure_voice("english", "lola")


def test_controller_voice_selection_is_rejected_while_reading(
    qapp, tmp_path, monkeypatch
):
    generator = FakeGenerator(block_first=True)
    controller = make_controller(tmp_path, monkeypatch, generator=generator)

    assert controller.select_voice("dutch", "daan")
    assert generator.language == "dutch"
    assert generator.voice == "daan"
    assert controller.selected_voice_profile.display_name == "Nederlands · Daan"

    controller.read_chapter("first")
    assert generator.first_started.wait(timeout=3)
    assert not controller.select_voice("spanish", "lola")
    assert generator.language == "dutch"
    finish_controller(qapp, controller, generator)
