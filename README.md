# WiFi Agent

## Download version 1.2.0

Installers are available directly—no ZIP extraction or separate Python runtime
is required:

- [Windows 64-bit setup](https://github.com/akshajtiwari/Wifi-Agent/releases/download/v1.2.0/WiFiAgent-1.2.0-Windows-x64-Setup.exe)
- [Apple silicon Mac package](https://github.com/akshajtiwari/Wifi-Agent/releases/download/v1.2.0/WiFiAgent-1.2.0-macOS-arm64.pkg)
- [Intel Mac package](https://github.com/akshajtiwari/Wifi-Agent/releases/download/v1.2.0/WiFiAgent-1.2.0-macOS-x86_64.pkg)
- [All installers and release notes](https://github.com/akshajtiwari/Wifi-Agent/releases/tag/v1.2.0)

WiFi Agent is a lightweight, cross-platform background service for networks
using a Sophos or Cyberoam captive portal. It monitors wired connectivity,
checks whether the portal is reachable, verifies real internet access, and
automatically restores or keeps alive an authenticated session.

## Features

- Supports Windows, macOS, and Linux.
- Distinguishes Ethernet, portal-port, and internet status.
- Logs in only when Ethernet is connected and internet access is unavailable.
- Stores passwords in the operating system credential vault—never in project
  files or `config.json`.
- Provides a native management dashboard with live health cards, grouped
  settings, startup controls, and a copyable diagnostics/log viewer.
- Provides a macOS menu-bar item and Windows notification-area icon for
  day-to-day management.
- Starts automatically at user login and restarts after failures.
- Prevents duplicate monitor instances and uses bounded exponential retry
  backoff when a portal or upstream connection is unhealthy.

## Requirements

- Native installer: no separate Python installation is required
- Source/script installation: Python 3.10 or newer
- An unlocked OS credential vault: Windows Credential Manager, macOS Keychain,
  or a Linux Secret Service provider
- On some Linux distributions, the `python3-tk` package

## Installation

### Native installers

Download the installer matching the computer from the GitHub release:

- **Windows 64-bit:** run `WiFiAgent-<version>-Windows-x64-Setup.exe`. The
  per-user installer does not require administrator access and opens the secure
  settings window when it finishes.
- **Apple silicon Mac:** open the `arm64` `.pkg` or `.dmg`.
- **Intel Mac:** open the `x86_64` `.pkg` or `.dmg`.

The macOS package installs **WiFi Agent.app** in `/Applications` and opens its
settings for the signed-in user. The disk image offers the familiar alternative
of dragging **WiFi Agent.app** into **Applications** and opening it once.

On first opening, WiFi Agent shows only the initial credential and connection
setup. Enter the portal credentials and settings, select the correct Ethernet
adapter if automatic detection is unsuitable, choose **Test Connection**, then
choose **Save & Install at Login** on macOS or **Save & install** on Windows.
This stores the password in the operating-system credential vault, activates
the login-time agent, and then reveals the live dashboard.

### Script installation

The source-based installers remain available for development and Linux. On
Windows, double-click `install.cmd` or run:

```powershell
.\install.ps1
```

On macOS or Linux, run:

```sh
./install.sh
```

The dashboard's **Overview** tab (**General** on macOS) shows live Ethernet,
portal-port, internet, process, and startup health. **Settings** (**Connection**
on macOS) manages credentials and retry policy, while **Diagnostics** provides
a safe status snapshot and recent logs without including the saved password.

On Windows, installation starts a WiFi Agent icon in the notification area of
the taskbar. Click it to open settings, or right-click it to check and
log in immediately, pause/resume monitoring, open logs, or exit until the next
Windows login. The command script is only needed for the initial installation
or troubleshooting.

On macOS, installation creates a menu-bar item with live status, Check Now,
pause/resume, Settings, Diagnostics, logs, and Quit commands. The macOS settings
window uses the native Aqua theme, system appearance and accent colors,
pane-specific titles, fixed settings-window sizing, remembered panes, and the
standard Command–Comma, Command–S, and Command–W shortcuts. Choosing **Quit
WiFi Agent** keeps it closed for the rest of the login session; it starts again
at the next login.

The script installer creates an isolated runtime in the user's application-data
directory. Native installers bundle their runtime inside the installed app, so
neither installation method depends on the downloaded project folder afterward.

## Management

Native-installer users can manage the agent from its menu-bar/taskbar icon and
settings window. For a source installation, pass a command through the platform
installer:

```sh
./install.sh setup       # Change credentials or settings
./install.sh run         # Run interactively
./install.sh run --once  # Run one diagnostic/login cycle
./install.sh check       # Ask the running agent to check immediately
./install.sh status      # Display live state and recent logs
./install.sh doctor      # Validate configuration, vault, and startup
./install.sh open-logs   # Open the log location
./install.sh install     # Reinstall and start the startup service
./install.sh uninstall   # Remove the service but retain settings
```

On Windows, use `install.cmd` with the same arguments.

## Development

Run the dependency-free regression suite with:

```sh
python -m unittest discover -s tests -v
```

### Building native installers

PyInstaller must run on the target operating system; it does not cross-compile
Windows and macOS applications. Install the application and build dependencies
on the target machine first:

```sh
python -m pip install -r requirements.txt -r packaging/requirements-build.txt
```

On Windows, install Inno Setup 6 or 7 and run:

```powershell
.\packaging\windows\build-installer.ps1
```

On macOS, run:

```sh
./packaging/macos/build-installer.sh
```

Outputs are written beneath `build/windows/installer` or
`build/macos/installer`. The macOS builder produces both `.pkg` and `.dmg`
files. Set `MACOS_APP_SIGNING_IDENTITY`, `MACOS_INSTALLER_SIGNING_IDENTITY`,
and `APPLE_NOTARY_KEYCHAIN_PROFILE` to create Developer ID-signed and notarized
release artifacts; without them, the builder creates development artifacts.

The Windows builder similarly signs both the application executable and setup
executable when `WINDOWS_SIGNING_CERTIFICATE` points to a PFX file; provide its
password through `WINDOWS_SIGNING_PASSWORD`.

The **Build native installers** GitHub Actions workflow runs tests and builds a
Windows x64 installer plus separate Apple silicon and Intel macOS installers.
Every manual run publishes a prerelease page containing the `.exe`, `.pkg`, and
`.dmg` files as direct downloads instead of requiring users to extract Actions
artifact ZIPs. Pushing a version tag such as `v1.0.0` builds the installers and
attaches them to the corresponding GitHub release automatically.
When signing secrets are configured, workflow builds are signed and macOS
installers are notarized. Without them, CI clearly marks the build as unsigned
but still publishes testable installers. Configure these repository secrets for
trusted public distribution:

- `WINDOWS_CERTIFICATE_BASE64` and `WINDOWS_CERTIFICATE_PASSWORD`
- `MACOS_CERTIFICATE_BASE64` and `MACOS_CERTIFICATE_PASSWORD`
- `MACOS_APP_SIGNING_IDENTITY` and `MACOS_INSTALLER_SIGNING_IDENTITY`
- `APPLE_NOTARY_APPLE_ID`, `APPLE_NOTARY_PASSWORD`, and
  `APPLE_NOTARY_TEAM_ID`

## Security and startup

The password is stored through the system credential API. Non-secret settings
and the username are stored in the user's configuration directory. Portal-only
TLS verification can be relaxed for appliances using self-signed certificates;
internet probes continue to require trusted HTTPS certificates.

The monitor reloads changed settings without a restart, writes an atomic status
snapshot for the UI and CLI, rejects captive-portal redirects during internet
checks, and treats the portal's authenticated session response as authoritative
when a public connectivity probe is unavailable. It sanitizes portal responses
before logging and isolates unexpected cycle failures so one bad adapter or
request does not stop the service.

WiFi Agent starts when the user logs in rather than during pre-login boot,
because system credential vaults are normally locked before that point.
