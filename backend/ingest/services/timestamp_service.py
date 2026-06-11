"""RFC 3161 trusted timestamping of the custody root hash.

V2's audit chain is tamper-evident but *locally* signed — anyone trusting it must
trust this server. An RFC 3161 Time-Stamp Authority (TSA) is an independent third
party that cryptographically attests "this digest existed at this UTC instant".
Anchoring the audit-chain head to a TSA token makes the seal **independently
verifiable**: a court can check the token against the TSA's public certificate
without trusting us.

No fallbacks (per project rule + V3 handoff): if the TSA is unreachable or
rejects the request, we raise loudly with the exact reason. We NEVER return a
"pretend it's stamped" result. The caller records the failure reason in the audit
trail before surfacing the error.

The HTTP transport is injectable (`poster`) so the request-building and
response-parsing logic is fully unit-tested offline, without a live TSA.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Callable, Optional

from asn1crypto import algos, cms, core, tsp

# RFC 3161 marks `timeStampToken` OPTIONAL (absent on rejection), but some
# asn1crypto builds omit that flag, which makes a real rejection response
# unparseable. Restore the optional flag so rejections surface cleanly.
for _i, _f in enumerate(tsp.TimeStampResp._fields):
    if _f[0] == "time_stamp_token":
        _opts = dict(_f[2]) if len(_f) > 2 else {}
        _opts["optional"] = True
        tsp.TimeStampResp._fields[_i] = (_f[0], _f[1], _opts)

# freetsa.org is a free, no-auth RFC 3161 issuer. Override with TSA_URL.
DEFAULT_TSA_URL = "https://freetsa.org/tsr"
_GRANTED = {"granted", "granted_with_mods"}

# Type of the injectable HTTP transport: (url, der_request, timeout) -> der_response
Poster = Callable[[str, bytes, float], bytes]


class TimestampError(RuntimeError):
    """Raised loudly when a trusted timestamp cannot be obtained or verified."""


@dataclass
class TimestampToken:
    token_der: bytes
    gen_time: str          # ISO-8601 UTC instant attested by the TSA
    serial_number: int
    policy: Optional[str]
    tsa_url: str
    digest_hex: str        # the digest that was stamped (the custody root)

    def token_b64(self) -> str:
        return base64.b64encode(self.token_der).decode("ascii")


def build_timestamp_request(digest: bytes, hash_algo: str = "sha256",
                            nonce: Optional[int] = None, cert_req: bool = True) -> bytes:
    """Build a DER-encoded RFC 3161 TimeStampReq for `digest`."""
    if hash_algo == "sha256" and len(digest) != 32:
        raise TimestampError(
            f"sha256 message imprint must be 32 bytes, got {len(digest)}")
    req = tsp.TimeStampReq({
        "version": "v1",
        "message_imprint": tsp.MessageImprint({
            "hash_algorithm": algos.DigestAlgorithm({"algorithm": hash_algo}),
            "hashed_message": core.OctetString(digest),
        }),
        "cert_req": cert_req,
    })
    if nonce is not None:
        req["nonce"] = core.Integer(nonce)
    return req.dump()


def _default_poster(url: str, der_request: bytes, timeout: float) -> bytes:
    import requests  # local import so the module loads without network deps
    resp = requests.post(
        url, data=der_request, timeout=timeout,
        headers={"Content-Type": "application/timestamp-query",
                 "Accept": "application/timestamp-reply"},
    )
    resp.raise_for_status()
    return resp.content


def request_timestamp(digest: bytes, tsa_url: str = DEFAULT_TSA_URL,
                      nonce: Optional[int] = None, timeout: float = 15.0,
                      poster: Poster = _default_poster) -> TimestampToken:
    """Obtain a trusted timestamp token over `digest`. Raises loudly on any
    failure (network, TSA rejection, malformed response, imprint mismatch)."""
    der_req = build_timestamp_request(digest, nonce=nonce)
    try:
        der_resp = poster(tsa_url, der_req, timeout)
    except Exception as e:  # network/transport failure — surface the exact cause
        raise TimestampError(f"TSA request to {tsa_url} failed: {e!r}") from e

    try:
        resp = tsp.TimeStampResp.load(der_resp)
    except Exception as e:
        raise TimestampError(f"TSA returned an unparseable response: {e!r}") from e

    status = resp["status"]["status"].native
    if status not in _GRANTED:
        fail_info = None
        try:
            fail_info = resp["status"]["fail_info"].native
        except Exception:
            pass
        raise TimestampError(
            f"TSA {tsa_url} rejected the request: status={status!r} fail_info={fail_info!r}")

    token_ci = resp["time_stamp_token"]
    if token_ci.native is None:
        raise TimestampError(f"TSA {tsa_url} granted but returned no token")

    token_der = token_ci.dump()
    info = verify_timestamp(token_der, digest)   # also confirms imprint matches
    info.tsa_url = tsa_url
    return info


def verify_timestamp(token_der: bytes, digest: bytes) -> TimestampToken:
    """Parse a timestamp token and confirm its message imprint equals `digest`.

    Verifies the binding between the token and the data (the custody root). Full
    X.509 signature-chain validation against the TSA's CA is the verifier's job
    at audit time and is intentionally out of scope here — documented, not faked.
    """
    try:
        ci = cms.ContentInfo.load(token_der)
        signed_data = ci["content"]
        content = signed_data["encap_content_info"]["content"]
        # asn1crypto maps the `tst_info` content type, so the octet string
        # auto-parses to a TSTInfo via `.parsed`; otherwise load the raw bytes.
        parsed = getattr(content, "parsed", None)
        if isinstance(parsed, tsp.TSTInfo):
            tst_info = parsed
        else:
            raw = content.native
            tst_info = raw if isinstance(raw, tsp.TSTInfo) else tsp.TSTInfo.load(raw)
    except Exception as e:
        raise TimestampError(f"could not parse timestamp token: {e!r}") from e

    stamped = tst_info["message_imprint"]["hashed_message"].native
    if stamped != digest:
        raise TimestampError(
            "timestamp token does not match the data: message imprint mismatch")

    policy = None
    try:
        policy = tst_info["policy"].native
    except Exception:
        pass

    return TimestampToken(
        token_der=token_der,
        gen_time=tst_info["gen_time"].native.isoformat(),
        serial_number=int(tst_info["serial_number"].native),
        policy=str(policy) if policy is not None else None,
        tsa_url="",
        digest_hex=digest.hex(),
    )
