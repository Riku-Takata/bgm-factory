from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

import librosa
import numpy as np
import pyloudnorm as pyln
import soundfile as sf

from .config import AppConfig


def clamp(value: float) -> float:
    return float(max(0.0, min(1.0, value)))


def cosine_similarity(left: np.ndarray, right: np.ndarray) -> float:
    denominator = float(np.linalg.norm(left) * np.linalg.norm(right))
    if denominator <= 1e-12:
        return 0.0
    return clamp((float(np.dot(left, right)) / denominator + 1.0) / 2.0)


def correct_half_double_tempo(estimated_bpm: float, requested_bpm: float) -> float:
    if estimated_bpm <= 0 or requested_bpm <= 0:
        return estimated_bpm
    candidates = (estimated_bpm / 2.0, estimated_bpm, estimated_bpm * 2.0)
    plausible = [candidate for candidate in candidates if 30 <= candidate <= 300]
    return min(plausible, key=lambda candidate: abs(candidate - requested_bpm))


@dataclass(frozen=True)
class AudioAnalysis:
    duration_sec: float
    sample_rate: int
    bpm: float
    peak: float
    lufs: float
    silence_ratio: float
    clipping_ratio: float
    spectral_centroid: float
    hook_start: float
    hook_end: float
    loop_start: float
    loop_end: float
    quality_score: float
    hook_score: float
    loop_score: float
    final_score: float

    def to_dict(self) -> dict:
        return asdict(self)


class AudioAnalyzer:
    def __init__(self, config: AppConfig):
        self.config = config

    def analyze(self, audio_path: Path) -> AudioAnalysis:
        waveform, sample_rate = librosa.load(audio_path, sr=None, mono=True)
        if waveform.size == 0:
            raise ValueError(f"Empty audio file: {audio_path}")
        waveform = np.asarray(waveform, dtype=np.float32)
        duration = float(waveform.size / sample_rate)
        peak = float(np.max(np.abs(waveform)))
        clipping_ratio = float(np.mean(np.abs(waveform) >= 0.999))
        silence_ratio = float(np.mean(np.abs(waveform) < 10 ** (-50 / 20)))
        meter = pyln.Meter(sample_rate)
        lufs = float(meter.integrated_loudness(waveform))
        if not np.isfinite(lufs):
            lufs = -70.0

        tempo, beat_frames = librosa.beat.beat_track(y=waveform, sr=sample_rate)
        bpm = float(np.asarray(tempo).reshape(-1)[0]) if np.size(tempo) else 0.0
        centroid = librosa.feature.spectral_centroid(y=waveform, sr=sample_rate)[0]
        spectral_centroid = float(np.mean(centroid))
        rms = librosa.feature.rms(y=waveform)[0]

        hook_start, hook_end, hook_score = self._find_hook(waveform, sample_rate)
        loop_score = self._loop_score(waveform, sample_rate, beat_frames)
        quality_score = self._quality_score(peak, lufs, silence_ratio, clipping_ratio, rms)
        final_score = clamp(0.45 * hook_score + 0.30 * loop_score + 0.25 * quality_score)
        return AudioAnalysis(
            duration_sec=duration,
            sample_rate=sample_rate,
            bpm=bpm,
            peak=peak,
            lufs=lufs,
            silence_ratio=silence_ratio,
            clipping_ratio=clipping_ratio,
            spectral_centroid=spectral_centroid,
            hook_start=hook_start,
            hook_end=hook_end,
            loop_start=0.0,
            loop_end=duration,
            quality_score=quality_score,
            hook_score=hook_score,
            loop_score=loop_score,
            final_score=final_score,
        )

    def _find_hook(self, waveform: np.ndarray, sample_rate: int) -> tuple[float, float, float]:
        duration_samples = min(
            len(waveform), int(self.config.hook.duration_sec * sample_rate)
        )
        step_samples = max(1, int(self.config.hook.window_step_sec * sample_rate))
        starts = range(0, max(1, len(waveform) - duration_samples + 1), step_samples)
        candidates: list[tuple[float, int]] = []
        for start in starts:
            window = waveform[start : start + duration_samples]
            rms = librosa.feature.rms(y=window)[0]
            energy = clamp((float(np.mean(rms)) + 0.02) / 0.20)
            onset = librosa.onset.onset_strength(y=window, sr=sample_rate)
            beat_score = clamp(float(np.mean(onset)) / 3.0)
            chroma = librosa.feature.chroma_stft(y=window, sr=sample_rate)
            melody = clamp(float(np.std(np.mean(chroma, axis=1))) * 8.0)
            half = max(1, chroma.shape[1] // 2)
            repetition = cosine_similarity(
                np.mean(chroma[:, :half], axis=1), np.mean(chroma[:, -half:], axis=1)
            )
            no_silence = 1.0 - float(np.mean(np.abs(window) < 10 ** (-50 / 20)))
            stability = clamp(1.0 - float(np.std(rms)) / (float(np.mean(rms)) + 1e-6))
            score = clamp(
                0.25 * energy
                + 0.20 * beat_score
                + 0.20 * repetition
                + 0.15 * melody
                + 0.10 * no_silence
                + 0.10 * stability
            )
            candidates.append((score, start))
        score, start = max(candidates, default=(0.0, 0))
        return start / sample_rate, (start + duration_samples) / sample_rate, score

    def _loop_score(
        self, waveform: np.ndarray, sample_rate: int, beat_frames: np.ndarray
    ) -> float:
        window_size = min(len(waveform) // 3, int(sample_rate * 0.5))
        if window_size < 1024:
            return 0.0
        start = waveform[:window_size]
        end = waveform[-window_size:]
        mfcc_start = np.mean(librosa.feature.mfcc(y=start, sr=sample_rate, n_mfcc=13), axis=1)
        mfcc_end = np.mean(librosa.feature.mfcc(y=end, sr=sample_rate, n_mfcc=13), axis=1)
        chroma_start = np.mean(librosa.feature.chroma_stft(y=start, sr=sample_rate), axis=1)
        chroma_end = np.mean(librosa.feature.chroma_stft(y=end, sr=sample_rate), axis=1)
        rms_start = float(np.sqrt(np.mean(np.square(start))))
        rms_end = float(np.sqrt(np.mean(np.square(end))))
        rms_similarity = clamp(1.0 - abs(rms_start - rms_end) / (max(rms_start, rms_end) + 1e-6))
        spectrum_start = np.abs(np.fft.rfft(start))
        spectrum_end = np.abs(np.fft.rfft(end))
        beat_alignment = 1.0 if len(beat_frames) >= 2 else 0.5
        return clamp(
            0.30 * cosine_similarity(mfcc_start, mfcc_end)
            + 0.25 * cosine_similarity(chroma_start, chroma_end)
            + 0.20 * rms_similarity
            + 0.15 * cosine_similarity(spectrum_start, spectrum_end)
            + 0.10 * beat_alignment
        )

    def _quality_score(
        self,
        peak: float,
        lufs: float,
        silence_ratio: float,
        clipping_ratio: float,
        rms: np.ndarray,
    ) -> float:
        integrity = 1.0 if np.all(np.isfinite(rms)) and peak > 0.01 else 0.0
        loudness = clamp(1.0 - abs(lufs - self.config.audio.target_lufs) / 24.0)
        no_clipping = clamp(1.0 - clipping_ratio / 0.005)
        no_silence = clamp(1.0 - silence_ratio / 0.20)
        stability = clamp(1.0 - float(np.std(rms)) / (float(np.mean(rms)) + 1e-6))
        return clamp(
            0.25 * integrity
            + 0.20 * loudness
            + 0.20 * no_clipping
            + 0.20 * no_silence
            + 0.15 * stability
        )

    def normalize(self, source: Path, destination: Path) -> None:
        audio, sample_rate = sf.read(source, always_2d=True)
        mono = np.mean(audio, axis=1)
        meter = pyln.Meter(sample_rate)
        loudness = float(meter.integrated_loudness(mono))
        normalized = audio
        if np.isfinite(loudness):
            gain = 10 ** ((self.config.audio.target_lufs - loudness) / 20)
            normalized = audio * gain
        ceiling = 10 ** (self.config.audio.true_peak_db / 20)
        current_peak = float(np.max(np.abs(normalized)))
        if current_peak > ceiling:
            normalized *= ceiling / current_peak
        destination.parent.mkdir(parents=True, exist_ok=True)
        sf.write(destination, normalized, sample_rate, subtype="PCM_16")

    def write_hook(self, master: Path, destination: Path, start: float, end: float) -> None:
        audio, sample_rate = sf.read(master, always_2d=True)
        start_sample = max(0, int(start * sample_rate))
        end_sample = min(len(audio), int(end * sample_rate))
        destination.parent.mkdir(parents=True, exist_ok=True)
        sf.write(destination, audio[start_sample:end_sample], sample_rate, subtype="PCM_16")
