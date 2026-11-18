# Mirrors the Dane lazy-node contract in
# browser/components/greatdane/GreatDANE.sys.mjs and
# security/manager/ssl/SSLServerCertVerification.cpp.
# Keep these constants in sync. No Firefox runtime required.

import hashlib
import time

# TODO-KEEPER-FLAG: exact CLI flag or env name is not final.
LAZY_NODE_CLI_FLAG = "--lazy"  # TODO-KEEPER-FLAG
LAZY_NODE_ENV_NAME = "GREATDANE_NODE_LAZY"  # TODO-KEEPER-FLAG

# TODO-KEEPER-EDE: dnsd signals "zone still fetching" as SERVFAIL plus this
# Extended DNS Error code. 0 means not yet assigned: do not treat any EDE as
# loading until this is replaced. Interim HTTP signal is /gd/tlsa status
# "loading" (the node should translate SERVFAIL+EDE into that status).
LAZY_LOADING_EDE = 0  # TODO-KEEPER-EDE
TLSA_STATUS_LOADING = "loading"
DEFAULT_LAZY_TIMEOUT_SEC = 10

RCODE_NOERROR = 0
RCODE_SERVFAIL = 2
RCODE_NXDOMAIN = 3

# Verdicts used by the verifier / interstitial classifier.
MATCH = "match"
FAIL = "fail"  # includes bad TLSA / plain SERVFAIL / unusable record
LOADING_TIMEOUT = "loading_timeout"  # retryable, never a cert/pinning failure
UNOWNED = "unowned"
NO_TLSA = "no_tlsa"
BAD_RECORD = "bad_record"


def is_lazy_loading_status(body, loading_ede=LAZY_LOADING_EDE):
    """True when the node is still fetching this name's zone.

    A loading signal must never be classified as NXDOMAIN, no_tlsa, or a
    TLSA/cert failure. Plain SERVFAIL without the Keeper EDE is False.
    """
    if not isinstance(body, dict):
        return False
    if body.get("status") == TLSA_STATUS_LOADING:
        return True
    if not loading_ede:
        return False
    rcode = body.get("rcode")
    try:
        ede = int(body.get("ede"))
    except (TypeError, ValueError):
        return False
    servfail = rcode in (2, "2", "SERVFAIL", RCODE_SERVFAIL)
    return servfail and ede == loading_ede


def is_lazy_loading_dns(rcode, ede, loading_ede=LAZY_LOADING_EDE):
    """Raw dnsd contract: SERVFAIL + Keeper EDE is loading; plain SERVFAIL is not."""
    if not loading_ede:
        return False
    try:
        ede = int(ede)
    except (TypeError, ValueError):
        return False
    return rcode in (RCODE_SERVFAIL, 2, "SERVFAIL") and ede == loading_ede


def classify_chain_failure(tlsa, tls_fail=None, block=None):
    """Same decision as GreatDANEAbout.classifyChainFailure."""
    if block:
        return block
    if tlsa is None:
        return "GD_NODE_NOT_READY"
    if tlsa == TLSA_STATUS_LOADING:
        return "GD_ZONE_LOADING"
    if tlsa in ("unowned", "bad_name"):
        return "GD_NAME_UNOWNED"
    if tlsa == "no_tlsa":
        return "GD_NO_TLSA"
    if tlsa == "bad_record":
        return "GD_BAD_TLSA"
    if tlsa == "ok":
        return "GD_SITE_UNREACHABLE" if tls_fail is False else "GD_TLS_UNTRUSTED"
    return "GD_TLS_UNTRUSTED"


def _spki_sha256_hex(spki_bytes):
    return hashlib.sha256(spki_bytes).hexdigest()


def verify_body(body, leaf_spki):
    """Definitive /gd/tlsa body vs leaf SPKI (C++ GreatDANEVerifyBody)."""
    if not isinstance(body, dict):
        return FAIL
    if is_lazy_loading_status(body):
        raise ValueError("verify_body called on a loading signal")
    status = body.get("status")
    if status == "unowned" or status == "bad_name":
        return UNOWNED
    if status == "no_tlsa":
        return NO_TLSA
    if status == "bad_record":
        return BAD_RECORD
    if (
        status != "ok"
        or str(body.get("usage")) != "3"
        or str(body.get("selector")) != "1"
        or str(body.get("mtype")) != "1"
    ):
        return FAIL
    want = str(body.get("data") or "").lower()
    if len(want) != 64:
        return FAIL
    got = _spki_sha256_hex(leaf_spki)
    return MATCH if got == want else FAIL


def wait_for_tlsa(fetch, leaf_spki, lazy=True, timeout_sec=DEFAULT_LAZY_TIMEOUT_SEC,
                  loading_ede=LAZY_LOADING_EDE, clock=time.monotonic, sleep=time.sleep):
    """Retry loop matching SSLServerCertVerification.cpp GreatDANEVerify.

    fetch() should return one of:
      ("ok", dict_body)
      ("connect_fail", None)
      ("timeout", None)
      ("bad_response", None)
    """
    if timeout_sec < 1:
        timeout_sec = DEFAULT_LAZY_TIMEOUT_SEC
    if timeout_sec > 60:
        timeout_sec = 60
    deadline = clock() + (timeout_sec if lazy else 5)
    saw_loading = False
    while True:
        left = deadline - clock()
        if left <= 0:
            break
        kind, body = fetch()
        if kind == "ok":
            if is_lazy_loading_status(body, loading_ede=loading_ede):
                saw_loading = True
                sleep(min(0.1, max(0.0, deadline - clock())))
                continue
            return verify_body(body, leaf_spki)
        if kind == "connect_fail":
            if saw_loading:
                sleep(min(0.1, max(0.0, deadline - clock())))
                continue
            return FAIL
        if kind == "timeout" and (lazy or saw_loading):
            saw_loading = True
            sleep(min(0.1, max(0.0, deadline - clock())))
            continue
        if kind == "bad_response" and saw_loading:
            sleep(min(0.1, max(0.0, deadline - clock())))
            continue
        return FAIL
    if saw_loading or lazy:
        return LOADING_TIMEOUT
    return FAIL
