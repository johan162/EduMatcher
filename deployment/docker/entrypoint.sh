#!/usr/bin/env bash
# PID 1 of the EduMatcher container.
#
#   1. prepare the (bind-mounted) data directory
#   2. optionally start sshd
#   3. start the pm-opctl-cli process profile
#   4. stay alive until the container is stopped, then stop the profile;
#      with EM_RESTART_DEAD=1, restart dead processes meanwhile

set -euo pipefail

DATA_DIR="${EDUMATCHER_DATA_DIR:-/data}"
CONFIG="${EM_CONFIG:-s10-basic}"
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
    # The company profiles of the s300 tickers (pm-compdb-cli). Built once and
    # never overwritten, so companies added in the container survive restarts.
    if [ "${CONFIG}" = "s300-sim" ] && [ ! -f "${DATA_DIR}/companies.db" ]; then
        log "building the company database"
        pm-compdb-cli --db "${DATA_DIR}/companies.db" init \
            || log "warning: could not build ${DATA_DIR}/companies.db"
    fi
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

if [ "${EM_SSH:-0}" = "1" ]; then
    start_sshd
fi

# Accelerated time: pm-scheduler reads its --speed/--start defaults from the
# environment, which pm-opctl-cli passes on to every process it starts.
if [ -n "${EM_SPEED:-}" ] && [ "${EM_SPEED}" != "1" ]; then
    export EDUMATCHER_SCHEDULER_SPEED="${EM_SPEED}"
    log "accelerated time: x${EM_SPEED}${EM_START:+ from ${EM_START}}"
fi
if [ -n "${EM_START:-}" ]; then
    export EDUMATCHER_SCHEDULER_START="${EM_START}"
fi

log "starting profile '${PROFILE}'"
pm-opctl-cli start "${PROFILE}"
pm-opctl-cli list --no-restart || true

trap shutdown TERM INT

log "EduMatcher is up — attach with 'make shell'"
if [ "${EM_RESTART_DEAD:-0}" = "1" ]; then
    # Long unattended runs: once a minute, restart any process of the profile
    # that has died (a crash, or a bot that started before the engine).
    log "restarting dead processes once a minute (EM_RESTART_DEAD=1)"
    while true; do
        sleep 60 & wait $!
        pm-opctl-cli list --restart 2>&1 | sed -n '/^Restarting:/,$p' | while IFS= read -r line; do
            log "$(date '+%F %T') ${line}"
        done
    done
fi
sleep infinity & wait $!
