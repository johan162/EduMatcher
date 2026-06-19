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

## Exercise 2: Run pm-setup

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
