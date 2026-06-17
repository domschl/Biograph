# Chrome Web Store Listing — Biograph Web Sensor

> Last Updated: 2026-06-17

## Store Listing

**Extension Name**
Biograph Web Sensor

**Short Description**
Automatically journals your browser visits as web-visit events on your Biograph timeline.

**Detailed Description**
Biograph Web Sensor is a companion browser extension for the self-hosted Biograph personal life-logging tool. It monitors your web browsing activity and logs page visits directly to your local Biograph server.

Key Features:
- Automatic logging of HTTP and HTTPS website visits.
- Offline buffering: events are safely queued in local browser storage if your server is unreachable or offline.
- Batch upload: pending events are automatically flushed in batches once the connection is restored.
- Pending count badge displayed directly on the extension icon.
- Customisable device/host name to easily identify which machine logged the event on your timeline.

How to use:
1. Open the Extension Options page.
2. Enter your self-hosted Biograph Server URL (e.g., http://127.0.0.1:8000) and Access Token.
3. Customise the device name (e.g., "macbook-chrome").
4. Click Save. The extension will automatically log subsequent web visits.

Privacy & Security:
All logs are stored locally or sent directly to your self-hosted Biograph server. No data is sent to the extension developers or any third-party analytics services.

**Category**
Productivity

**Single Purpose**
Automatically logs web page titles and URLs to a self-hosted Biograph server.

**Primary Language**
English

## Graphics & Assets

| Asset | Dimensions | Status | Filename |
|-------|-----------|--------|----------|
| Store Icon | 128×128 PNG | ⬜ Not created | Omitted in source (browser default icon is used) |
| Screenshot 1 | 1280×800 or 640×400 | ⬜ Not created | |

## Permissions Justification

| Permission | Type | Justification |
|------------|------|---------------|
| `storage` | permissions | Required to store the server URL, auth token, and device name configurations, and to queue offline events locally when the server is down. |
| `tabs` | permissions | Required to read the URL and page title of completed tab updates to generate event payloads. |
| `<all_urls>` | host_permissions | Required to send HTTP requests to user-configured self-hosted server URLs, which can be located on localhost, local network IPs, or custom domains. |

## Privacy & Data Use

### Data Collection

**Does the extension collect user data?** Yes (collected local-only and sent solely to the user's self-hosted server)

| Data Type | Collected? | Transmitted Off-Device? | Purpose | Shared with Third Parties? |
|-----------|-----------|------------------------|---------|---------------------------|
| Authentication info | Yes | Yes (only to user's server) | To authenticate with the user's Biograph API. | No |
| Web history | Yes | Yes (only to user's server) | To log visited URLs and page titles to the user's timeline. | No |

### Data Use Certification
- [x] Data is NOT sold to third parties
- [x] Data is NOT used for purposes unrelated to the extension's core functionality
- [x] Data is NOT used for creditworthiness or lending purposes

## Privacy Policy

**Privacy Policy URL**
https://github.com/user/biograph/blob/main/browser-extension/PRIVACY.md

## Distribution

**Visibility**: Public
**Regions**: All regions
**Pricing**: Free

## Developer Info

**Publisher Name**
Biograph Project

**Contact Email**
developer@example.com

## Version History

| Version | Date | Changes | Status |
|---------|------|---------|--------|
| 0.1.0 | 2026-06-17 | Initial Manifest V3 release with tab tracking, local buffer queue, and batch flusher. | Draft |

## Review Notes

### Known Issues / Limitations
- Relies on tab complete status which might exclude tracking some instant redirections.
