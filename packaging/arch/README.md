# Arch Linux Packaging for Biograph

This directory contains `PKGBUILD` scripts to package Biograph components for Arch Linux.

## Packages Included

1. **`biograph-backend`**: Installs the FastAPI backend server (`biograph-server`) and mounts the static web client assets in `/usr/share/biograph/web-client`.
2. **`biograph-cli`**: Installs the `bio` CLI query and note-taking utility.
3. **`biograph-sensor-zsh`**: Installs the `biograph-sensor-zsh` daemon and a system-wide systemd user service (`biograph-zsh.service`) configured to execute the system binary.

## How to Build and Install

To build any of the packages locally:

1. Navigate to the package subdirectory:
   ```bash
   cd packaging/arch/biograph-backend # or biograph-cli, biograph-sensor-zsh
   ```

2. Compile and package using `makepkg` (pass `-i` to install the resulting package with `pacman`):
   ```bash
   makepkg -si
   ```

*Note: The PKGBUILDs are configured to pull source dynamically from the main Git repository branch. Ensure you have network access or pre-fetched packages.*
