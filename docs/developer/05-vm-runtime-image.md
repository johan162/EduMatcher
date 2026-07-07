# VM Runtime Image with Pinned PyPI Release

!!! note "Learning objectives"
    After reading this page you will understand:

    - How to build a VM image preinstalled with a selected EduMatcher version
    - Why the VM image uses pip in a dedicated venv instead of pipx
    - How all pm-* commands are linked into /usr/local/bin
    - How to launch and operate EduMatcher from the provisioned VM


## Summary

EduMatcher can be distributed as a pre-provisioned VM where runtime commands are available globally.

This repository includes a scripted pipeline in `vm/README.md`:

- `vm/build_multipass_vm.sh`
- `vm/install_edumatcher_runtime.sh`

The provisioning flow installs a pinned package version from PyPI and creates symlinks for every detected pm-* command in /usr/local/bin.


## Why pip in venv instead of pipx for this VM

For a shared VM runtime image, pip in a dedicated virtual environment is the better fit:

1. Deterministic system pathing: all pm-* commands resolve from /usr/local/bin.
2. Operational clarity: one controlled runtime location under /opt/edumatcher/.venv.
3. Easier service wiring: unit files and scripts can always reference stable absolute paths.

pipx remains a strong choice for per-user workstation installs, but this VM image has a system-wide command-link requirement.


## Build the VM image

Without cloning the repository:

```bash
curl -fsSL https://raw.githubusercontent.com/johan162/EduMatcher/main/vm/curl_setup_vm.sh | bash -s -- --version 0.15.2 --snapshot
```

With a local repository checkout:

From repository root:

```
./vm/build_multipass_vm.sh --version 0.15.2
```

Useful options:

| Name | Default | Description |
|---|---|---|
| `--name` | `edumatcher-vm` | Name of the Multipass VM instance |
| `--image` | `lts` | Base Multipass image to launch |
| `--cpus` | `2` | Number of virtual CPUs assigned to the VM |
| `--memory` | `3G` | RAM allocated to the VM |
| `--disk` | `10G` | Maximum virtual disk size for the VM |
| `--snapshot-name` | `clean-runtime` | Snapshot name used when `--snapshot` is enabled |
| `--version` | `0.7.1` | EduMatcher PyPI version to install in the VM |


## What provisioning does

Inside the VM, provisioning performs the following steps:

1. Installs Python 3.13 and runtime prerequisites.
2. Creates /opt/edumatcher/.venv.
3. Installs edumatcher==<selected version> from PyPI.
4. Discovers all installed pm-* console entry points.
5. Symlinks each command to /usr/local/bin/pm-*
6. Persists installed version to /opt/edumatcher/EDUMATCHER_VERSION.


## Verify command links

Inside the VM:

```
ls -1 /usr/local/bin/pm-*
cat /opt/edumatcher/EDUMATCHER_VERSION
```


You can also inspect the source directory for symlink targets:

```
ls -1 /opt/edumatcher/.venv/bin/pm-*
```


## Launch and run EduMatcher in the VM

Open a shell:

```
multipass shell edumatcher-vm
```

A bootstrap config have already been created in `/home/ubuntu/session/` using `pm-setup`:

```
cd ~/session
```

Open five terminals and connect them to a VM shell with `multipass shell edumatcher-vm` . The start the EduMatcher key processes in separate terminals:

Terminal 1:
`pm-engine --verbose`

Terminal 2:
`pm-audit --terminal`

Terminal 3:
`pm-clearing`

Terminal 4:
`pm-viewer --symbol AAPL`

Terminal 5:
`pm-alf-console --id TRADER01` 


## Upgrading the pinned version

Preferred approach is immutable rebuild with a new VM name:

```
./vm/build_multipass_vm.sh --name edumatcher-072 --version 0.15.2 --snapshot
```

If you need in-place reprovisioning:

```
multipass transfer vm/install_edumatcher_runtime.sh edumatcher-071:/tmp/install_edumatcher_runtime.sh
multipass exec edumatcher-071 -- sudo chmod +x /tmp/install_edumatcher_runtime.sh
multipass exec edumatcher-071 -- sudo /tmp/install_edumatcher_runtime.sh --version 0.15.2
```

