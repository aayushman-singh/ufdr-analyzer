"""Voice-note transcription — make audio messages queryable.

UFDR dumps contain audio messages that the text/IR query layer can't see. This
service transcribes audio media (locally, via faster-whisper — no API key),
persists each transcript linked to its source audio, records the transcription
as an audit event (audio_file_id, model, timestamp, transcript_hash), and lets
the caller index transcripts in Meilisearch alongside text.

The transcriber is **injected** (`transcriber`), so the persistence + audit +
indexing orchestration is fully testable without the heavy model. The default
transcriber lazily loads faster-whisper and **fails loudly** if it isn't
installed — never silently skipping audio (which would hide evidence).
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from sqlmodel import Session, select

from db_setup import Media, Run, Transcript

logger = logging.getLogger(__name__)

_AUDIO_EXTS = {".amr", ".3gp", ".m4a", ".mp3", ".ogg", ".opus", ".wav", ".aac", ".flac"}

# transcriber(audio_path, model_size) -> {"text": str, "language": str|None, "model": str}
Transcriber = Callable[[str, str], dict]


@dataclass
class TranscriptResult:
    transcript_id: str
    media_id: str
    model: str
    language: Optional[str]
    text: str
    transcript_hash: str

    def to_dict(self) -> dict:
        return self.__dict__


def _is_audio(media: Media) -> bool:
    if media.media_type and "audio" in media.media_type.lower():
        return True
    path = media.original_path or media.storage_path or ""
    return Path(path).suffix.lower() in _AUDIO_EXTS


def default_whisper_transcriber(audio_path: str, model_size: str = "base") -> dict:
    """faster-whisper transcriber. Fails loudly if the package is absent."""
    try:
        from faster_whisper import WhisperModel
    except ImportError as e:  # explicit, actionable — not a silent skip
        raise RuntimeError(
            "faster-whisper is not installed — cannot transcribe audio. "
            "Install it (`pip install faster-whisper`) or inject a transcriber."
        ) from e
    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    segments, info = model.transcribe(audio_path)
    text = " ".join(seg.text for seg in segments).strip()
    return {"text": text, "language": info.language, "model": f"faster-whisper/{model_size}"}


class TranscriptionService:
    def __init__(self, transcriber: Optional[Transcriber] = None, model_size: str = "base"):
        self._transcriber = transcriber or default_whisper_transcriber
        self._model_size = model_size

    def audio_media(self, session: Session, run_id) -> list[Media]:
        media = session.exec(select(Media).where(Media.run_id == run_id)).all()
        return [m for m in media if _is_audio(m)]

    def transcribe_run(self, session: Session, run_id, audit_service=None,
                       meili_client=None) -> list[TranscriptResult]:
        """Transcribe every audio item in a run; persist + audit each.

        Fails loud on a nonexistent run. Re-transcription replaces prior
        transcripts for the same media (idempotent)."""
        if session.get(Run, run_id) is None:
            raise ValueError(f"run {run_id} does not exist")

        results: list[TranscriptResult] = []
        for media in self.audio_media(session, run_id):
            path = media.storage_path or media.original_path
            if not path:
                raise RuntimeError(f"audio media {media.id} has no path to transcribe")

            out = self._transcriber(path, self._model_size)
            text = out["text"]
            thash = hashlib.sha256(text.encode("utf-8")).hexdigest()

            # Replace any prior transcript for this media (idempotent re-runs).
            for old in session.exec(select(Transcript).where(Transcript.media_id == media.id)).all():
                session.delete(old)

            tr = Transcript(
                run_id=run_id, media_id=media.id, model=out["model"],
                language=out.get("language"), text=text, transcript_hash=thash,
            )
            session.add(tr)
            session.commit()
            session.refresh(tr)

            if audit_service is not None:
                audit_service.record(
                    session, "transcription",
                    payload={"audio_file_id": str(media.id), "model": out["model"],
                             "transcript_hash": thash, "language": out.get("language")},
                    run_id=run_id,
                )

            results.append(TranscriptResult(
                transcript_id=str(tr.id), media_id=str(media.id), model=out["model"],
                language=out.get("language"), text=text, transcript_hash=thash,
            ))

        if meili_client is not None and results:
            self.index_transcripts(meili_client, run_id, results)
        return results

    def index_transcripts(self, meili_client, run_id, results: list[TranscriptResult]) -> None:
        """Index transcripts in Meilisearch alongside text content."""
        docs = [
            {"id": r.transcript_id, "run_id": str(run_id), "media_id": r.media_id,
             "text": r.text, "language": r.language, "model": r.model}
            for r in results
        ]
        meili_client.index("transcripts").add_documents(docs)
