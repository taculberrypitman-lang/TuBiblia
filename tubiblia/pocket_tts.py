# Copyright © 2026 CunaWare.Lab
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

from dataclasses import dataclass
import wave
from pathlib import Path
from threading import Event


@dataclass(frozen=True)
class VoiceProfile:
    language: str
    language_name: str
    voice: str
    voice_name: str

    @property
    def display_name(self) -> str:
        return f"{self.language_name} · {self.voice_name}"


VOICE_PROFILES = (
    VoiceProfile("english", "English", "alba", "Alba"),
    VoiceProfile("french", "Français", "estelle", "Estelle"),
    VoiceProfile("german", "Deutsch", "juergen", "Juergen"),
    VoiceProfile("italian", "Italiano", "giovanni", "Giovanni"),
    VoiceProfile("dutch", "Nederlands", "daan", "Daan"),
    VoiceProfile("portuguese", "Português", "rafael", "Rafael"),
    VoiceProfile("spanish", "Español", "lola", "Lola"),
)
DEFAULT_VOICE_PROFILE = VOICE_PROFILES[-1]


def voice_profile(language: str, voice: str) -> VoiceProfile:
    for profile in VOICE_PROFILES:
        if profile.language == language and profile.voice == voice:
            return profile
    raise ValueError(f"Voz no disponible para el idioma seleccionado: {voice}")


class PocketTTSError(RuntimeError):
    """Pocket TTS could not load its model or generate audio."""


class PocketTTSNotInstalledError(PocketTTSError):
    """The Pocket TTS dependency is not installed."""


class PocketTTSGenerator:
    def __init__(self) -> None:
        self.language = DEFAULT_VOICE_PROFILE.language
        self.voice = DEFAULT_VOICE_PROFILE.voice
        self._model = None
        self._voice_state = None
        self._model_language: str | None = None

    @property
    def voice_ready(self) -> bool:
        return (
            self._model is not None
            and self._model_language == self.language
            and self._voice_state is not None
        )

    @property
    def selected_profile(self) -> VoiceProfile:
        return voice_profile(self.language, self.voice)

    def configure_voice(self, language: str, voice: str) -> None:
        profile = voice_profile(language, voice)
        if profile.language == self.language and profile.voice == self.voice:
            return
        if profile.language != self.language:
            self._model = None
            self._model_language = None
        self._voice_state = None
        self.language = profile.language
        self.voice = profile.voice

    def prepare_voice(self) -> None:
        self._load_model()

    def generate_wav(
        self, text: str, output_path: Path, cancelled: Event
    ) -> Path | None:
        if cancelled.is_set():
            return None
        if not text.strip():
            raise PocketTTSError("No hay texto para convertir en voz.")

        self._load_model()
        if cancelled.is_set():
            return None

        try:
            import numpy as np

            audio = self._model.generate_audio(self._voice_state, text)
            pcm = audio.detach().cpu().numpy()
            if pcm.size == 0:
                raise PocketTTSError("Pocket TTS no generó audio para este texto.")
            pcm = np.asarray(pcm).reshape(-1)
            if pcm.dtype.kind == "f":
                pcm = np.nan_to_num(pcm, nan=0.0, posinf=1.0, neginf=-1.0)
                pcm = (np.clip(pcm, -1.0, 1.0) * 32767).astype(np.int16)
            with wave.open(str(output_path), "wb") as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(self._model.sample_rate)
                output.writeframes(pcm.astype("<i2", copy=False).tobytes())
        except PocketTTSError:
            raise
        except Exception as exc:
            raise PocketTTSError(f"No se pudo generar el audio: {exc}") from exc

        return None if cancelled.is_set() else output_path

    def _load_model(self) -> None:
        if self.voice_ready:
            return
        try:
            from pocket_tts import TTSModel
        except ImportError as exc:
            raise PocketTTSNotInstalledError(
                "Pocket TTS no está disponible en esta instalación. Reinstala "
                "TuBiblia con sus dependencias de proyecto."
            ) from exc

        try:
            model = self._model
            if model is None or self._model_language != self.language:
                model = TTSModel.load_model(language=self.language)
            voice_state = model.get_state_for_audio_prompt(self.voice)
        except Exception as exc:
            profile = self.selected_profile
            raise PocketTTSError(
                f"No se pudo cargar el modelo o la voz {profile.voice_name} "
                f"({profile.language_name}). "
                "Comprueba la conexión inicial, la caché y las condiciones de "
                f"acceso de los recursos de Kyutai. Detalle: {exc}"
            ) from exc
        self._model = model
        self._model_language = self.language
        self._voice_state = voice_state
