# EduMatcher v1.0.0 — clean-history reset and release model (2026-11-24)

Goal: v1.0.0 starts from a repository with **no pre-1.0 history and no
pre-1.0 GitHub releases**, and from 1.0.0 onwards `main` and `develop` are
**identical after every release** (GitHub shows "0 ahead / 0 behind").

Decisions taken:

| # | Decision |
|---|----------|
| D1 | Rewrite the existing GitHub repo in place (force-push). No new repo. |
| D2 | Delete all pre-1.0 git tags, GitHub releases, workflow runs and the `gh-pages` history. |
| D3 | Change the release merge from *squash + merge-back* to *`--no-ff` merge + fast-forward back*. |
| D4 | Keep `vX.Y.Z` / `vX.Y.ZrcN` annotated tags; add tag and branch rulesets after the reset. |

---

## 1. Why not a new repo (option C), and why A == B

Options A (squash `develop`, recreate `main` from it) and B (squash `main`,
recreate `develop` from it) end in exactly the same state: two branches
pointing at one fresh root commit. The only real choice is *in place* vs
*new repo*.

A new repo buys nothing a clone would ever see, and costs:

- `PYPI_API_TOKEN` / `TEST_PYPI_API_TOKEN` secrets must be re-created.
- Every GHCR package (`ghcr.io/johan162/edumatcher*`) is linked to the old
  repository; `publish-images.yml` pushes with `GITHUB_TOKEN`, so each package
  must be re-linked / granted Actions access to the new repo.
- GitHub Pages settings, repo description/topics and the 3 stars are lost.
- The old repo name must be freed first (delete or rename).

In place, force-push instead of delete:

- `develop` is the default branch, and GitHub refuses to delete the default
  branch.
- Deleting a branch closes PRs that target it.
- No branch protection or rulesets exist today, so force-push is allowed.

The only thing in-place cannot remove is GitHub's own `refs/pull/*` refs
(3 exist). They keep old objects on GitHub's servers but are **not** fetched
by `git clone`, so no clone ever sees them.

---

## 2. Is the current release process best practice?

Mostly yes: release from a clean, up-to-date `develop`; required changelog
entry; artifacts built and checked before tagging; annotated `v`-prefixed
SemVer tags; atomic push of branch + tag; wait for CI before creating the
GitHub release; publishing (PyPI, GHCR) driven by the GitHub *release* event;
`rcN` tags routed to TestPyPI and kept off `:latest`. That is a sound
git-flow-lite process.

The one design choice that is *not* best practice is the **squash merge into
`main` followed by a merge back into `develop`**. That is the cause of the
permanent "develop is N commits ahead of main" message.

### 2.1 Why squash causes the ahead/behind message

GitHub's ahead/behind count is a **commit-graph** comparison, not a content
comparison. A squash commit on `main` has the same *tree* as `develop`, but
none of `develop`'s commits are ancestors of `main`. After the merge back:

```
main:     S1 ─────────── S2              (squash commits)
             \             \
develop:  a─b─c─M1─d─e─f───M2            (M = "sync develop with main")
```

`develop` contains every `main` commit (behind = 0), but `main` contains none
of `a…f` (ahead = all of them, growing forever). Between `mkrelease.sh`
pushing `main` and pushing `develop` it is also "1 behind". This can't be
fixed while `main` is squashed; it is how squash merges work.

### 2.2 Alternatives

| Model | `main` after release | Ahead/behind | Release-only view of `main` |
|-------|----------------------|--------------|-----------------------------|
| Squash + merge back (current) | 1 squash commit per release | Always "N ahead" | `git log main`, GitHub commit list |
| **`--no-ff` merge, then fast-forward `develop` (recommended)** | 1 merge commit per release, full history beneath | **0 / 0** | `git log --first-parent main`, Releases page |
| `--ff-only` (no merge commit) | `main` simply moves to `develop`'s tip | 0 / 0 | Tags / Releases page only |
| Trunk only (drop `main`, release = tag) | — | n/a | Tags / Releases page only |

**Recommendation: `--no-ff` merge + fast-forward back.**

- `main` gets one merge commit per release, titled `release: X.Y.Z`, so
  `git log --first-parent --oneline main` is exactly the release list.
- `develop` is then fast-forwarded to that merge commit. Both branches point
  at the **same commit**, so GitHub shows 0 ahead / 0 behind and
  `git diff main develop` is empty by construction, not by convention.
- No extra "sync develop with main" commits.
- The tag sits on a commit that is on both branches.

The trade-off: GitHub's web commit list for `main` shows all individual
commits (GitHub does not render first-parent). The **Releases page** is the
per-release view, and `CHANGELOG.md` is the human-readable one. If a
one-commit-per-release GitHub commit list on `main` is a hard requirement,
squash is the only way, and the ahead/behind message comes with it.

Trunk-only would also be best practice for a single maintainer, but
`ci.yml` and the docs deploy both key on pushes to `main`. Dropping `main`
means rewiring CI and publishing docs on the release event. That is more
change than 1.0 needs.

### 2.3 Tagging — anything else needed?

No new tagging scheme is needed. Keep:

- Annotated tags `vX.Y.Z` (production → PyPI + `:latest`) and `vX.Y.ZrcN`
  (TestPyPI, no `:latest`). This already matches what the two publish
  workflows expect.
- Tags created only by `mkrelease.sh`, on the release merge commit.
- No moving git tags (`latest`, `stable`). The GitHub "Latest release" badge
  and the image `:latest` tag already cover that.

Recommended additions (after the reset, §4 step 9):

- **Tag ruleset** on `v*`: block deletion and update (no re-pointing a
  published tag; PyPI cannot re-upload a version anyway).
- **Branch ruleset** on `main` (and optionally `develop`): block force-push
  and deletion. This is the last force-push `main` should ever see.
- Optional: signed tags (`git tag -s`) so GitHub shows "Verified". Needs a
  GPG/SSH signing key configured for git; drop-in change in `mkrelease.sh`.

### 2.4 Smaller issues found in the release scripts

- The tag message and squash commit message are boilerplate from another
  project: "All example networks validated", "CLI and REPL functionality
  verified". Replace with the `CHANGELOG.md` section for the version, or a
  short accurate list.
- Coverage numbers disagree: help text says ">90%", `COVERAGE="80"`, CI uses
  `--cov-fail-under=85`.
- Phase 5 summary text ("GitHub will show develop as 'ahead' of main - this is
  expected!") and the help "WORKFLOW" section describe squash and must be
  updated with D3.
- The `RELEASE_TYPE` argument only feeds the tag message; the version comes
  from `pyproject.toml`. Harmless, but `mkrelease.sh major` for 1.0.0 is
  cosmetic.

---

## 3. `mkrelease.sh` change (D3)

Phase 2.2: replace the squash with a `--no-ff` merge.

```bash
# before
run_command "git merge --squash develop" "Squashing develop changes..."
run_command "git commit -m \"release: $VERSION ...\"" "Creating release commit on main..."

# after
run_command "git merge --no-ff develop -m \"release: $VERSION

See CHANGELOG.md for detailed changes.\"" "Merging develop into main..."
```

Phase 3.2: replace the `--no-ff` merge-back with a fast-forward.

```bash
# before
git merge --no-ff -m "chore: sync develop with main after release v$VERSION" main

# after
git merge --ff-only main     # develop == main, no sync commit
```

Also: add a check, before the merge, that `develop` has commits `main` lacks,
so "Already up to date" fails cleanly instead of tagging an old commit:

```bash
check_condition '[[ -n $(git rev-list origin/main..develop) ]]' "Nothing to release: develop has no commits that main lacks"
```

Update the help text and the Phase 5 summary to match (§2.4).

Rule that comes with this model: **never commit directly to `main`** (no
hotfixes there). Fix on `develop` and release. A commit only on `main` makes
the `--ff-only` step fail *after* `main` and the tag are pushed.

Make this change on `develop` **before** the reset, so the new root commit
already contains it.

---

## 4. Reset procedure

Preconditions: all 1.0 work merged and pushed to `develop`; no other open
work branches you want to keep; `mkbld.sh` green.

`mkrelease.sh` needs `main` **one commit behind** `develop`. If they are
equal, there is nothing to merge. So the reset builds `main` = a root
commit, and `develop` = that root commit + the 1.0.0 version bump.

```bash
cd ~/Devel/EduMatcher
git checkout develop && git pull --ff-only

# 0. Safety net (optional; delete it once 1.0.0 is published and verified).
#    'bundle verify' must be run inside a git repository.
git bundle create ~/edumatcher-pre-1.0.bundle --all
git bundle verify ~/edumatcher-pre-1.0.bundle

# 1. One root commit with develop's current tree (version still 0.x).
#    -M keeps develop's upstream config (verified).
git checkout --orphan new-root develop
git commit -m "chore: initial import of EduMatcher"
git branch -f main new-root
git branch -M new-root develop          # replaces the old develop

# 2. Release prep on develop (normal routine)
#    - set pyproject version to 1.0.0 (poetry version 1.0.0)
#    - CHANGELOG.md: see note below
#    - commit (do NOT push yet; step 7 pushes it), then ./scripts/mkbld.sh

# 3. Delete all GitHub releases together with their tags
#    (159 today; none are drafts or immutable)
gh release list --limit 500 --json tagName -q '.[].tagName' \
  | xargs -r -n1 gh release delete -y --cleanup-tag

# 4. Delete remaining remote tags and all local tags
git ls-remote --tags --refs origin | awk '{print $2}' \
  | xargs -r git push origin --delete
git tag -l | xargs -r git tag -d

# 5. Delete stale branches (gh-pages is NOT deleted, see step 9)
git push origin --delete feature/system-test msg-gen operator-dashboard trader-gui
git branch -D operator-dashboard backup/main-before-reset-20261027-213140

# 6. Delete old workflow runs (925 today)
./scripts/mkdelghactions.sh --delete --keep 0 --limit 1000

# 7. Publish the new branches. --force-with-lease refuses if GitHub moved
#    since your last fetch. Triggers ci.yml + a docs deploy on main.
git push --force-with-lease -u origin main develop

# 8. Release (mkrelease.sh ends on develop; mkghrelease.sh requires main)
./scripts/mkrelease.sh major --dry-run
./scripts/mkrelease.sh major
git checkout main
./scripts/mkghrelease.sh                 # ends with 'git checkout develop'

# 9. Flatten gh-pages to one commit. Wait until the docs.yml deploy for the
#    release push has finished (gh run list --workflow docs.yml), then:
git fetch origin gh-pages
NEW=$(git commit-tree -m "Deploy documentation for v1.0.0" 'origin/gh-pages^{tree}')
git push --force origin "$NEW:refs/heads/gh-pages"

# 10. Lock it down (GitHub → Settings → Rules → Rulesets)
#    - branch ruleset main: block force pushes, restrict deletions
#    - tag ruleset v*: restrict updates, restrict deletions

# 11. Local cleanup. Refs outside heads/tags/remotes keep the old history
#     alive and must go first: ~200 Claude Code checkpoint refs (refs/agents/*),
#     one stash ("On develop: Before pulling origin" — check it first with
#     'git stash show -p'), and a stale worktree record.
git worktree prune
git stash clear
git for-each-ref --format='%(refname)' refs/agents | xargs -r -n1 git update-ref -d
git fetch --prune origin
git for-each-ref --format='%(refname)' | grep -vE '^refs/(heads|tags|remotes)/'   # must print nothing
git reflog expire --expire=now --all && git gc --prune=now
git count-objects -vH                                                          # size-pack ≈ 135 MiB
```

Notes:

- **CHANGELOG.md.** With no history and no old releases, decide whether
  the 0.x entries stay (as plain history text) or are replaced by a single
  1.0.0 entry. `mkrelease.sh` only requires the `## [v1.0.0] - YYYY-MM-DD`
  heading.
- **gh-pages.** It is flattened in place (step 9) instead of deleted, so the
  docs site never goes offline. `commit-tree` builds the commit from the
  published tree without touching your working directory. Every later push
  to `main` adds one deploy commit on top of it.
- **Step 11 alternative.** Instead of cleaning up in place, clone the repo
  fresh and copy over untracked local files you need (`.venv` can be
  rebuilt). Either way, `git log --oneline --all` afterwards should show only
  the new commits plus the `gh-pages` commit.
- **Other clones and worktrees** (other machines, containers, the
  `operator-dashboard` worktree if any) must be deleted and re-cloned. A
  `git pull` in an old clone merges the entire old history back, and the next
  push re-publishes it.
- **PyPI and GHCR keep their 0.x versions.** They are not GitHub releases.
  Old GHCR image versions can be deleted under the package settings if
  wanted. Deleting PyPI releases is possible but discouraged (versions can
  never be reused, and anyone pinning them breaks); yanking is the gentler
  option.
- **Optional rehearsal.** Set the version to `1.0.0rc1` in step 2, release it
  (goes to TestPyPI, images without `:latest`), then bump to `1.0.0` and
  release again. That exercises the changed `mkrelease.sh` end to end at the
  cost of one extra `release:` merge commit on `main`.

---

## 5. Expected end state and checks

```
main:     R ───────── M  (tag v1.0.0)
           \         /
develop:    └─ bump ─┘    develop == main == M
```

| Check | Expected |
|-------|----------|
| `git rev-parse main develop origin/main origin/develop \| sort -u \| wc -l` | 1 (all four identical) |
| `git rev-list --left-right --count origin/main...origin/develop` | `0 0` |
| `git log --oneline main` | 3 commits: release merge, bump, root |
| `git log --first-parent --oneline main` | 2 commits: release merge, root |
| `git tag -l` | `v1.0.0` only |
| `gh release list` | `v1.0.0` only |
| `git ls-remote --heads origin` | `develop`, `gh-pages`, `main` only |
| `git rev-list --count origin/gh-pages` | 1 (after step 9) |
| GitHub branches page | develop: 0 ahead / 0 behind |
| `du -sh .git` in a fresh clone | ≈ 137 MB (current tree + docs site; binary docs/images dominate), not ~470 MB |
| PyPI / GHCR | `1.0.0` published; images tagged `1.0.0` + `latest` |
| docs site | up |

After the next release (1.0.1 / 1.1.0), `main` and `develop` must again be
the same SHA.

---

## 6. Verification record (2026-11-24)

Every git command in §3 and §4 was run in a throwaway copy: a bare clone of
this repo (all 9 remote branches, 174 tags) acting as GitHub, and a clone of
it acting as the working copy.

| Command(s) | Result |
|------------|--------|
| Step 1 orphan + `branch -f` + `branch -M` | Root commit has no parent, tree identical to old `develop`, `develop` upstream config kept, `@{u}` check in `mkrelease.sh` passes |
| Step 4 tag deletion | 174 remote and local tags removed, `xargs -r` safe when empty |
| Step 5 branch deletion | Remote branches removed; `branch -D` of a missing branch only prints an error |
| Step 7 `--force-with-lease -u` | Pushes the rewrite; refuses ("stale info") if the remote moved |
| §3 `--no-ff` merge + `--ff-only` back, two release cycles | Branches identical after each release, `0 0` ahead/behind, `git describe --tags --abbrev=0 main` (used by `mkghrelease.sh`) returns the new tag |
| Step 9 `commit-tree` flatten | `gh-pages` 174 → 1 commit, same tree, working directory untouched |
| Step 11 cleanup | `reflog expire` + `gc` alone does **not** drop old history while `refs/agents/*` or `refs/stash` exist; after removing them it does |
| Step 0 bundle | `bundle verify` OK (inside a repo); `git clone <bundle>` restores |

The `gh` commands were not run, since they would change GitHub. Their flags
were checked against the installed `gh` 2.97.0 (`release list --json tagName`,
`release delete --cleanup-tag -y`), and `gh release list` was run read-only:
159 releases, none draft or immutable. `mkdelghactions.sh` accepts
`--keep 0` and `--limit 1000`.
