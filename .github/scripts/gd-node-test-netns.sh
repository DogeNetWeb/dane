#!/usr/bin/env bash
# Run greatdane-node's gd_node_test.sh in a root-made private network
# namespace on a CI runner, as the calling (non-root) user, with:
#   - built-in seeds disabled: greatdane-node has no flag or env to turn
#     off its built-in seed list (the app seeds, the mesh dial list and
#     the chain's DNS seeds are compiled in and all are hostnames, and
#     --seeds only prepends candidates). Inside the namespace,
#     /etc/nsswitch.conf has "hosts: files" and /etc/hosts holds only
#     localhost, so every seed lookup fails at once with no DNS query,
#     and a fresh --data has no cached peers, so nothing is dialed;
#   - only loopback: the namespace has just lo. A default route via lo
#     makes any non-loopback connect produce a packet, so the guard can
#     count it, and OUTPUT accepts only loopback destinations;
#   - an egress guard that FAILS on any attempt, even a blocked one:
#     iptables/ip6tables counters for non-loopback destinations and for
#     DNS (53/853, any destination, loopback included), plus an ss sample
#     of non-loopback sockets (SYN-SENT included). Addresses are never
#     printed. A canary run first proves the counters see attempts.
#
#   gd-node-test-netns.sh <greatdane-node> <gd_node_test.sh>
set -euo pipefail
export PATH="${PATH}:/usr/sbin:/sbin"
NODE=$(readlink -f "$1")
TEST=$(readlink -f "$2")
[ -x "$NODE" ] && [ -f "$TEST" ] || { echo "usage: $0 <greatdane-node> <gd_node_test.sh>" >&2; exit 2; }
for c in ip iptables ip6tables ss setpriv python3; do
  command -v "$c" >/dev/null || { echo "gd-node-test-netns: missing $c" >&2; exit 1; }
done
sudo -n true

NS="gdci-$$"
ETC="/etc/netns/${NS}"
WORK=$(mktemp -d "${RUNNER_TEMP:-/tmp}/gd-netns.XXXXXX")
SS_LOG="${WORK}/ss-guard.log"
: > "${SS_LOG}"
SS_PID=
cleanup() {
  if [ -n "${SS_PID}" ]; then kill "${SS_PID}" 2>/dev/null || true; wait "${SS_PID}" 2>/dev/null || true; fi
  sudo -n ip netns del "${NS}" 2>/dev/null || true
  sudo -n rm -rf "${ETC}"
  rm -rf "${WORK}"
}
trap cleanup EXIT INT TERM

nsx() { sudo -n ip netns exec "${NS}" "$@"; }

# Namespace-local resolver config (ip netns exec bind-mounts these over /etc).
sudo -n mkdir -p "${ETC}"
printf '127.0.0.1\tlocalhost\n::1\tlocalhost ip6-localhost ip6-loopback\n' | sudo -n tee "${ETC}/hosts" >/dev/null
sed -E 's/^hosts:.*/hosts: files/' /etc/nsswitch.conf | sudo -n tee "${ETC}/nsswitch.conf" >/dev/null
grep -q '^hosts: files$' "${ETC}/nsswitch.conf" || echo 'hosts: files' | sudo -n tee -a "${ETC}/nsswitch.conf" >/dev/null
printf 'nameserver 127.0.0.1\noptions timeout:1 attempts:1\n' | sudo -n tee "${ETC}/resolv.conf" >/dev/null

sudo -n ip netns add "${NS}"
nsx ip link set lo up
nsx ip route add default dev lo
nsx ip -6 route add default dev lo

install_chains() {
  local ipt=$1 lo=$2
  nsx "${ipt}" -N GDCI_DNS
  nsx "${ipt}" -A GDCI_DNS -j REJECT
  nsx "${ipt}" -N GDCI_EGRESS
  nsx "${ipt}" -A GDCI_EGRESS -j REJECT
  nsx "${ipt}" -N GDCI_INGRESS
  nsx "${ipt}" -A GDCI_INGRESS -j DROP
  # DNS is counted (and refused) before the loopback accept: none expected.
  nsx "${ipt}" -A OUTPUT -p udp --dport 53 -j GDCI_DNS
  nsx "${ipt}" -A OUTPUT -p tcp --dport 53 -j GDCI_DNS
  nsx "${ipt}" -A OUTPUT -p tcp --dport 853 -j GDCI_DNS
  nsx "${ipt}" -A OUTPUT -o lo -d "${lo}" -j ACCEPT
  nsx "${ipt}" -A OUTPUT -j GDCI_EGRESS
  nsx "${ipt}" -A INPUT -i lo -s "${lo}" -j ACCEPT
  nsx "${ipt}" -A INPUT -j GDCI_INGRESS
}
install_chains iptables 127.0.0.0/8
install_chains ip6tables ::1/128

# Packets that hit a chain's terminal rule (the chain jump count).
chain_hits() {
  local ipt=$1 chain=$2
  nsx "${ipt}" -nvx -L "${chain}" | awk 'NR > 2 { s += $1 } END { print s + 0 }'
}
counts() {
  echo "$(( $(chain_hits iptables GDCI_EGRESS) + $(chain_hits ip6tables GDCI_EGRESS) ))" \
       "$(( $(chain_hits iptables GDCI_DNS) + $(chain_hits ip6tables GDCI_DNS) ))" \
       "$(( $(chain_hits iptables GDCI_INGRESS) + $(chain_hits ip6tables GDCI_INGRESS) ))"
}
as_user() {
  nsx setpriv --reuid "$(id -u)" --regid "$(id -g)" --init-groups \
    env -i PATH="${PATH}" HOME="${GD_HOME}" TMPDIR="${GD_TMP}" \
    XDG_DATA_HOME="${GD_HOME}/.local/share" XDG_CONFIG_HOME="${GD_HOME}/.config" \
    XDG_CACHE_HOME="${GD_HOME}/.cache" LANG=C.UTF-8 "$@"
}
GD_HOME="${WORK}/home"
GD_TMP="${WORK}/tmp"
mkdir -p "${GD_HOME}/.local/share" "${GD_HOME}/.config" "${GD_HOME}/.cache" "${GD_TMP}"

# Canary: the guard must see a blocked TCP attempt, a blocked UDP DNS
# query, and a name lookup must fail without any DNS query. Documentation
# addresses only (RFC 5737 / 3849), and the reserved .invalid name.
as_user python3 - <<'PY'
import socket, sys
fails = 0
for fam, addr in ((socket.AF_INET, ("198.51.100.7", 9)), (socket.AF_INET6, ("2001:db8::7", 9))):
    s = socket.socket(fam, socket.SOCK_STREAM); s.settimeout(3)
    try:
        s.connect(addr); print("canary: TCP connect unexpectedly succeeded"); fails += 1
    except OSError:
        pass
    finally:
        s.close()
u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
try:
    u.sendto(b"\0" * 12, ("198.51.100.7", 53))
except OSError:
    pass
u.close()
sys.exit(1 if fails else 0)
PY
read -r c_out c_dns c_in < <(counts)
echo "canary: egress hits=${c_out} (want >= 2), DNS hits=${c_dns} (want >= 1)"
[ "${c_out}" -ge 2 ] && [ "${c_dns}" -ge 1 ] || { echo "CI guard canary failed: the counters did not see blocked attempts"; exit 1; }
nsx iptables -Z; nsx ip6tables -Z
as_user python3 -c '
import socket, sys
try:
    socket.getaddrinfo("gdci-canary.invalid", 80)
    print("canary: a non-local name resolved"); sys.exit(1)
except socket.gaierror:
    pass
socket.getaddrinfo("localhost", 80)
'
read -r c_out c_dns c_in < <(counts)
echo "canary: name lookup fails with DNS hits=${c_dns} (want 0), egress hits=${c_out} (want 0)"
[ "${c_dns}" -eq 0 ] && [ "${c_out}" -eq 0 ] || { echo "CI guard canary failed: name lookups reach DNS"; exit 1; }
nsx iptables -Z; nsx ip6tables -Z

# Socket sampler: any non-listening socket with a non-loopback peer.
(
  while :; do
    nsx ss -H -tuan 2>/dev/null | awk '
      { st = $2; peer = $6 }
      st == "LISTEN" || st == "UNCONN" { next }
      peer ~ /^127\./ || peer ~ /^\[::1\]:/ || peer ~ /^\[::ffff:127\./ || peer ~ /^\*:/ { next }
      peer == "0.0.0.0:*" || peer == "[::]:*" || peer == "*" { next }
      { n = split(peer, a, ":"); print "NONLOOPBACK " $1 " " st " port " a[n] }
    ' >> "${SS_LOG}" || true
    sleep 0.2
  done
) &
SS_PID=$!

echo "gd_node_test mode: private netns (lo only), built-in seeds unresolvable (hosts: files)"
set +e
( cd "$(dirname "${TEST}")" && as_user sh "${TEST}" "${NODE}" )
test_rc=$?
set -e
sleep 0.5
kill "${SS_PID}" 2>/dev/null || true; wait "${SS_PID}" 2>/dev/null || true; SS_PID=

read -r n_out n_dns n_in < <(counts)
n_ss=$(sort -u "${SS_LOG}" | wc -l)
echo "CI guard: non-loopback outbound attempts=${n_out} DNS attempts=${n_dns} non-loopback inbound=${n_in} non-loopback sockets seen=${n_ss}"
if [ "${n_out}" -ne 0 ] || [ "${n_dns}" -ne 0 ] || [ "${n_in}" -ne 0 ] || [ "${n_ss}" -ne 0 ]; then
  echo "CI guard FAILED: greatdane-node attempted non-loopback or DNS traffic (addresses not shown)"
  sort -u "${SS_LOG}" | head -20
  exit 1
fi
echo "CI guard: zero outbound attempts"
exit "${test_rc}"
