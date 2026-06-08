"""RFC 3161 timestamp service — offline tests (no live TSA).

Exercises request construction, token verification, message-imprint binding, and
the fail-loud paths, using a locally-synthesized token and an injected HTTP
transport so no network is required.
"""
import hashlib
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("DATABASE_URL", "sqlite://")

from asn1crypto import algos, cms, core, tsp  # noqa: E402

from ingest.services.timestamp_service import (  # noqa: E402
    TimestampError, build_timestamp_request, request_timestamp, verify_timestamp,
)

DIGEST = hashlib.sha256(b"custody-root").digest()


def _fake_token(digest: bytes, serial: int = 42) -> bytes:
    """Build a minimal RFC 3161 token (TSTInfo wrapped in CMS) for `digest`.

    Not CA-signed — enough to exercise parsing + imprint verification offline.
    """
    tst_info = tsp.TSTInfo({
        "version": "v1",
        "policy": "1.2.3.4.5",
        "message_imprint": tsp.MessageImprint({
            "hash_algorithm": algos.DigestAlgorithm({"algorithm": "sha256"}),
            "hashed_message": core.OctetString(digest),
        }),
        "serial_number": serial,
        "gen_time": datetime(2026, 6, 8, 12, 0, 0, tzinfo=timezone.utc),
    })
    signed = cms.SignedData({
        "version": "v3",
        "digest_algorithms": [algos.DigestAlgorithm({"algorithm": "sha256"})],
        "encap_content_info": cms.EncapsulatedContentInfo({
            "content_type": "tst_info",
            "content": core.ParsableOctetString(tst_info.dump()),
        }),
        "certificates": [],
        "signer_infos": [],
    })
    return cms.ContentInfo({"content_type": "signed_data", "content": signed}).dump()


def _granted_response(digest: bytes) -> bytes:
    token = cms.ContentInfo.load(_fake_token(digest))
    return tsp.TimeStampResp({
        "status": tsp.PKIStatusInfo({"status": "granted"}),
        "time_stamp_token": token,
    }).dump()


def _rejected_response() -> bytes:
    # TimeStampResp ::= SEQ { PKIStatusInfo ::= SEQ { status INTEGER=2 } }, no token.
    return bytes([0x30, 0x05, 0x30, 0x03, 0x02, 0x01, 0x02])


# -- request construction --------------------------------------------------
def test_build_request_roundtrips_imprint():
    der = build_timestamp_request(DIGEST)
    req = tsp.TimeStampReq.load(der)
    assert req["message_imprint"]["hashed_message"].native == DIGEST
    assert req["message_imprint"]["hash_algorithm"]["algorithm"].native == "sha256"


def test_build_request_rejects_wrong_digest_length():
    with pytest.raises(TimestampError, match="32 bytes"):
        build_timestamp_request(b"short")


# -- verification ----------------------------------------------------------
def test_verify_accepts_matching_imprint():
    info = verify_timestamp(_fake_token(DIGEST), DIGEST)
    assert info.serial_number == 42
    assert info.digest_hex == DIGEST.hex()
    assert info.gen_time.startswith("2026-06-08")


def test_verify_rejects_mismatched_imprint():
    other = hashlib.sha256(b"different").digest()
    with pytest.raises(TimestampError, match="imprint mismatch"):
        verify_timestamp(_fake_token(DIGEST), other)


# -- request_timestamp orchestration (injected transport) ------------------
def test_request_timestamp_success_via_injected_poster():
    def poster(url, der, timeout):
        return _granted_response(DIGEST)
    token = request_timestamp(DIGEST, tsa_url="https://tsa.example/tsr", poster=poster)
    assert token.serial_number == 42
    assert token.tsa_url == "https://tsa.example/tsr"
    assert token.token_b64()


def test_request_timestamp_network_failure_is_loud():
    def poster(url, der, timeout):
        raise ConnectionError("network down")
    with pytest.raises(TimestampError, match="failed"):
        request_timestamp(DIGEST, poster=poster)


def test_request_timestamp_tsa_rejection_is_loud():
    def poster(url, der, timeout):
        return _rejected_response()
    with pytest.raises(TimestampError, match="rejected"):
        request_timestamp(DIGEST, poster=poster)


def test_request_timestamp_imprint_tampering_is_caught():
    # TSA returns a token for a DIFFERENT digest than we asked for.
    def poster(url, der, timeout):
        return _granted_response(hashlib.sha256(b"evil").digest())
    with pytest.raises(TimestampError, match="imprint mismatch"):
        request_timestamp(DIGEST, poster=poster)
