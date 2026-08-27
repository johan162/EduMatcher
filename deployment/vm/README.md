# EduMatcher VM Runtime Pipeline

This folder contains a reproducible VM provisioning pipeline for a pinned EduMatcher PyPI release.

## Files in this directory

- `curl_setup_vm.sh` is the repository-free entry point. Run it with `curl | bash` when the host does not have an EduMatcher checkout. It downloads the runtime VM scripts for the selected branch or tag and forwards the remaining arguments to `build_multipass_vm.sh`.
- `build_multipass_vm.sh` creates a small, ready-to-use EduMatcher runtime VM. Use it from a repository checkout for a pinned PyPI release or with `--dev` to install the current wheel from `dist/`. It also creates the sample session and an optional clean snapshot.
- `install_edumatcher_runtime.sh` is the in-VM runtime installer used by `build_multipass_vm.sh`. It creates `/opt/edumatcher/.venv`, installs the requested EduMatcher version or wheel, and links the `pm-*` commands into `/usr/local/bin`. Run it directly only when reprovisioning an existing VM.
- `mkdevnode.sh` creates a larger development workstation VM from a repository checkout. Use it when the node needs SSH access and the development tools checked by `scripts/verify_setup.sh`; it is not a replacement for the runtime VM or the curl bootstrap path.

The two VM creation scripts intentionally serve different purposes: use `build_multipass_vm.sh` for a lightweight runtime or demo image, and use `mkdevnode.sh` for a repository-oriented development node.

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
curl -fsSL https://raw.githubusercontent.com/johan162/EduMatcher/main/deployment/vm/curl_setup_vm.sh | bash -s -- --version 0.7.1 --snapshot
```

Optional environment overrides for custom forks/branches:

```bash
REPO_OWNER=<owner> REPO_NAME=<repo> REPO_REF=<ref> \
curl -fsSL https://raw.githubusercontent.com/<owner>/<repo>/<ref>/deployment/vm/curl_setup_vm.sh | bash -s -- [build options]
```

## Build a VM with pinned EduMatcher version

From repository root:

```bash
./deployment/vm/build_multipass_vm.sh --name edumatcher-016 --version 0.16.0 --snapshot
```

## Build a VM with the current development wheel file

From repository root:

```bash
./deployment/vm/build_multipass_vm.sh --name edumatcher-dev --dev --snapshot
```

Optional flags:

- --image lts
- --cpus 2
- --memory 2G
- --disk 12G
- --snapshot-name clean-runtime

## Enter and use the VM

Open a shell:

multipass shell edumatcher-016

Verify links:

ls -1 /usr/local/bin/pm-*

Start a session:

mkdir -p ~/session
cd ~/session
pm-engine --verbose

Open additional host terminals and attach to the same VM for other processes:

multipass shell edumatcher-016

Then run, for example:

pm-audit --terminal
pm-clearing
pm-viewer --symbol AAPL
pm-gateway --id TRADER01

## Upgrade to a new EduMatcher release

Rebuild with a new version pin:

./deployment/vm/build_multipass_vm.sh --name edumatcher-016--version 0.16.0 --snapshot

Or reprovision an existing VM manually:

multipass transfer deployment/vm/install_edumatcher_runtime.sh edumatcher-016:/tmp/install_edumatcher_runtime.sh
multipass exec edumatcher-016 -- sudo chmod +x /tmp/install_edumatcher_runtime.sh
multipass exec edumatcher-016 -- sudo /tmp/install_edumatcher_runtime.sh --version 0.16.0 
