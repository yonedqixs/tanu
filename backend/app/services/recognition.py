import base64
import hashlib
import hmac
import time
from dataclasses import dataclass
from typing import Optional

import httpx

from app.config import settings


class RecognitionError(Exception):
    pass


@dataclass
class RecognitionResult:
    track: str
    artist: str
    confidence: float
    provider: str


def _normalize_confidence(value: Optional[float], default: float = 0.5) -> float:
    if value is None:
        return default
    try:
        value = float(value)
    except (TypeError, ValueError):
        return default
    if value > 1.0:
        value = value / 100.0
    return max(0.0, min(1.0, value))


async def _recognize_with_audd(audio_bytes: bytes) -> RecognitionResult:
    if not settings.audd_api_token:
        raise RecognitionError("AUDD_API_TOKEN is not configured")

    url = "https://api.audd.io/"
    files = {
        "file": ("sample.wav", audio_bytes, "audio/wav"),
    }
    data = {"api_token": settings.audd_api_token, "return": "apple_music,spotify"}

    async with httpx.AsyncClient(timeout=25) as client:
        response = await client.post(url, data=data, files=files)
    response.raise_for_status()
    payload = response.json()

    result = payload.get("result")
    if not result:
        raise RecognitionError("AudD did not identify a track")

    return RecognitionResult(
        track=result.get("title", "Unknown Track"),
        artist=result.get("artist", "Unknown Artist"),
        confidence=_normalize_confidence(result.get("score"), default=0.9),
        provider="audd",
    )


def _acrcloud_signature(
    method: str,
    uri: str,
    access_key: str,
    data_type: str,
    signature_version: str,
    timestamp: str,
    access_secret: str,
) -> str:
    sign_string = "\n".join([method, uri, access_key, data_type, signature_version, timestamp])
    dig = hmac.new(access_secret.encode("utf-8"), sign_string.encode("utf-8"), hashlib.sha1).digest()
    return base64.b64encode(dig).decode("utf-8")


async def _recognize_with_acrcloud(audio_bytes: bytes) -> RecognitionResult:
    if not settings.acrcloud_host or not settings.acrcloud_access_key or not settings.acrcloud_access_secret:
        raise RecognitionError("ACRCloud credentials are not fully configured")

    uri = "/v1/identify"
    method = "POST"
    data_type = "audio"
    signature_version = "1"
    timestamp = str(int(time.time()))
    signature = _acrcloud_signature(
        method=method,
        uri=uri,
        access_key=settings.acrcloud_access_key,
        data_type=data_type,
        signature_version=signature_version,
        timestamp=timestamp,
        access_secret=settings.acrcloud_access_secret,
    )

    url = f"https://{settings.acrcloud_host}{uri}"
    data = {
        "access_key": settings.acrcloud_access_key,
        "sample_bytes": str(len(audio_bytes)),
        "timestamp": timestamp,
        "signature": signature,
        "data_type": data_type,
        "signature_version": signature_version,
    }
    files = {"sample": ("sample.wav", audio_bytes, "audio/wav")}

    async with httpx.AsyncClient(timeout=25) as client:
        response = await client.post(url, data=data, files=files)
    response.raise_for_status()
    payload = response.json()

    status = payload.get("status", {})
    if status.get("code") != 0:
        message = status.get("msg", "ACRCloud recognition failed")
        raise RecognitionError(message)

    music = payload.get("metadata", {}).get("music", [])
    if not music:
        raise RecognitionError("ACRCloud did not identify a track")

    first = music[0]
    artist_items = first.get("artists", [])
    artist = artist_items[0].get("name", "Unknown Artist") if artist_items else "Unknown Artist"
    score = first.get("score")

    return RecognitionResult(
        track=first.get("title", "Unknown Track"),
        artist=artist,
        confidence=_normalize_confidence(score, default=0.9),
        provider="acrcloud",
    )


async def recognize_audio(audio_bytes: bytes) -> RecognitionResult:
    provider = settings.recognition_provider.lower().strip()

    if provider == "audd":
        return await _recognize_with_audd(audio_bytes)
    if provider == "acrcloud":
        return await _recognize_with_acrcloud(audio_bytes)

    if provider in ("auto", "", None):
        errors = []
        try:
            return await _recognize_with_audd(audio_bytes)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"AudD: {exc}")

        try:
            return await _recognize_with_acrcloud(audio_bytes)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"ACRCloud: {exc}")

        raise RecognitionError("No recognition provider succeeded. " + " | ".join(errors))

    raise RecognitionError(f"Unknown recognition provider: {provider}")
