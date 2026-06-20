# EduMatcher VM Runtime Pipeline

This folder contains a reproducible VM provisioning pipeline for a pinned EduMatcher PyPI release.

## What this pipeline guarantees

- Installs a selected EduMatcher version from PyPI
- Uses a dedicated runtime virtual environment at /opt/edumatcher/.venv
- Discovers all installed pm-* console commands from the installed package metadata
- Links every discovered pm-* command into /usr/local/bin

## Why this uses pip in a venv and not pipx

For this VM image workflow, pip in a dedicated virtual environment is preferred because:

- /usr/local/bin symlinks are a hard requirement
- service and operator paths are deterministic and system-wide
- ownership and upgrade behavior are controlled centrally

pipx is excellent for per-user workstation installs, but less predictable for a system image where all users should see the same /usr/local/bin commands.

## Prerequisites on host machine

- multipass installed
- enough local resources for a VM image

## Build without cloning the repository

Run directly from GitHub with curl:

```bash
curl -fsSL https://raw.githubusercontent.com/johan162/EduMatcher/main/vm/curl_setup_vm.sh | bash -s -- --version 0.7.1 --snapshot
```

Optional environment overrides for custom forks/branches:

```bash
REPO_OWNER=<owner> REPO_NAME=<repo> REPO_REF=<ref> \
curl -fsSL https://raw.githubusercontent.com/<owner>/<repo>/<ref>/vm/curl_setup_vm.sh | bash -s -- [build options]
```

## Build a VM with pinned EduMatcher version

From repository root:

./vm/build_multipass_vm.sh --name edumatcher-071 --version 0.7.1 --snapshot

Optional flags:

- --image lts
- --cpus 2
- --memory 2G
- --disk 12G
- --snapshot-name clean-runtime

## Enter and use the VM

Open a shell:

multipass shell edumatcher-071

Verify links:

ls -1 /usr/local/bin/pm-*

Start a session:

mkdir -p ~/session
cd ~/session
pm-setup
pm-engine --verbose

Open additional host terminals and attach to the same VM for other processes:

multipass shell edumatcher-071

Then run, for example:

pm-audit --terminal
pm-clearing
pm-viewer --symbol AAPL
pm-gateway --id TRADER01

## Upgrade to a new EduMatcher release

Rebuild with a new version pin:

./vm/build_multipass_vm.sh --name edumatcher-072 --version 0.7.2 --snapshot

Or reprovision an existing VM manually:

multipass transfer vm/install_edumatcher_runtime.sh edumatcher-071:/tmp/install_edumatcher_runtime.sh
multipass exec edumatcher-071 -- sudo chmod +x /tmp/install_edumatcher_runtime.sh
multipass exec edumatcher-071 -- sudo /tmp/install_edumatcher_runtime.sh --version 0.7.2
