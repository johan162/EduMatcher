#!/bin/bash
# run.sh NAME [VAR=VALUE ...]: the container entrypoint against ./NAME/data, in the background.
N=$1; shift
mkdir -p /home/claude/aisim/$N
cd /home/claude/em
env PATH=/home/claude/emv/bin:$PATH EDUMATCHER_DATA_DIR=/home/claude/aisim/$N/data \
    TZ=Europe/Stockholm EM_CONFIG=s300-sim EM_PROFILE=ai-sim EM_RESTART_DEAD=1 EM_SPEED=1 "$@" \
    setsid nohup bash deployment/docker/entrypoint.sh > /home/claude/aisim/$N/entrypoint.log 2>&1 &
echo $! > /home/claude/aisim/$N/entrypoint.pid
