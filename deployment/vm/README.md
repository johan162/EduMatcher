# EduMatcher VM Runtime Pipeline

A reproducible Multipass VM carrying a chosen EduMatcher release, with every
`pm-*` command on the system PATH.

Prefer this over [`../docker/`](../docker/) when you want a real machine to log
into — a workshop image you can snapshot and reset, or an environment where the
processes are started by hand. The container deployment is the better choice
when you want the whole system, web GUIs included, in one command.

## Files in this directory

| File | Purpose |
|---|---|
| `Makefile` | The everyday interface: `make build`, `up`, `shell`, `ssh`, `status`, `restore`, `clean` |
| `mknode.sh` | Creates and provisions the runtime VM. Called by the Makefile; usable directly |
| `install_edumatcher.sh` | The in-VM installer `mknode.sh` runs. Creates `/opt/edumatcher/.venv`, installs the release or wheel, links the `pm-*` commands into `/usr/local/bin` |
| `curl_setup_vm.sh` | Repository-free entry point. Downloads the two scripts above and forwards its arguments to `mknode.sh` |
| `mkupd.sh` | Updates an existing VM to a newer runtime in place |
| `mkdevnode.sh` | A larger *development workstation* VM from a checkout, with the tools `scripts/verify_setup.sh` expects. Not a replacement for the runtime VM |

`mknode.sh` and `mkdevnode.sh` serve different purposes deliberately: the first
builds a lightweight runtime or demo image, the second a repository-oriented
development node.

## What the pipeline guarantees

- Installs a chosen EduMatcher version from PyPI, or a local wheel with `--dev`
- Uses one dedicated runtime virtualenv at `/opt/edumatcher/.venv`
- Discovers every `pm-*` console command from the installed package metadata
- Links each one into `/usr/local/bin`, so all users see the same commands
- Records what was installed in `/opt/edumatcher/EDUMATCHER_VERSION`
- Runs `pm-setup` so the VM has a deployed configuration and can start immediately

### Why pip in a venv rather than pipx

`/usr/local/bin` symlinks are a hard requirement here, operator and service
paths need to be deterministic and system-wide, and ownership and upgrades are
controlled centrally. pipx is excellent for per-user workstation installs but
less predictable for a system image where every user should see the same
commands.

## Prerequisites

Multipass on the host, and enough resources for the VM (4 CPUs, 4 GB RAM and
6 GB of disk by default).

## Build

From a checkout, through the Makefile:

```bash
cd deployment/vm
make build                      # VM named 'ems', current release
make build NAME=ems-026 VERSION=0.26.0
make build DEV=1                # install the wheel from ../../dist
make help                       # every target and variable
```

`make build` records the VM name in `.vm-name`, so later `make shell`,
`make ssh` and `make status` need no arguments.

Without a checkout:

```bash
curl -fsSL https://raw.githubusercontent.com/johan162/EduMatcher/main/deployment/vm/curl_setup_vm.sh \
    | bash -s -- --version 0.26.0
```

For a fork or a branch:

```bash
REPO_OWNER=<owner> REPO_NAME=<repo> REPO_REF=<ref> \
curl -fsSL https://raw.githubusercontent.com/<owner>/<repo>/<ref>/deployment/vm/curl_setup_vm.sh \
    | bash -s -- [options]
```

### `mknode.sh` options

The Makefile passes these through; use them directly when calling the script.

| Option | Default | Description |
|---|---|---|
| `--name <vm-name>` | `ems` | VM instance name |
| `--image <image>` | `lts` | Base Multipass image |
| `--cpus <count>` | `4` | Virtual CPUs |
| `--memory <size>` | `4G` | RAM |
| `--disk <size>` | `6G` | Disk |
| `--version <x.y.z>` | `dev` | PyPI release to install |
| `--dev` | — | Install the local wheel from the repository's `dist/` instead of PyPI. This is the default when no `--version` is given |
| `--snapshot` | already on | Snapshot after provisioning — enabled by default, so this flag only makes that explicit |
| `--snapshot-name <name>` | `clean` | Snapshot name |
| `--ssh-key <path>` | `~/.ssh/<vm-name>_ed25519` | Private key whose public half is installed for passwordless login |
| `--help` | — | Usage |

!!! note
    Because the default is `--dev`, a bare `mknode.sh` needs a wheel in the
    repository's `dist/` — run `poetry build` first, or pass `--version`.

## Use the VM

```bash
make shell            # or: multipass shell ems
make ssh              # passwordless, as user 'ubuntu'
make status           # pm-opctl-cli list, one row per process
make health           # exit 0 when every process is OK
make info             # VM name and multipass state
```

Provisioning has already run `pm-setup`, so the VM starts with a deployed
configuration. The working directory is `/home/ubuntu/session`; the data
directory is `/home/ubuntu/.local/share/edumatcher`, exported as
`EDUMATCHER_DATA_DIR` in `.bashrc`.

Start everything with the process manager:

```bash
pm-opctl-cli start          # the 'default' profile
pm-opctl-cli list
pm-opctl-cli stop
```

Or start processes by hand, one per terminal, which is how the User Guide is
written:

```bash
pm-engine --verbose
pm-audit --terminal
pm-clearing
pm-viewer --symbol AAPL
pm-alf-console --id TRADER01
```

`mknode.sh` prints the VM's IP address and the API keys from the deployed
configuration when it finishes — keep that output, or recover the keys later
with `pm-config-show`.

Verify the command links:

```bash
ls -1 /usr/local/bin/pm-*
cat /opt/edumatcher/EDUMATCHER_VERSION
```

## Upgrade

The preferred route is an immutable rebuild under a new name, so the old VM
stays available:

```bash
make build NAME=ems-026 VERSION=0.26.0
```

To update a VM in place:

```bash
./mkupd.sh --vm-name ems
```

## Reset and remove

```bash
make restore          # roll back to the 'clean' snapshot
make clean            # multipass delete --purge
```

`make restore` is what makes this image useful for teaching: after a class has
made a mess of the order books, one command returns the VM to its
freshly-provisioned state.
