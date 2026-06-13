# Release Checklist & Guide

## Summary

This document describes all steps necessary to make a new EduMacher release.

## Checklist

1. Bump the `pyproject.toml` version  
    ```sh
    poetry version <NEW VERSION>  
    ```

2. Add a new `CHANGELOGENTRY.md`. Use the `/changelog` skill to create a draft version based on the git-logs

3. Run the complete build script `scripts/mkbld.sh` and fix any potential issues until it runs clean.

4. Check in all modified files, some versions (e.g. README.md) have been bumped by the `mkbld.sh` script. Make sure the `develop`  branch is clean.

5. Run the release script `script/mkrelease <RELEASE-TYPE>` to handle merge into `main` and verify that all things are in place. Fix potential isssues until it runs clean. This will also trigger GitHub actions like publishing the `gh-pages` to the doc-site.

6. Make the GitHub release with `scripts/mkghrelease.sh` 


