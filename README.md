# WiFi Agent

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

- Python 3.10 or newer
- An unlocked OS credential vault: Windows Credential Manager, macOS Keychain,
  or a Linux Secret Service provider
- On some Linux distributions, the `python3-tk` package

## Installation

On Windows, double-click `install.cmd` or run:

```powershell
.\install.ps1
```

On macOS or Linux, run:

```sh
./install.sh
```

Enter the portal credentials and settings, select the correct Ethernet adapter
if automatic detection is unsuitable, choose **Test Connection**, then choose
**Save & Install at Login** on macOS or **Save & install** on Windows and Linux.

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

The installer creates an isolated runtime in the user's application-data
directory. The downloaded project folder can be moved or removed afterward.

## Management

Pass a command through the platform installer:

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

## Security and startup

The password is stored through the system credential API. Non-secret settings
and the username are stored in the user's configuration directory. Portal-only
TLS verification can be relaxed for appliances using self-signed certificates;
internet probes continue to require trusted HTTPS certificates.

The monitor reloads changed settings without a restart, writes an atomic status
snapshot for the UI and CLI, rejects captive-portal redirects during internet
checks, sanitizes portal responses before logging, and isolates unexpected
cycle failures so one bad adapter or request does not stop the service.

WiFi Agent starts when the user logs in rather than during pre-login boot,
because system credential vaults are normally locked before that point.
