#!/usr/bin/env bash
# PID 1 of the EduMatcher container.
#
#   1. prepare the (bind-mounted) data directory
#   2. optionally start sshd
#   3. start the pm-opctl-cli process profile
#   4. stay alive until the container is stopped, then stop the profile

set -euo pipefail

DATA_DIR="${EDUMATCHER_DATA_DIR:-/data}"
CONFIG="${EM_CONFIG:-three-basic}"
CONFIG_FILE="${EM_CONFIG_FILE:-}"
PROFILE="${EM_PROFILE:-default}"
CONFIG_STAMP="${DATA_DIR}/.container-config"

log() { printf '==> %s\n' "$*"; }

setup_data_dir() {
    mkdir -p "${DATA_DIR}"
    # An engine configuration supplied as a file wins over the example name.
    # pm-config-deploy overwrites unconditionally, so there is no stamp to
    # keep: the file mounted now is the configuration that runs now.
    if [ -n "${CONFIG_FILE}" ]; then
        log "deploying engine config from ${CONFIG_FILE}"
        pm-setup --no-config
        pm-config-deploy "${CONFIG_FILE}"
        rm -f "${CONFIG_STAMP}"
        return
    fi
    # pm-setup keeps an already-deployed configuration, which is what you want
    # across restarts — but not when EM_CONFIG now names a different example
    # than the one this data directory was built from.
    if [ -f "${CONFIG_STAMP}" ] && [ "$(cat "${CONFIG_STAMP}")" != "${CONFIG}" ]; then
        log "engine config changed: $(cat "${CONFIG_STAMP}") -> ${CONFIG} (redeploying)"
        pm-setup --config "${CONFIG}" --force
    else
        pm-setup --config "${CONFIG}"
    fi
    printf '%s\n' "${CONFIG}" > "${CONFIG_STAMP}"
}

# Inside a container the network namespace is the isolation boundary, and the
# compose BIND_ADDR (127.0.0.1 by default) decides what reaches the host. A
# gateway bound to 127.0.0.1 is therefore unreachable from a sibling container
# for no benefit — it is what stops terminal-gui from opening its CALF feed to
# pm-md-gwy on 5570. Rewrite loopback binds and recompile, so the deployed
# artifact keeps describing what the processes actually do.
#
# 'bind_address' and 'host' are the only two bind keys in the schema; nothing
# in engine_config.yaml uses either to mean "connect to".
LOOPBACK_BIND_RE='^([[:space:]]*(bind_address|host):[[:space:]]*)127\.0\.0\.1[[:space:]]*$'

open_gateway_binds() {
    local source="${DATA_DIR}/ref_data/engine_config.yaml"
    [ -f "${source}" ] || return 0
    grep -qE "${LOOPBACK_BIND_RE}" "${source}" || return 0
    log "rewriting loopback gateway binds to 0.0.0.0 (the container namespace is the boundary)"
    sed -i -E "s/${LOOPBACK_BIND_RE}/\10.0.0.0/" "${source}"
    pm-config-deploy "${source}"
}

start_sshd() {
    # Host keys live in the data directory so they survive `make down`; without
    # that, every recreated container would trip the client's known_hosts.
    mkdir -p /run/sshd /root/.ssh "${DATA_DIR}/ssh-hostkeys"
    if ls "${DATA_DIR}"/ssh-hostkeys/ssh_host_* >/dev/null 2>&1; then
        cp -a "${DATA_DIR}"/ssh-hostkeys/ssh_host_* /etc/ssh/
    else
        ssh-keygen -A
        cp -a /etc/ssh/ssh_host_* "${DATA_DIR}/ssh-hostkeys/"
    fi
    chmod 600 /etc/ssh/ssh_host_*_key

    # The keys are mounted read-only from the host; copying them in is what
    # gives them the root ownership and 0600 mode sshd insists on.
    if [ -s /run/host-authorized-keys ]; then
        install -m 600 -o root -g root /run/host-authorized-keys /root/.ssh/authorized_keys
        log "sshd starting on port 22 with $(wc -l < /root/.ssh/authorized_keys) authorized key(s)"
    else
        log "sshd starting on port 22 but no authorized keys were mounted — logins will fail"
    fi
    /usr/sbin/sshd -e
}

shutdown() {
    log "stopping profile '${PROFILE}'"
    pm-opctl-cli stop || true
    exit 0
}

setup_data_dir
open_gateway_binds

if [ "${EM_SSH:-0}" = "1" ]; then
    start_sshd
fi

log "starting profile '${PROFILE}'"
pm-opctl-cli start "${PROFILE}"
pm-opctl-cli list --no-restart || true

trap shutdown TERM INT

log "EduMatcher is up — attach with 'make shell'"
sleep infinity & wait $!
