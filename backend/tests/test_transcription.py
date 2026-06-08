"""Voice-note transcription tests — DI stub transcriber, no model required."""
import hashlib
import os
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("DATABASE_URL", "sqlite://")

from sqlmodel import Session, SQLModel, create_engine, select  # noqa: E402

import db_setup  # noqa: E402,F401
from db_setup import Media, Run, Transcript, User  # noqa: E402
from ingest.services.audit_service import AuditService  # noqa: E402
from ingest.services.transcription_service import (  # noqa: E402
    TranscriptionService, default_whisper_transcriber,
)


@pytest.fixture()
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


@pytest.fixture()
def run_id(session):
    u = User(username="IO", email="io@x.gov", password_hash="x")
    session.add(u); session.commit(); session.refresh(u)
    r = Run(user_id=u.id, ufdr_file_name="c.ufdr", status="complete")
    session.add(r); session.commit(); session.refresh(r)
    session.add_all([
        Media(run_id=r.id, original_path="/d/voice1.amr", storage_path="/s/voice1.amr",
              media_type="audio/amr"),
        Media(run_id=r.id, original_path="/d/pic.jpg", storage_path="/s/pic.jpg",
              media_type="image/jpeg"),  # not audio — must be skipped
        Media(run_id=r.id, original_path="/d/voice2.opus", storage_path="/s/voice2.opus",
              media_type=None),  # detected by extension
    ])
    session.commit()
    return r.id


def _stub(text="the package arrives tuesday at the docks"):
    def transcriber(path, model_size):
        # Vary text by file so each transcript is distinct + deterministic.
        return {"text": f"{text} [{Path(path).name}]", "language": "en",
                "model": f"stub/{model_size}"}
    return transcriber


def test_only_audio_is_transcribed(session, run_id):
    svc = TranscriptionService(transcriber=_stub())
    audio = svc.audio_media(session, run_id)
    assert {m.original_path for m in audio} == {"/d/voice1.amr", "/d/voice2.opus"}


def test_transcribe_persists_and_audits(session, run_id):
    audit = AuditService()
    svc = TranscriptionService(transcriber=_stub())
    results = svc.transcribe_run(session, run_id, audit_service=audit)

    assert len(results) == 2
    stored = session.exec(select(Transcript)).all()
    assert len(stored) == 2
    for r in results:
        assert r.transcript_hash == hashlib.sha256(r.text.encode()).hexdigest()
        assert r.model == "stub/base"
        assert "docks" in r.text

    # Each transcription recorded as an audit event with the required fields.
    chain = audit.export(session)
    tevents = [e for e in chain["events"] if e["event_type"] == "transcription"]
    assert len(tevents) == 2
    assert all({"audio_file_id", "model", "transcript_hash"} <= set(e["payload"]) for e in tevents)
    assert chain["verified"] is True


def test_retranscription_is_idempotent(session, run_id):
    svc = TranscriptionService(transcriber=_stub())
    svc.transcribe_run(session, run_id)
    svc.transcribe_run(session, run_id)
    assert len(session.exec(select(Transcript)).all()) == 2  # replaced, not duplicated


def test_meili_indexing_called(session, run_id):
    class FakeIndex:
        def __init__(self): self.docs = []
        def add_documents(self, docs): self.docs.extend(docs)

    class FakeMeili:
        def __init__(self): self.idx = FakeIndex()
        def index(self, name):
            assert name == "transcripts"
            return self.idx

    meili = FakeMeili()
    TranscriptionService(transcriber=_stub()).transcribe_run(session, run_id, meili_client=meili)
    assert len(meili.idx.docs) == 2
    assert all("text" in d for d in meili.idx.docs)


def test_nonexistent_run_fails_loud(session):
    import uuid as _uuid
    with pytest.raises(ValueError, match="does not exist"):
        TranscriptionService(transcriber=_stub()).transcribe_run(session, _uuid.uuid4())


def test_default_transcriber_fails_loud_without_model():
    pytest.importorskip  # noqa
    try:
        import faster_whisper  # noqa: F401
        pytest.skip("faster-whisper is installed; cannot test the missing-package path")
    except ImportError:
        with pytest.raises(RuntimeError, match="faster-whisper is not installed"):
            default_whisper_transcriber("/nonexistent.wav")
