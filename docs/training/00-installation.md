# Installation & Setup

## Objective

Install EduMatcher from PyPI, configure environment variables for config and
data directories, and use the `pm-setup` helper to bootstrap your workspace.


---

## Exercise 0: Read the [How an Exchange Works](../how-exchange-works.md)

This is not strictly required, but it will give you a solid mental model of the core components and data flows in an exchange. It will make the training exercises more intuitive and meaningful. This is especially recommended if you are new to how exchanges operate under the hood or lack a financial background.

Once you read that introduction, you can refer back to it at any time during the training. The concepts will become clearer as you see them in action.

---

## Exercise 1: Install EduMatcher

The recommended way to install is via `pipx` (isolates the package in its own
virtual environment while making all `pm-*` commands globally available):

```bash
pip install pipx
pipx ensurepath
pipx install edumatcher
```

Verify the installation:

```bash
pm-engine --version
```

!!! tip "Alternative: Poetry (developer mode)"
    If you're working from source:
    ```bash
    git clone https://github.com/johan162/EduMatcher.git
    cd EduMatcher
    poetry install --with dev
    ```
    All commands must be prefixed with `poetry run` (e.g. `poetry run pm-engine`).

:material-checkbox-blank-outline: **Checkpoint:** `pm-engine --version` prints a version number.

---

## Exercise 1 (Alternative): Multipass VM Setup

If you want a ready-to-run Linux environment without installing Python tooling
on your host, use the Multipass bootstrap flow. This creates an Ubuntu VM,
installs EduMatcher inside it, and leaves you with a clean runtime sandbox.

### Step 1: Install Multipass on your host

Install Multipass from [multipass.run](https://multipass.run/install), then
verify it is available:

```bash
multipass version
```

### Step 2: Bootstrap the VM with one command

Run the curl bootstrap script (pinned to this release):

```bash
curl -fsSL https://raw.githubusercontent.com/johan162/EduMatcher/main/vm/curl_setup_vm.sh | bash -s -- --version 0.12.1 --snapshot
```

This command will:

1. Download the VM setup scripts from the EduMatcher repository.
2. Launch a Multipass VM (default name: `edumatcher-vm`).
3. Install the EduMatcher runtime and required dependencies in the VM.
4. Print a short summary showing how to enter the VM and start processes.

!!! tip "Security-first variant"
    If you prefer to inspect scripts before running them:
    ```bash
    curl -fsSL https://raw.githubusercontent.com/johan162/EduMatcher/main/vm/curl_setup_vm.sh -o curl_setup_vm.sh
    less curl_setup_vm.sh
    bash curl_setup_vm.sh --version 0.12.1 --snapshot
    ```

### Step 3: Enter the VM and verify commands

```bash
multipass shell edumatcher-vm
pm-engine --version
pm-scheduler --help
pm-gateway --help
```

### Step 4: Run a first end-to-end session inside the VM

Open several host terminals and attach each to the same VM:

```bash
multipass shell edumatcher-vm
```

Then start core processes in separate VM shells (engine, scheduler, gateways,
and clients) following the run order from the User Guide. 

### Step 5: Stop, restart, and clean up the VM

From your host machine:

```bash
multipass list
multipass stop edumatcher-vm
multipass start edumatcher-vm
```

When you no longer need it:

```bash
multipass delete edumatcher-vm
multipass purge
```

### Relevant User Guide chapters

- [Getting Started](../user-guide/00-getting-started.md) (see VM bootstrap mode)
- [Running the Engine](../user-guide/03-running-the-engine.md)
- [Processes](../user-guide/10-processes.md)
- [Examples](../user-guide/80-examples.md)

:material-checkbox-blank-outline: **Checkpoint:** You can enter
`edumatcher-vm` and `pm-engine --version` succeeds inside the VM.

---



## Exercise 2: Run pm-setup

***If you have used the VM (Multipass) this step can be skipped as it has already been done as part of the VM setup.***

The `pm-setup` helper bootstraps your local environment in one command:

```bash
pm-setup
```

What it does:

1. Creates the data directory at `~/.local/share/edumatcher/`.
2. Copies a sample `engine_config.yaml` into the current working directory.
3. Prints a shell snippet with the environment variable exports you need.

Expected output:

```
✓ Created data directory: /Users/you/.local/share/edumatcher
✓ Copied sample engine_config.yaml to ./engine_config.yaml

Add the following to your shell profile (~/.zshrc or ~/.bashrc):

  export EDUMATCHER_DATA_DIR="$HOME/.local/share/edumatcher"
  export EDUMATCHER_CONFIG="./engine_config.yaml"
```

!!! note "Re-running pm-setup"
    Use `pm-setup --force` to overwrite an existing sample config with the
    latest version from the package.

:material-checkbox-blank-outline: **Checkpoint:** data directory exists; sample config in place.

---

## Exercise 3: Set Environment Variables

***If you have used the VM (Multipass) this step can be skipped as it has already been done as part of the VM setup.***

Add the exports to your shell profile:

```bash
# Add to ~/.zshrc (macOS) or ~/.bashrc (Linux)
export EDUMATCHER_DATA_DIR="$HOME/.local/share/edumatcher"
export EDUMATCHER_CONFIG="./engine_config.yaml"
```

Then reload:

```bash
source ~/.zshrc   # or source ~/.bashrc
```

| Variable | Purpose | Default |
|----------|---------|---------|
| `EDUMATCHER_DATA_DIR` | Where persistent data (stats DB, logs, state) is stored | `~/.local/share/edumatcher` |
| `EDUMATCHER_CONFIG` | Path to the engine configuration YAML | `./engine_config.yaml` |

!!! tip "Override per-session"
    You can point to a different config for different scenarios:
    ```bash
    EDUMATCHER_CONFIG=~/configs/classroom.yaml pm-engine
    ```
    The `--config` flag on `pm-engine` and `pm-scheduler` takes precedence
    over the environment variable.

:material-checkbox-blank-outline: **Checkpoint:** `echo $EDUMATCHER_DATA_DIR` prints the correct path.

---

## Exercise 4: Verify the Data Directory

Check that the data directory was created and is writable:

```bash
ls -la "$EDUMATCHER_DATA_DIR"
```

This directory will hold:

- `stats.db` — trade and market statistics (created by `pm-stats`).
- Session state and persistence files (created by `pm-engine`).
- Log files (if file logging is enabled).

:material-checkbox-blank-outline: **Checkpoint:** directory exists and is writable.

---

## Exercise 5: Inspect the Sample Configuration

Open the generated config:

```bash
cat engine_config.yaml
```

You should see a `symbols:` section and a `gateways:` section. This is the file
you will customise in the next chapter.

:material-checkbox-blank-outline: **Checkpoint:** sample config contains symbols and gateways.

---

## Exercise 6: Confirm All Entry Points

Verify that the key commands are available:

```bash
pm-engine --help
pm-scheduler --help
pm-gateway --help
pm-setup --help
pm-config-gen --help
pm-mm-bot --help
```

Each should print usage information without errors.

!!! note "pm-mm-bot is available"
    `pm-mm-bot` is included in the installed command set. Chapter 02 starts
    with manual market-maker quotes so you understand quote mechanics first,
    then introduces equivalent bot-based workflow.

:material-checkbox-blank-outline: **Checkpoint:** all commands respond to `--help`.

---

## Summary

You now have:

- EduMatcher installed and accessible as `pm-*` commands.
- A data directory for persistent state.
- Environment variables configured.
- A sample `engine_config.yaml` ready for customisation.

## Further Reading

- [Getting Started](../user-guide/00-getting-started.md)
- [Running the Engine](../user-guide/03-running-the-engine.md)
- [Processes](../user-guide/10-processes.md)

**Next:** [01 — Configuring & Starting Up](01-configuring-startup.md)
