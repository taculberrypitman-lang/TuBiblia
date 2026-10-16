# Copyright © 2026 CunaWare.Lab
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

from collections.abc import Sequence
import tempfile
import uuid
from pathlib import Path
from threading import Event

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QUrl, Signal
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

from tubiblia.pocket_tts import (
    DEFAULT_VOICE_PROFILE,
    PocketTTSGenerator,
    VoiceProfile,
    voice_profile,
)


class _GenerationSignals(QObject):
    completed = Signal(int, int, str)
    failed = Signal(int, int, str)
    finished = Signal(int, int)


class _GenerationTask(QRunnable):
    def __init__(
        self,
        request_id: int,
        segment_index: int,
        text: str,
        output_path: Path,
        cancelled: Event,
        generator: PocketTTSGenerator,
    ) -> None:
        super().__init__()
        self.request_id = request_id
        self.segment_index = segment_index
        self.text = text
        self.output_path = output_path
        self.cancelled = cancelled
        self.generator = generator
        self.signals = _GenerationSignals()

    def run(self) -> None:
        try:
            result = self.generator.generate_wav(
                self.text, self.output_path, self.cancelled
            )
            if result is not None:
                self.signals.completed.emit(
                    self.request_id, self.segment_index, str(result)
                )
            else:
                self.output_path.unlink(missing_ok=True)
        except Exception as exc:
            self.output_path.unlink(missing_ok=True)
            self.signals.failed.emit(
                self.request_id, self.segment_index, str(exc)
            )
        finally:
            self.signals.finished.emit(self.request_id, self.segment_index)


class _VoicePreparationSignals(QObject):
    completed = Signal()
    failed = Signal(str)
    finished = Signal()


class _VoicePreparationTask(QRunnable):
    def __init__(self, generator: PocketTTSGenerator) -> None:
        super().__init__()
        self.generator = generator
        self.signals = _VoicePreparationSignals()

    def run(self) -> None:
        try:
            self.generator.prepare_voice()
            self.signals.completed.emit()
        except Exception as exc:
            self.signals.failed.emit(str(exc))
        finally:
            self.signals.finished.emit()


class PocketTTSController(QObject):
    state_changed = Signal(str)
    error_occurred = Signal(str)
    chapter_advanced = Signal(int, int)
    voice_preparation_finished = Signal(bool, str)
    progress_changed = Signal(int, int)

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        generator: PocketTTSGenerator | None = None,
        player: QMediaPlayer | None = None,
    ) -> None:
        super().__init__(parent)
        self._generator = generator or PocketTTSGenerator()
        self._voice_profile = DEFAULT_VOICE_PROFILE
        self._player = player or QMediaPlayer(self)
        self._audio_output = None
        if player is None:
            self._audio_output = QAudioOutput(self)
            self._player.setAudioOutput(self._audio_output)
        self._player.mediaStatusChanged.connect(self._on_media_status_changed)
        self._player.errorOccurred.connect(self._on_player_error)

        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        self._state = "stopped"
        self._playback_rate = 1.0
        self._request_id = 0
        self._active_worker = False
        self._cancelled: Event | None = None
        self._task: _GenerationTask | None = None
        self._voice_preparation_task: _VoicePreparationTask | None = None
        self._preparing_voice = False
        self._pending_request: (
            tuple[tuple[str, ...], tuple[int, int] | None] | None
        ) = None
        self._next_reference: tuple[int, int] | None = None
        self._segments: tuple[str, ...] = ()
        self._next_segment_index = 0
        self._ready_audio_path: Path | None = None
        self._ready_segment_index: int | None = None
        self._audio_path: Path | None = None
        self._paused = False
        self._cache_directory = Path(tempfile.gettempdir()) / "tubiblia-audio"
        self._cache_directory.mkdir(parents=True, exist_ok=True)

    @property
    def state(self) -> str:
        return self._state

    @property
    def is_active(self) -> bool:
        return self._state != "stopped"

    @property
    def voice_ready(self) -> bool:
        return bool(getattr(self._generator, "voice_ready", False))

    @property
    def selected_voice_profile(self) -> VoiceProfile:
        return self._voice_profile

    @property
    def playback_rate(self) -> float:
        return self._playback_rate

    def set_playback_rate(self, rate: float) -> None:
        if not 0.5 <= rate <= 2.0:
            raise ValueError("La velocidad debe estar entre 0.5 y 2.0.")
        self._playback_rate = float(rate)
        self._player.setPlaybackRate(self._playback_rate)

    def select_voice(self, language: str, voice: str) -> bool:
        if self._preparing_voice or self._active_worker or self.is_active:
            return False
        profile = voice_profile(language, voice)
        self._generator.configure_voice(profile.language, profile.voice)
        self._voice_profile = profile
        return True

    def prepare_voice(self) -> bool:
        if self._preparing_voice or self._active_worker or self.is_active:
            self.voice_preparation_finished.emit(
                False,
                "Detén la lectura actual antes de preparar la voz.",
            )
            return False
        self._preparing_voice = True
        task = _VoicePreparationTask(self._generator)
        task.signals.completed.connect(self._on_voice_preparation_completed)
        task.signals.failed.connect(self._on_voice_preparation_failed)
        task.signals.finished.connect(self._on_voice_preparation_finished)
        self._voice_preparation_task = task
        self._pool.start(task)
        self._set_state("preparing_voice")
        return True

    def read_chapter(
        self,
        text: str | Sequence[str],
        next_reference: tuple[int, int] | None = None,
    ) -> None:
        if self._preparing_voice:
            self.error_occurred.emit(
                "Espera a que termine la preparación de la voz antes de leer."
            )
            return
        segments = (text,) if isinstance(text, str) else tuple(text)
        segments = tuple(segment.strip() for segment in segments if segment.strip())
        if not segments:
            self.error_occurred.emit("El capítulo no contiene texto para leer.")
            return
        self._player.stop()
        self._clear_audio_file()
        self._clear_ready_audio_file()
        self._paused = False
        self._request_id += 1
        request_id = self._request_id
        self._cancel_active_worker()
        if self._active_worker:
            self._pending_request = (segments, next_reference)
            self._set_state("generating")
            return
        self._pending_request = None
        self._begin_request(segments, next_reference, request_id)

    def pause(self) -> None:
        if self._state not in {"generating", "playing"}:
            return
        self._paused = True
        if self._state == "playing":
            self._player.pause()
        self._set_state("paused")

    def resume(self) -> None:
        if self._state != "paused":
            return
        self._paused = False
        if self._audio_path is not None:
            self._player.play()
            self._set_state("playing")
        else:
            if self._ready_audio_path is not None:
                self._start_ready_audio()
            else:
                self._set_state("generating")

    def stop(self) -> None:
        self._request_id += 1
        self._cancel_active_worker()
        self._pending_request = None
        self._paused = False
        self._next_reference = None
        self._player.stop()
        self._clear_audio_file()
        self._clear_ready_audio_file()
        self._segments = ()
        self._next_segment_index = 0
        self._set_state("stopped")

    def _begin_request(
        self,
        segments: tuple[str, ...],
        next_reference: tuple[int, int] | None,
        request_id: int,
    ) -> None:
        self._segments = segments
        self._next_segment_index = 0
        self._next_reference = next_reference
        self._start_next_generation(request_id)

    def _start_next_generation(self, request_id: int) -> None:
        if (
            self._active_worker
            or request_id != self._request_id
            or self._next_segment_index >= len(self._segments)
        ):
            return
        segment_index = self._next_segment_index
        text = self._segments[segment_index]
        self._next_segment_index += 1
        cancelled = Event()
        self._cancelled = cancelled
        self._active_worker = True
        output_path = self._cache_directory / f"{uuid.uuid4().hex}.wav"
        task = _GenerationTask(
            request_id,
            segment_index,
            text,
            output_path,
            cancelled,
            self._generator,
        )
        task.signals.completed.connect(self._on_generation_completed)
        task.signals.failed.connect(self._on_generation_failed)
        task.signals.finished.connect(self._on_generation_finished)
        self._task = task
        self._pool.start(task)
        if self._audio_path is None:
            self._set_state("generating")

    def _cancel_active_worker(self) -> None:
        if self._cancelled is not None:
            self._cancelled.set()
            self._cancelled = None

    def _on_generation_completed(
        self, request_id: int, segment_index: int, path: str
    ) -> None:
        generated_path = Path(path)
        if request_id != self._request_id:
            generated_path.unlink(missing_ok=True)
            return
        if self._audio_path is None:
            self._audio_path = generated_path
            self._ready_segment_index = segment_index
            self._start_ready_audio()
        else:
            self._clear_ready_audio_file()
            self._ready_audio_path = generated_path
            self._ready_segment_index = segment_index

    def _on_generation_failed(
        self, request_id: int, segment_index: int, message: str
    ) -> None:
        if request_id != self._request_id:
            return
        self.stop()
        self.error_occurred.emit(message)

    def _on_generation_finished(
        self, request_id: int, segment_index: int
    ) -> None:
        self._active_worker = False
        self._task = None
        if request_id == self._request_id:
            self._cancelled = None
        pending = self._pending_request
        self._pending_request = None
        if pending is not None:
            segments, next_reference = pending
            self._paused = False
            self._begin_request(segments, next_reference, self._request_id)
        elif (
            request_id == self._request_id
            and self._ready_audio_path is None
        ):
            self._start_next_generation(request_id)

    def _on_voice_preparation_completed(self) -> None:
        profile = self._voice_profile
        self._set_state("stopped")
        self.voice_preparation_finished.emit(
            True,
            f"La voz {profile.voice_name} ({profile.language_name}) está "
            "preparada. Los recursos quedan en la caché local de Pocket TTS.",
        )

    def _on_voice_preparation_failed(self, message: str) -> None:
        self._set_state("stopped")
        self.voice_preparation_finished.emit(False, message)

    def _on_voice_preparation_finished(self) -> None:
        self._preparing_voice = False
        self._voice_preparation_task = None

    def _on_media_status_changed(self, status: QMediaPlayer.MediaStatus) -> None:
        if status != QMediaPlayer.MediaStatus.EndOfMedia or self._state == "stopped":
            return
        self._clear_audio_file()
        if self._ready_audio_path is not None:
            self._audio_path = self._ready_audio_path
            self._ready_audio_path = None
            self._start_ready_audio()
            self._start_next_generation(self._request_id)
            return
        if self._active_worker:
            self._set_state("generating")
            return
        if self._next_segment_index < len(self._segments):
            self._start_next_generation(self._request_id)
            return
        next_reference = self._next_reference
        self._next_reference = None
        self._segments = ()
        self._next_segment_index = 0
        if next_reference is None:
            self._set_state("stopped")
        else:
            self._set_state("advancing")
            self.chapter_advanced.emit(*next_reference)

    def _on_player_error(
        self, error: QMediaPlayer.Error, error_string: str
    ) -> None:
        if error == QMediaPlayer.Error.NoError:
            return
        self.stop()
        self.error_occurred.emit(
            "No se pudo reproducir el audio generado. "
            + (error_string or "El dispositivo de audio no está disponible.")
        )

    def _start_ready_audio(self) -> None:
        if self._audio_path is None:
            return
        self._player.setSource(QUrl.fromLocalFile(str(self._audio_path)))
        self._player.setPlaybackRate(self._playback_rate)
        if self._ready_segment_index is not None:
            self.progress_changed.emit(
                self._ready_segment_index + 1, len(self._segments)
            )
            self._ready_segment_index = None
        if self._paused:
            self._player.play()
            self._player.pause()
            self._set_state("paused")
        else:
            self._player.play()
            self._set_state("playing")

    def _clear_audio_file(self) -> None:
        if self._audio_path is not None:
            self._audio_path.unlink(missing_ok=True)
            self._audio_path = None

    def _clear_ready_audio_file(self) -> None:
        if self._ready_audio_path is not None:
            self._ready_audio_path.unlink(missing_ok=True)
            self._ready_audio_path = None
        self._ready_segment_index = None

    def _set_state(self, state: str) -> None:
        if self._state == state:
            return
        self._state = state
        self.state_changed.emit(state)
