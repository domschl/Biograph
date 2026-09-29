# Arch Linux Packaging for Biograph

This directory contains `PKGBUILD` scripts to package Biograph components for Arch Linux.

## Packages Included

1. **`biograph-backend`**: Installs the FastAPI backend server (`biograph-server`), mounts the static web client assets in `/usr/share/biograph/web-client`, and sets up a systemd system service (`biograph-backend.service`) running under a dedicated `biograph` system user.
2. **`biograph-cli`**: Installs the `bio` CLI query and note-taking utility.
3. **`biograph-sensor-shell`**: Installs the `biograph-sensor-shell` daemon and a system-wide systemd user service (`biograph-shell.service`) configured to execute the system binary.

## How to Build and Install

To build any of the packages locally:

1. Navigate to the package subdirectory:
   ```bash
   cd packaging/arch/biograph-backend # or biograph-cli, biograph-sensor-shell
   ```

2. Compile and package using `makepkg` (pass `-i` to install the resulting package with `pacman`):
   ```bash
   makepkg -si
   ```

*Note: The PKGBUILDs are configured to pull source dynamically from the main Git repository branch. Ensure you have network access or pre-fetched packages.*

## Running the Backend as a System Service

The `biograph-backend` package sets up a systemd system-level service.

1. **Configure**:
   Edit `/etc/biograph/config.toml` to change the secret token and settings. The package installation sets this file to be owned by `root:biograph` with `0640` permissions so only root and the `biograph` daemon user can read the API token.
   
2. **Start the Service**:
   Enable and start the service system-wide:
   ```bash
   sudo systemctl enable --now biograph-backend.service
   ```

3. **Check Logs**:
   ```bash
   journalctl -u biograph-backend.service -f
   ```

*Note: The database is automatically initialized and persisted at `/var/lib/biograph/biograph.db` (which is automatically managed via the systemd `StateDirectory=biograph` directive).*

