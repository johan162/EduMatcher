# Config `include:` — design and workplan

Status: DRAFT 2026-11-05. Target: before 1.0.0. No code yet.

## 1. Goal

Let `engine_config.yaml` pull in other YAML files so that hundreds of symbols and
participants can live in `symbols.yaml` / `participants.yaml` while the main file stays
readable. YAML itself has no include (anchors/aliases are single-document only), so this
is an EduMatcher feature with its own, deliberately small, semantics.

## 2. Findings that shape the design

The config is *compiled*. `pm-config-deploy` reads the authored YAML, validates it, and writes
`engine_config.json`; running processes read only the artifact. So includes are an
**authoring-time** feature and touch only the tools that read the authored YAML:

| Site | What it does with the YAML |
|---|---|
| `config_deploy.compile_config` | calls `load_engine_config(source)` plus ten gateway/log/monitor loaders, each doing its own `yaml.safe_load(path)` |
| `cverifier/layer1_yaml.py:54` | parse + `Y001–Y004` errors |
| `config_show/cli.py:113` | `pm-config-show` |
| `config_artifact` (`source_digest`, staleness check) | hashes the *main file text only* |
| `config_deploy.deploy` | copies the authored text beside the artifact |
| `new_symbol` (`config.py`, `yaml_edit.py`, `install.py`) | text-level edit of `symbols:`, refuses if the source digest differs from the deployed one |
| `config_gen` | emits one file |
| `emo/cli.py:506` | reads a YAML — check whether it is the engine config |

Not affected: `market_sim.yaml`, ai_trader presets/swarm, valuation, compdb, eod roster (separate files).

## 3. Semantics (decisions)

1. Top-level key `include:` — a list of relative paths. Not a `!include` tag (would need a custom
   loader; breaks `safe_load`, yamllint, editors).
2. Paths are relative to the including file, must not be absolute and must not contain `..`
   (an include stays inside the main file's directory tree). Missing file → error.
3. One level only: an included file may not itself contain `include:`. No cycles possible.
4. Included files are mappings using the same top-level keys as the main file.
5. Merge, per top-level key present in more than one file:
   - both lists → concatenated, in include order (main file's own entries first);
   - both mappings → merged one level deep; a repeated second-level key is an error;
   - anything else (scalars, mixed types) → error naming both files.
   Nothing is ever silently overridden.
6. The merged dict is what every loader sees; the `include` key is removed from it.
7. Origin tracking: the helper also returns which file supplied each top-level key (and each
   `symbols` key / `participants` element) so diagnostics can name the file.

## 4. Shared helper

`src/edumatcher/config_include.py`:

```python
@dataclass(frozen=True)
class LoadedConfig:
    data: dict[str, Any]
    files: tuple[Path, ...]          # main first, then includes in order
    origins: ...                     # key -> file, see WP-INC4

class ConfigIncludeError(ValueError): ...

def load_config_mapping(path: Path) -> LoadedConfig: ...
```

Every `yaml.safe_load(path.read_text())` listed in §2 for the engine config is replaced by it.
Failures raise `ConfigIncludeError` (a `ValueError`, so existing `except ValueError` paths keep
working); cverifier maps it to a new `Y005`.

## 5. Workpackages

- **WP-INC1 — core helper. DONE 2026-11-05** (`LoadedConfig` carries `data` + `files` only; per-key origin tracking moved to WP-INC4 where it is first needed). `config_include.py` + unit tests: no include, one/many includes,
  list concat, mapping merge, duplicate key, type clash, absolute path, `..`, missing file,
  nested include, YAML syntax error in an included file (message names that file).
  → verify: new tests green, mypy/pyright clean.
- **WP-INC2 — wire into readers. DONE 2026-11-05** (also added `Y005` to layer 1; loaders now raise on a non-mapping file instead of returning defaults; `emo/cli.py:506` reads emo profiles, not the engine config, so unchanged). `load_engine_config` and the ten loaders called from
  `compile_config`; `layer1_yaml.load`; `config_show`; decide `emo/cli.py:506`. A split config and
  its single-file equivalent must produce identical `CompiledConfig` content.
  → verify: equivalence test over the bundled examples (split them programmatically in the test).
- **WP-INC3 — deploy and staleness.** `source_digest` becomes a digest over all files (main +
  includes, in order, with names, so a rename changes it). `deploy` copies the authored tree beside
  the artifact (same relative layout) instead of one file. Stale-detection and
  `new_symbol.resolve_target` use the combined digest. Removing an include between deploys must
  not leave an orphan copy behind (same care as the existing `market_sim.yaml` unlink).
  Open point: copy the tree (faithful record, chosen) vs. install one merged file (loses comments).
  → verify: deploy → edit an included file → staleness reported; deploy twice with fewer includes.
- **WP-INC4 — diagnostics.** `Y005` for include errors; cverifier messages for symbols and
  participants name the supplying file (`symbols.yaml: symbol ABC …`). Line numbers for syntax
  errors come from the failing file. Check `pm-config-show` prints the file list.
  → verify: verifier tests with a broken symbol in `symbols.yaml`.
- **WP-INC5 — `pm-new-symbol`.** `insert_symbol` edits the file that supplies `symbols:` (the last
  contributing file if several; the main file if it has its own). Round-trip check in `yaml_edit`
  is done on that file's text; the "unreviewed edits" guard uses the combined digest.
  → verify: listing into split and unsplit configs; deployed result equals the unsplit one.
- **WP-INC6 — `config_gen --split`.** Writes `symbols.yaml` and `participants.yaml` beside the
  main output file and adds `include:`. Final `load_engine_config` validation runs on the main
  file, so it proves the split loads. Look at the existing output-path handling in
  `config_gen/cli.py` first (the temp-file validation near line 2097 must write the included files
  too). Not offered when output goes to stdout. → verify: generated split == generated single
  after load.
- **WP-INC7 — docs and e2e.** Operator guide config chapter (005) and the training guide: syntax,
  merge rules, limits, `--split`. Config-verifier and config-show design docs updated. One bundled
  example in split form if it fits the examples layout. An e2e: `pm-config-deploy` on a split config
  then engine start (follow `make test-e2e` conventions).

## 6. Out of scope

Glob includes, nested includes, overriding a value from an include, environment-variable paths,
include in `market_sim.yaml` or other YAML files. Revisit only if asked.

## 7. Risks

- A reader that is missed keeps calling `yaml.safe_load` on the main file and silently sees no
  symbols. Mitigation: WP-INC2 greps for every remaining `safe_load` on the engine config and the
  equivalence test runs the whole `compile_config` path.
- The combined digest must stay stable for single-file configs, or every existing deployed artifact
  looks stale. Per the project rule there is no migration code, so the digest may simply change and
  existing artifacts get redeployed; decide in WP-INC3.
