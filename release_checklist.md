# Release Checklist & Guide

## Summary

This document describes all steps necessary to make a new EduMacher release.

## Checklist

1. Bump the `pyproject.toml` version  
    ```sh
    poetry version <NEW VERSION>  
    ```

2. Add a new `CHANGELOGENTRY.md`. Use the `/changelog <VERSION> <MAJOR|MINOR|PATCH>` skill to create a draft version based on the git-logs

3. Run the complete build script `scripts/mkbld.sh` and fix any potential issues until it runs clean.

4. Check in all modified files, some versions (e.g. README.md) have been bumped by the `mkbld.sh` script. Make sure the `develop`  branch is clean. Optionally call `mkbld.sh --intro` to re-build the Exchange Intro

5. Run the release script `script/mkrelease.sh` to handle merge into `main` and verify that all things are in place. Fix potential isssues until it runs clean. This will also trigger GitHub actions like publishing the `gh-pages` , publishing containers to GHCR, etc.

6. Make the GitHub release with `scripts/mkghrelease.sh` (try `--dry-run` first). Besides the release itself and the container images it **builds the web site and uploads it with `scripts/mkweb.sh`** (PHASE 6C). This needs `TIRNEX_ADITUS_FTP_SITE/USER/PWD` and `expect`, which the script checks before it publishes anything; use `--skip-web` or `--no-web-upload` to bypass. See `web_site/README.md` for the details and for what to do if that phase fails.

7. Check the live web site: new version badge, `/docs/`, and the Download page links (PDF, wheel, ZIP).
