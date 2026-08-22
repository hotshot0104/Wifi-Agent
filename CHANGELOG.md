# Changelog

## 1.2.0 — 2026-08-22

### Highlights

- Added a first-run setup flow that collects portal credentials and completes
  login-time installation before revealing the management dashboard.
- Made the Windows connection settings vertically scrollable so Test
  Connection, Save, and installation controls remain accessible in compact or
  non-maximized windows.
- Added authenticated portal-session tracking. A confirmed Sophos/Cyberoam
  session now remains visibly connected when a public connectivity probe is
  blocked or inconclusive.
- Fixed macOS package post-install launching by opening the installed app bundle
  by filesystem path.
- Added native frozen-application startup self-tests to both Windows and macOS
  builders to prevent broken installers from being published.
- Changed installer automation so manual and tagged builds publish `.exe`,
  `.pkg`, and `.dmg` files as direct GitHub Release downloads.

### Packaging

- Windows: per-user x64 setup executable.
- macOS Apple silicon: PKG and DMG installers.
- macOS Intel: PKG and DMG installers.
- Version metadata updated to 1.2.0 throughout the application and installers.

### Validation

- 25 regression tests pass.
- Ruff, Python compilation, shell syntax, workflow YAML, and Tk interface smoke
  checks pass.

### Signing note

The repository currently has no Apple Developer ID or Windows signing secrets
configured. CI can therefore produce the release installers, but Windows may
show an unknown-publisher warning and macOS may require **Open Anyway** from
Privacy & Security. Configure the secrets documented in the README to enable
trusted signing and Apple notarization on a future rebuild.

## 1.1.0 — 2026-08-21

- Added native Windows and macOS packaging, tray/menu-bar management, signing
  hooks, and automated installer builds.

## 1.0.0 — 2026-08-21

- Initial WiFi Agent release.
