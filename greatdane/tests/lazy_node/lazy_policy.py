# Mirrors the Dane lazy-node contract in
# browser/components/greatdane/GreatDANE.sys.mjs and
# security/manager/ssl/SSLServerCertVerification.cpp.
# Keep these constants in sync. No Firefox runtime required.

import hashlib
import time

# Keeper/lazy-node: confirmed flags/env. Passed only when the pref is on.
# Other tunables (--lazy-wait-ms, cache caps, TTLs) stay at node defaults.
LAZY_NODE_CLI_FLAG = "--lazy"
LAZY_NODE_ENV_NAME = "GREATDANE_NODE_LAZY"
LAZY_CACHE_DIR_CLI_FLAG = "--lazy-cache-dir"
LAZY_CACHE_DIR_ENV_NAME = "GREATDANE_NODE_LAZY_CACHE_DIR"

# RFC 8914: 14 = Not Ready (fetch in flight); 22 = fetch failed, retrying.
# Both are retryable loading. Plain SERVFAIL without these codes is not.
LAZY_LOADING_EDE = 14
LAZY_FETCH_FAILED_EDE = 22
LAZY_LOADING_EDES = (LAZY_LOADING_EDE, LAZY_FETCH_FAILED_EDE)
TLSA_STATUS_LOADING = "loading"
DEFAULT_LAZY_TIMEOUT_SEC = 10
DEFAULT_LAZY_RETRY_MS = 1000


def lazy_node_args(data_dir, enabled=True):
    """CLI args Dane passes when launching the node (mirrors _lazyArgs)."""
    if not enabled:
        return []
    return [LAZY_NODE_CLI_FLAG, LAZY_CACHE_DIR_CLI_FLAG, data_dir]


def lazy_node_env(data_dir, enabled=True):
    """Env Dane appends on spawn when the lazy pref is on."""
    if not enabled:
        return {}
    return {
        LAZY_NODE_ENV_NAME: "1",
        LAZY_CACHE_DIR_ENV_NAME: data_dir,
    }

RCODE_NOERROR = 0
RCODE_SERVFAIL = 2
RCODE_NXDOMAIN = 3

MATCH = "match"
FAIL = "fail"
LOADING_TIMEOUT = "loading_timeout"
UNOWNED = "unowned"
NO_TLSA = "no_tlsa"
BAD_RECORD = "bad_record"


def is_lazy_loading_ede(ede):
    try:
        return int(ede) in LAZY_LOADING_EDES
    except (TypeError, ValueError):
        return False


def is_lazy_loading_status(body, loading_edes=LAZY_LOADING_EDES):
    """True when the node is still fetching this name's zone.

    A loading signal must never be classified as NXDOMAIN, no_tlsa, or a
    TLSA/cert failure. Plain SERVFAIL without EDE 14/22 is False.
    """
    if not isinstance(body, dict):
        return False
    if body.get("status") == TLSA_STATUS_LOADING:
        return True
    rcode = body.get("rcode")
    servfail = rcode in (2, "2", "SERVFAIL", RCODE_SERVFAIL)
    try:
        ede = int(body.get("ede"))
    except (TypeError, ValueError):
        return False
    return servfail and ede in tuple(loading_edes)


def is_lazy_loading_dns(rcode, ede, loading_edes=LAZY_LOADING_EDES):
    """Raw dnsd contract: SERVFAIL + EDE 14 or 22 is loading."""
    try:
        ede = int(ede)
    except (TypeError, ValueError):
        return False
    return rcode in (RCODE_SERVFAIL, 2, "SERVFAIL") and ede in tuple(loading_edes)


def is_proxy_loading(http_status, headers):
    """Cold CONNECT: 503 + X-GreatDANE-Status: loading (Retry-After: 1)."""
    if not headers:
        return False
    # Header names are case-insensitive
    norm = {str(k).lower(): str(v).strip() for k, v in headers.items()}
    return norm.get("x-greatdane-status", "").lower() == "loading"


def lazy_retry_ms(body, budget_ms):
    n = DEFAULT_LAZY_RETRY_MS
    try:
        v = int(body.get("retry_ms"))
        if v >= 1:
            n = v
    except (TypeError, ValueError, AttributeError):
        pass
    if budget_ms and budget_ms > 0 and n > budget_ms:
        n = budget_ms
    return max(1, n)


def loading_retry_sec(retry_after=None, retry_ms=None, cap=DEFAULT_LAZY_TIMEOUT_SEC):
    if retry_ms is not None:
        try:
            ms = float(retry_ms)
            if ms >= 1:
                sec = max(1, int((ms + 999) // 1000))  # ceil
            else:
                sec = 1
        except (TypeError, ValueError):
            sec = 1
    elif retry_after is not None:
        try:
            sec = int(retry_after)
        except (TypeError, ValueError):
            sec = 1
    else:
        sec = 1
    if cap < 1:
        cap = DEFAULT_LAZY_TIMEOUT_SEC
    if sec > cap:
        sec = cap
    if sec < 1:
        sec = 1
    return sec


def classify_chain_failure(tlsa, tls_fail=None, block=None, proxy_loading=False):
    """Same decision as GreatDANEAbout.classifyChainFailure."""
    if block:
        return block
    if proxy_loading:
        return "GD_ZONE_LOADING"
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
    # Final only when the node returns this status (after 2 peers).
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
                  loading_edes=LAZY_LOADING_EDES, clock=time.monotonic, sleep=time.sleep):
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
            if is_lazy_loading_status(body, loading_edes=loading_edes):
                saw_loading = True
                wait = lazy_retry_ms(body, int(left * 1000)) / 1000.0
                if wait > left:
                    wait = left
                if wait > 0:
                    sleep(wait)
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
