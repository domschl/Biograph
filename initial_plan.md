## Overview

The 'Biograph' project keeps a journal of a (single) user's activities over time.
It consists of:
- a backend that journals events in the user's life
- multiple 'sensors' that run on different devices, collecting events in the user's life and relaying them to the backend
- a web client that allows browsing the history of events

### Examples of events collected via sensors

#### Intial phase

- 'Sensor' monitors changes in zsh history file: each command in history (which contains time-stamps) generates an event: (timestamp, ev-type: 'shell-cmd', origin: <hostname>, content: <cmd>)
- 'Sensor' monitors web browser (First: chrome only, if easier?). Each visited website generates an event: (timestamp, ev-type: 'website', origin: <hostname>/<browser-type>, content: <url>)
- 'Sensor' monitors Amazon Kindle connection and exports read books and highlights
- Logger: command-line tool to create an event

#### Later phase (not initially implemented)

- Photo libraries (via resource-links to photos)
- Email and chat history
- Kodi integration (movies watched)
- Mobile phone sensors (location, activity, log-function for user)
- Emacs integration

## Backend

- REST based SQlite server: CRUD, Filter/Search, export/import
- Token is used for auth, configured in config file (single user app)
- Optional SSL support (REST clients must support self-signed certs via configurable cert authority provided)
- Simple single-table database layout:

Events:

timestamp: time
ev-type: string
origin: string
content: JSON

- Import/Export tools
- Backup tool

## Clients

- Sensors (see above for start)
- Web client to search and browse events
