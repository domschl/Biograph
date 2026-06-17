# Biograph Kodi Media Logger

This service add-on for Kodi automatically logs movie playback events to your Biograph timeline.

## Features

- **Automatic Logging:** Watches playback in the background. Logs an event as soon as a movie finishes naturally or when manually stopped after watching 85% or more of the runtime.
- **Rich Metadata:** Captures movie Title, Release Year, IMDb ID, duration (in seconds), play progress (%), and watch status.
- **Zero Config:** Automatically reads your Biograph server URL and API token from your system's existing `~/.config/biograph/config.toml` file.

## Installation

You can install this add-on in Kodi in one of two ways:

### Option 1: Direct File Copy (Recommended for local setups)
Since Kodi and your CLI are on the same machine (or you want to copy the directory manually), copy the `service.biograph` directory directly into Kodi's addons folder:

**Linux:**
```bash
mkdir -p ~/.kodi/addons/
cp -r service.biograph ~/.kodi/addons/
```

**macOS:**
```bash
mkdir -p ~/Library/Application\ Support/Kodi/addons/
cp -r service.biograph ~/Library/Application\ Support/Kodi/addons/
```

Then restart Kodi or enable it via:
**Settings ➔ Add-ons ➔ My Add-ons ➔ Services ➔ Biograph Media Logger ➔ Enable**.


### Option 2: Install from ZIP
If you want to install it on a remote Kodi box:
1. Zip the `service.biograph` folder:
   ```bash
   zip -r service.biograph.zip service.biograph
   ```
2. Transfer the `.zip` file to your Kodi device.
3. In Kodi, go to **Settings ➔ System ➔ Add-ons** and enable **Unknown sources**.
4. Go to **Settings ➔ Add-ons ➔ Install from zip file** and select `service.biograph.zip`.

## Verification & Logs

The add-on logs standard debug and info lines to the Kodi log file. You can monitor it using:

```bash
tail -f ~/.kodi/temp/kodi.log | grep Biograph
```
