# AGENTS.md

Rules for every agent and person who changes this repository. The full
release mechanism is described in the Woow_HA_App_Store README (section
"版本策略與同步") and in ADR-0005 of the WOOW addon pipeline.

1. **``main`` only changes through a pull request.** A ruleset blocks direct
   pushes, force pushes and deleting the branch, and nobody can bypass it.
   Push a branch, open a PR, wait for the required checks, then merge.
2. **A PR that changes an addon version is a release.** Merging it publishes
   that version to the WOOW App Store. It must pass every required check; the
   checks are the approval, there is no human review step. One of them is
   `Upgrade comparison / compare` (pipeline #89): it compares each addon whose
   version the PR changes with the latest formal Release. A PR that changes no
   version passes it in seconds. The result is in the job summary.
3. **Breaking changes must be declared in `upgrade-notes.yaml`** next to the
   addon's `config.yaml` (here `woow-immich/upgrade-notes.yaml`), with the
   migration path. Create the file only when something needs declaring. The
   upgrade comparison blocks any breaking change without a matching entry:
   `option-removed`, `schema-removed`, `schema-retyped`, `made-required`,
   `range-narrowed`, `enum-value-removed`, `required-added`, `arch-removed`,
   `port-removed`, `image-changed`. Changed defaults and host ports are only
   reported. The addons here are built on the device, so the vulnerability
   comparison does not run for them yet (pipeline #90). Format:

   ```yaml
   "1.3.0":                       # the new version, quoted
     breaking:
       - change: option-removed   # change and key exactly as the report shows
         key: ssl_port            # schema path, e.g. database.port; the arch,
                                  # the port (8080/tcp) or `image`
         migration: Use the 443/tcp port mapping instead.
   ```

   Only sections newer than the latest formal Release and up to the new
   version count. `migration` must not be empty. The report prints a
   ready-to-paste entry for each finding. The release puts these entries on
   the GitHub Release under 破壞性變更與遷移方式. Full rules: the Woow_HA_App_Store
   README, section "升版比對與 `upgrade-notes.yaml`".
