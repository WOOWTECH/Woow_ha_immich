# AGENTS.md

Rules for every agent and person who changes this repository. The full
release mechanism is described in the Woow_HA_App_Store README (section
"版本策略與同步") and in ADR-0005 of the WOOW addon pipeline.

1. **``main`` only changes through a pull request.** A ruleset blocks direct
   pushes, force pushes and deleting the branch, and nobody can bypass it.
   Push a branch, open a PR, wait for the required checks, then merge.
2. **A PR that changes an addon version is a release.** Merging it publishes
   that version to the WOOW App Store. It must pass every required check; the
   checks are the approval, there is no human review step. Every PR runs
   `Upgrade comparison / compare` (pipeline #89); treat a failure as blocking.
   It compares each addon whose version the PR changes with the latest Stable
   Release. A PR that changes no version passes it in seconds. The result is
   in the job summary. It also runs the upgrade test (pipeline #144): the Store
   rebuilds the latest Release and the PR for amd64, starts the Release under a
   mock Supervisor, then the PR's version on the same data, and fails when
   either does not start (here: the webui on port 8080 answers and the
   container stays up). It also checks data (pipeline #151) with the hooks in
   `woow-immich/upgrade-check/`: on the Release, `seed` creates the first
   admin through Immich's REST API (`/api/auth/admin-sign-up`), an API key,
   uploads a photo and puts it in a new album; on this PR's version, `verify`
   checks that Immich answers (its migrations ran), the admin still logs in,
   the API key still works, the album still holds the photo, the photo's
   original downloads with the same bytes and checksum, and a new upload
   works. Keep them working when you change the port 8080 server, the media
   location or the bundled PostgreSQL; a failing check blocks the release.
   The hook interface (environment, JSON report) is in the Woow_HA_App_Store
   README, "第 2 類 升級測試", paragraph "資料檢查（#138）". Keep the hooks
   executable (`git update-index --chmod=+x`), with LF endings and a `#!` of
   python3 or busybox sh only (no bash): they run in the Store's
   python:3.12-alpine mock Supervisor container, so never `docker run` from
   them. A hook must not leave background processes running when it exits,
   and a hook file must not be a symlink to anything outside `upgrade-check/`
   (only that directory is mounted). An optional
   `woow-immich/upgrade-check/settings.yaml` sets `startup_timeout`,
   `stable_seconds` and `hook_timeout` (positive integer seconds);
   `hook_timeout` defaults to 600 and covers the whole `docker exec` of a hook.
   The Store registry sets `data_check_due: "2026-12-29"` for this addon
   (pipeline #141): from the next day (UTC), a version bump without a `verify`
   hook fails, so do not remove it.
3. **Breaking changes must be declared in `upgrade-notes.yaml`** next to the
   addon's `config.yaml` (here `woow-immich/upgrade-notes.yaml`). Create the
   file only when the upgrade comparison asks for it; copy `change` and `key`
   from its report and write the migration path. The addons here are built on
   the device: the vulnerability comparison runs on the images the Store
   rebuilds for the upgrade comparison (pipeline #146). The release puts these
   entries on the GitHub Release. Rules, change names and the file format: the
   Woow_HA_App_Store README, section "升版比對與 `upgrade-notes.yaml`".
