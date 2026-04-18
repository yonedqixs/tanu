import io
import sys
import wave

import numpy as np
import requests
import soundcard as sc
from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot
from PySide6.QtWidgets import (
    QApplication,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)


DEFAULT_SERVER_URL = "http://127.0.0.1:8000"


class WorkerSignals(QObject):
    status = Signal(str)
    finished = Signal(dict)
    error = Signal(str)


def capture_system_wav(duration_sec: int, samplerate: int = 44100, channels: int = 2) -> bytes:
    speaker = sc.default_speaker()
    if speaker is None:
        raise RuntimeError("No default speaker found on this system")

    speaker_id = getattr(speaker, "id", None)
    speaker_name = getattr(speaker, "name", None)
    if not speaker_id and not speaker_name:
        raise RuntimeError("Unable to resolve default speaker for loopback capture")

    loopback_mic = None
    if speaker_id:
        try:
            loopback_mic = sc.get_microphone(speaker_id, include_loopback=True)
        except Exception:  # noqa: BLE001
            loopback_mic = None
    if loopback_mic is None and speaker_name:
        loopback_mic = sc.get_microphone(speaker_name, include_loopback=True)
    if loopback_mic is None:
        raise RuntimeError("Loopback capture is unavailable for this output device")

    numframes = int(duration_sec * samplerate)
    with loopback_mic.recorder(samplerate=samplerate, channels=channels) as recorder:
        frames = recorder.record(numframes=numframes)

    if frames is None or len(frames) == 0:
        raise RuntimeError("No audio frames captured. Check if any sound is playing.")

    clipped = np.clip(frames, -1.0, 1.0)
    pcm16 = (clipped * 32767).astype(np.int16)

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(2)
        wav_file.setframerate(samplerate)
        wav_file.writeframes(pcm16.tobytes())

    return buffer.getvalue()


def recognize_on_server(server_url: str, wav_bytes: bytes) -> dict:
    url = f"{server_url.rstrip('/')}/recognize"
    files = {"file": ("sample.wav", wav_bytes, "audio/wav")}
    response = requests.post(url, files=files, timeout=35)

    if not response.ok:
        details = response.text.strip()
        raise RuntimeError(f"Recognition request failed [{response.status_code}]: {details}")

    payload = response.json()
    return {
        "track": payload.get("track", "Unknown Track"),
        "artist": payload.get("artist", "Unknown Artist"),
        "confidence": float(payload.get("confidence", 0.0)),
    }


class RecognitionWorker(QRunnable):
    def __init__(self, server_url: str, duration_sec: int):
        super().__init__()
        self.server_url = server_url
        self.duration_sec = duration_sec
        self.signals = WorkerSignals()

    @Slot()
    def run(self) -> None:
        try:
            self.signals.status.emit("Listening...")
            wav_bytes = capture_system_wav(duration_sec=self.duration_sec)

            self.signals.status.emit("Processing...")
            result = recognize_on_server(server_url=self.server_url, wav_bytes=wav_bytes)
            self.signals.finished.emit(result)
        except Exception as exc:  # noqa: BLE001
            self.signals.error.emit(str(exc))


class TanuClientWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Tanu Client")
        self.setMinimumWidth(620)
        self.thread_pool = QThreadPool.globalInstance()
        self.worker_busy = False
        self._build_ui()
        self._apply_styles()

    def _build_ui(self) -> None:
        wrapper = QWidget()
        self.setCentralWidget(wrapper)

        root_layout = QVBoxLayout(wrapper)
        root_layout.setContentsMargins(18, 18, 18, 18)
        root_layout.setSpacing(14)

        title = QLabel("Tanu")
        title.setObjectName("title")
        subtitle = QLabel("Desktop System-Audio Recognition")
        subtitle.setObjectName("subtitle")

        top_box = QVBoxLayout()
        top_box.addWidget(title)
        top_box.addWidget(subtitle)

        controls_frame = QFrame()
        controls_frame.setObjectName("panel")
        form = QFormLayout(controls_frame)
        form.setContentsMargins(14, 14, 14, 14)
        form.setSpacing(10)

        self.server_input = QLineEdit(DEFAULT_SERVER_URL)
        self.duration_input = QSpinBox()
        self.duration_input.setRange(5, 10)
        self.duration_input.setValue(7)
        self.duration_input.setSuffix(" sec")

        form.addRow("Server URL", self.server_input)
        form.addRow("Capture Duration", self.duration_input)

        self.start_button = QPushButton("Start Listening")
        self.start_button.clicked.connect(self.start_listening)

        status_frame = QFrame()
        status_frame.setObjectName("panel")
        status_layout = QVBoxLayout(status_frame)
        status_layout.setContentsMargins(14, 14, 14, 14)
        status_layout.setSpacing(8)

        self.status_value = QLabel("Idle")
        self.status_value.setObjectName("status")
        self.track_value = QLabel("Track: -")
        self.artist_value = QLabel("Artist: -")
        self.conf_value = QLabel("Confidence: -")

        status_layout.addWidget(self.status_value)
        status_layout.addWidget(self.track_value)
        status_layout.addWidget(self.artist_value)
        status_layout.addWidget(self.conf_value)

        button_row = QHBoxLayout()
        button_row.addWidget(self.start_button)
        button_row.addStretch()

        root_layout.addLayout(top_box)
        root_layout.addWidget(controls_frame)
        root_layout.addLayout(button_row)
        root_layout.addWidget(status_frame)

    def _apply_styles(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow {
                background-color: #0d0d13;
                color: #ececf6;
                font-family: 'Segoe UI';
            }
            QLabel#title {
                font-size: 34px;
                font-weight: 700;
                letter-spacing: 2px;
            }
            QLabel#subtitle {
                color: #b3b3cb;
            }
            QFrame#panel {
                background-color: #1a1a27;
                border: 1px solid #2d2d43;
                border-radius: 10px;
            }
            QLineEdit, QSpinBox {
                background-color: #12121b;
                color: #f2f2ff;
                border: 1px solid #3a3a57;
                border-radius: 8px;
                padding: 6px;
            }
            QPushButton {
                background-color: #8a45ff;
                border: none;
                border-radius: 8px;
                color: white;
                font-size: 14px;
                font-weight: 600;
                padding: 9px 16px;
            }
            QPushButton:hover {
                background-color: #9a5bff;
            }
            QPushButton:disabled {
                background-color: #51406b;
                color: #d3cce4;
            }
            QLabel#status {
                color: #b98bff;
                font-weight: 600;
                font-size: 16px;
            }
            """
        )

    @Slot()
    def start_listening(self) -> None:
        if self.worker_busy:
            return

        self.worker_busy = True
        self.start_button.setEnabled(False)
        self.status_value.setText("Preparing...")
        self.track_value.setText("Track: -")
        self.artist_value.setText("Artist: -")
        self.conf_value.setText("Confidence: -")

        worker = RecognitionWorker(
            server_url=self.server_input.text().strip(),
            duration_sec=self.duration_input.value(),
        )
        worker.signals.status.connect(self._on_status)
        worker.signals.finished.connect(self._on_finished)
        worker.signals.error.connect(self._on_error)
        self.thread_pool.start(worker)

    @Slot(str)
    def _on_status(self, text: str) -> None:
        self.status_value.setText(text)

    @Slot(dict)
    def _on_finished(self, payload: dict) -> None:
        self.status_value.setText("Result")
        self.track_value.setText(f"Track: {payload.get('track', '-')}")
        self.artist_value.setText(f"Artist: {payload.get('artist', '-')}")
        conf = payload.get("confidence", 0.0)
        self.conf_value.setText(f"Confidence: {conf:.2f}")
        self.worker_busy = False
        self.start_button.setEnabled(True)

    @Slot(str)
    def _on_error(self, error_text: str) -> None:
        self.status_value.setText("Error")
        self.track_value.setText("Track: -")
        self.artist_value.setText("Artist: -")
        self.conf_value.setText(f"Message: {error_text}")
        self.worker_busy = False
        self.start_button.setEnabled(True)


def main() -> None:
    app = QApplication(sys.argv)
    window = TanuClientWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
