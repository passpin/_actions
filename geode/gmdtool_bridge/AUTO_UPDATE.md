# gmdtool Runtime Bridge — Self-Update (Windows, experimental)

The updater uses **public GitHub Releases**; no custom server and no Geode Index registration is required.
It does **not** update a running DLL in memory or alter game-tick timing.

## What it does

1. When entering the GD main menu (once per process), check
   `https://api.github.com/repos/passpin/for_build/releases/latest`.
2. Compare the release tag against the current mod version (stable semver only).
3. Download the exact asset named `gmdtool.runtime-bridge.geode` if newer.
4. Require a `sha256:<64 hex digits>` digest provided by the GitHub Releases API.
   The download size must match the release asset metadata (between 1 KiB and 32 MiB).
5. Inspect the downloaded `.geode` as a ZIP. Validate its `mod.json` ID, release
   version, GD Windows target and Geode SDK target. Reject invalid packages.
6. Stage it in the mod's save directory as `update-staged.geode.part`.
7. Show **Later / Restart** in English. Only on **Restart** does it attempt to
   back up and replace the `.geode` archive, then restart GD while saving data.

No independent updater process or background HTTP server is needed. The existing
local API bridge is separate and remains optional.

## Release requirements (for the AI that manages GitHub)

- Repository: `passpin/for_build` must be **public** (the GitHub API is used
  without a token). Private GitHub Releases will not work.
- Publish a new **non-draft, non-prerelease** GitHub Release with a tag such as
  `v0.1.5`; keep `mod.json.version` exactly equal to the tag.
- Attach ONE Windows `.geode` binary as a Release asset with exact name:
  `gmdtool.runtime-bridge.geode`
- The built mod's `mod.json` must contain:
  `id = gmdtool.runtime-bridge`, `geode = 5.9.0`, `gd.win = 2.2081`.
- The Release asset's REST API `digest` field must be populated with SHA-256
  (GitHub normally computes this for uploaded assets). Do not publish an update
  if the field is missing; the updater intentionally fails closed.
- The asset is the *compiled* `.geode`, not a GitHub Actions artifact ZIP, source
  ZIP, or renamed DLL. Do not overwrite old releases; create new versioned releases.
- Keep the `mod.json.version` synchronized with release tag on each build.
- The code does not modify the workflow or create releases. Add separate
  publishing automation in the repository to suit the above contract.

## Installation / operation

- Build v0.1.4 and install this version **once** manually. After that, new
  releases can be downloaded and verified without manual file replacement.
- Leave `Check for updates automatically` enabled in the mod settings.
- Open the GD main menu with internet access; the update check is asynchronous.
- On prompt: **Later** keeps the current version running. **Restart** backs up,
  installs and restarts. If the currently loaded package cannot be renamed,
  installation fails without replacing it.
- Your previous package is saved as `previous-version.geode.backup` in this
  mod's save directory, not in the Geode mods directory. It can be restored
  manually if the new version fails to load.
- Review Geode logs (`Updater:`) if updates aren't detected.

## Current limits / safety

- Windows only. The code is not tested in an actual Geode SDK Windows build
  in this environment; CI compilation and game testing are still needed.
- Checks when the main menu initializes, not continuously while playing.
- Requires a **public** Release with a compatible asset. GitHub API limits,
  offline periods, missing SHA-256, or malformed releases fail without install.
- Package swap is attempted on user approval, not before. No hot reloading.
- No rollback after a game restart if the *new* mod itself crashes; the backup
  remains available for manual recovery via Geode safe mode (hold Shift on launch).
- Does not verify the whole Geode archive's arbitrary executable behavior.
  Only install releases from the trusted repository.
