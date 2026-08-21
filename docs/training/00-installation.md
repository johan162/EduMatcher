# Installation & Setup

## Objective

Install EduMatcher from PyPI, configure environment variables for config and
data directories, and use the `pm-setup` helper to bootstrap your workspace.


 

## Exercise 0: Read the [How an Exchange Works](../how-exchange-works.md)

This is not strictly required, but it will give you a solid mental model of the core components and data flows in an exchange. It will make the training exercises more intuitive and meaningful. This is especially recommended if you are new to how exchanges operate under the hood or lack a financial background.

Once you read that introduction, you can refer back to it at any time during the training. The concepts will become clearer as you see them in action.

 

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
curl -fsSL https://raw.githubusercontent.com/johan162/EduMatcher/main/vm/curl_setup_vm.sh | bash -s -- --version 0.20.2 --snapshot
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
    bash curl_setup_vm.sh --version 0.20.2 --snapshot
    ```

### Step 3: Enter the VM and verify commands

```bash
multipass shell edumatcher-vm
pm-engine --version
pm-scheduler --help
pm-alf-console --help
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

- [Getting Started](../user-guide/000-getting-started.md) (see VM bootstrap mode)
- [Running the Engine](../user-guide/040-running-the-exchange.md)
- [Processes](../user-guide/170-processes.md)
- [Examples](../user-guide/800-examples.md)

:material-checkbox-blank-outline: **Checkpoint:** You can enter
`edumatcher-vm` and `pm-engine --version` succeeds inside the VM.

 



## Exercise 2: Run pm-setup

***If you have used the VM (Multipass) this step can be skipped as it has already been done as part of the VM setup.***

The `pm-setup` helper bootstraps your local environment in one command:

```bash
pm-setup
```

What it does:

1. Creates the data directory at `~/.local/share/edumatcher/`.
2. Compiles the bundled sample configuration and installs it as the deployed
   ref-data artifact, keeping the authored YAML it compiled from alongside it.
3. Prints a shell snippet with the environment variable exports you need.

Expected output (abbreviated — the real output also prints the exact
`pm-engine`/`pm-scheduler`/`pm-alf-console` startup commands to run next):

```
pm-setup — EduMatcher session initialisation
==================================================
  ✓ Created data directory:          /Users/you/.local/share/edumatcher
  ✓ Sample config compiled to:       /Users/you/.local/share/edumatcher/ref_data/engine_config.json
    3 symbol(s) ready to trade.

  Shell environment snippet — add to your shell profile:
  (~/.zshrc)

  ----------------------------------------------
  export EDUMATCHER_DATA_DIR="/Users/you/.local/share/edumatcher"
  ----------------------------------------------
```

Notice `pm-setup` never mentions an `engine_config.yaml` in your **current
working directory** — that file is gone from this workflow. There is exactly
one file every process reads, and it is not a path you choose: the compiled
artifact under `$EDUMATCHER_DATA_DIR/ref_data/`. Confirm both paths it just
created:

```bash
pm-config-deploy --show
```

```
compiled: /Users/you/.local/share/edumatcher/ref_data/engine_config.json
source:   /Users/you/.local/share/edumatcher/ref_data/engine_config.yaml
```

!!! note "Re-running pm-setup"
    Use `pm-setup --force` to replace an already-deployed config with the
    latest sample from the package.

:material-checkbox-blank-outline: **Checkpoint:** data directory exists; `pm-config-deploy --show` prints both a `compiled:` and a `source:` path.

 

## Exercise 3: Set Environment Variables

***If you have used the VM (Multipass) this step can be skipped as it has already been done as part of the VM setup.***

Add the exports to your shell profile:

```bash
# Add to ~/.zshrc (macOS) or ~/.bashrc (Linux)
export EDUMATCHER_DATA_DIR="$HOME/.local/share/edumatcher"
```

Then reload:

```bash
source ~/.zshrc   # or source ~/.bashrc
```

| Variable | Purpose | Default |
|----------|---------|---------|
| `EDUMATCHER_DATA_DIR` | Where persistent data (stats DB, logs, state) **and the deployed engine configuration** live | `~/.local/share/edumatcher` |

This is the only variable there is. The engine configuration is always read
from `<EDUMATCHER_DATA_DIR>/ref_data/engine_config.json`, and no process takes
a path to it, so two processes cannot be started on different configurations.

!!! tip "Switching scenarios"
    Install a different configuration and restart:
    ```bash
    pm-config-deploy ~/configs/classroom.yaml
    ```
    Or give the scenario its own data directory, which isolates its
    statistics and logs as well:
    ```bash
    export EDUMATCHER_DATA_DIR=~/sessions/classroom
    pm-config-deploy ~/configs/classroom.yaml
    ```

:material-checkbox-blank-outline: **Checkpoint:** `echo $EDUMATCHER_DATA_DIR` prints the correct path.

 

## Exercise 4: Verify the Data Directory

Check that the data directory was created and is writable:

```bash
ls -la "$EDUMATCHER_DATA_DIR"
ls -la "$EDUMATCHER_DATA_DIR/ref_data"
```

This directory will hold:

- `ref_data/engine_config.json` — the **compiled artifact** every `pm-*`
  process actually reads; never edit this file by hand.
- `ref_data/engine_config.yaml` — the authored source it was last compiled
  from, kept only for provenance.
- `stats.db` — trade and market statistics (created by `pm-stats`).
- Session state and persistence files (created by `pm-engine`).
- Log files (if file logging is enabled).

:material-checkbox-blank-outline: **Checkpoint:** directory exists and is writable; `ref_data/` contains both `engine_config.json` and `engine_config.yaml`.

 

## Exercise 5: Inspect the Sample Configuration

`pm-setup` deployed the sample config from inside the installed package — it
never lands in your current working directory. Open the authored copy it
kept alongside the compiled artifact:

```bash
cat "$EDUMATCHER_DATA_DIR/ref_data/engine_config.yaml"
```

You should see a `symbols:` section and a `gateways:` section. This is the
same *kind* of file you will author and deploy yourself in the next chapter —
there, though, you will keep your own working copy under version control
rather than editing this deployed one directly.

:material-checkbox-blank-outline: **Checkpoint:** sample config contains symbols and gateways.

 

## Exercise 6: Confirm All Entry Points

Verify that the key commands are available:

```bash
pm-engine --help
pm-scheduler --help
pm-alf-console --help
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

 

## Summary

You now have:

- EduMatcher installed and accessible as `pm-*` commands.
- A data directory for persistent state.
- Environment variables configured.
- A sample `engine_config.yaml` ready for customisation.

## Before You Continue

Confirm every item before starting Chapter 01 — each one is a prerequisite
that chapter assumes without re-explaining:

- [ ] A configuration is deployed (`pm-config-deploy --show`, then `ls` that path).
- [ ] `EDUMATCHER_DATA_DIR` is set **in the shell you will use for the next
      chapter** (`echo $EDUMATCHER_DATA_DIR`) — it does not persist across new
      terminal windows unless added to your shell profile.
- [ ] `pm-engine --version` and `pm-engine --help` both resolve without a
      `command not found` error in that same shell.

## Reflection

Why does the training guide have you set `EDUMATCHER_DATA_DIR` explicitly in
Exercise 3 rather than always accepting a compiled-in default? What would
break in Chapter 16 (Persistence & Recovery) if two different terminal
sessions ended up pointing at two different data directories?

## Further Reading

- [Getting Started](../user-guide/000-getting-started.md)
- [Running the Engine](../user-guide/040-running-the-exchange.md)
- [Processes](../user-guide/170-processes.md)

**Next:** [01 — Configuring & Starting Up](01-configuring-startup.md)
