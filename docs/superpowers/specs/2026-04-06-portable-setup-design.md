# Portable Setup & Stateless Server Design

**Date:** 2026-04-06
**Status:** Approved

## Problem

The citibike-checker Lambda requires server-side config (`config.json`) with per-user API keys and station profiles. Adding a new user means editing the config and redeploying. Non-technical users can't set themselves up.

## Goal

Make the server stateless (profile config sent in each request) and provide a browser-based setup tool that lets non-technical users pick stations on a map and generate a ready-to-use Siri Shortcut config.

## Design Decisions

- **Target audience:** Non-technical people using Josh's deployed Lambda
- **Auth:** None. The server is a stateless proxy for public Citi Bike data.
- **Setup tool:** Static web app (hosted on GitHub Pages)
- **Shortcuts:** One Shortcut per profile (e.g., "Citi bike work docks"), each with its own hardcoded station config JSON
- **Station discovery:** Map with geolocation + address search

---

## Part 1: Stateless Lambda

Remove all server-side user config. The profile comes in the POST request body.

### New Request Format

Both `/citibike-check-english` (text) and `/citibike-check` (JSON) become POST endpoints:

```json
{
  "q": "docks",
  "profile": [
    {
      "name": "43rd and Madison",
      "id": "2af3ecc3-4f43-468a-a7cc-bb4804ee3e7a",
      "primary": true
    },
    {
      "name": "grand central",
      "primary": true,
      "stations": [
        {"id": "66dc8025-0aca-11e7-82f6-3863bb44ef7c", "name": "north"},
        {"id": "66dc7f02-0aca-11e7-82f6-3863bb44ef7c", "name": "south"}
      ]
    }
  ]
}
```

- `profile`: full station config array (same schema as a single profile in today's config.json)
- `q`: just `"docks"` or `"bikes"` (defaults to `"docks"` if omitted). No profile routing since each Shortcut is scoped to one profile.
- `type` param still works as an explicit override of `q`.
- Validation: return 400 if `profile` is missing or empty.
- All existing smart reporting logic (primary/backup thresholds, group collapsing, ebike prioritization) stays identical.

### Files to Change

- `src/lambda_app/handler.py` — remove auth, accept profile from body, simplify query parsing
- `src/lambda_app/config.py` — delete entirely (`get_all_station_ids` moves into handler)
- `template.yaml` — change `/citibike-check` from GET to POST, remove API key references
- `deploy.sh` — remove the `config.json` copy step
- `config.example.json` — delete (no longer used)

### Migration

Josh's current profiles are saved in `josh-profiles.json` (gitignored) for easy migration to the new request format.

---

## Part 2: Station Picker Web App

A single-page static web app for picking stations and generating Shortcut configs.

### Tech Stack

- Single `index.html` with inline CSS/JS (one file = simple deployment)
- Leaflet.js for the map (free, no API key, CDN)
- OpenStreetMap tiles (free)
- Nominatim geocoder for address search (free, no API key)
- Station data: `stations.json` bundled as a companion file alongside the web app. Station locations rarely change; a "last updated" note suffices.

### Map UX

1. Page loads with map centered on Manhattan
2. Browser geolocation prompt; recenters if accepted
3. Search box at top geocodes addresses via Nominatim, recenters map
4. All ~2300 stations shown as markers with Leaflet.markercluster for performance
5. Clicking a station marker adds it to the "Selected Stations" panel

### Selected Stations Panel

- Each station shows its Citi Bike name and a remove button
- Editable friendly display name (defaults to Citi Bike name)
- Checkbox for "primary" (checked by default)
- Drag-to-reorder or up/down buttons
- "Group" action: select 2+ stations, merge into a named group

### Profile Builder Flow

1. Pick stations on map
2. Name them, mark primary/backup, optionally group
3. Choose docks, bikes, or both (two Shortcuts)
4. Click "Generate"

---

## Part 3: Output & Shortcut Setup

When the user clicks "Generate," the app produces:

### 1. JSON Payload

Displayed in a copyable code block:

```json
{
  "q": "docks",
  "profile": [ ... ]
}
```

### 2. Step-by-Step Shortcut Instructions

1. Open Shortcuts app, tap "+" to create new Shortcut
2. Name it (e.g., "Citi bike work docks")
3. Add "Get Contents of URL":
   - URL: `https://<api-url>/prod/citibike-check-english`
   - Method: POST
   - Headers: `Content-Type: application/json`
   - Request Body: JSON — paste the payload
4. Add "Speak Text" — speak the result
5. Done

### 3. Base Shortcut Template

A pre-built Shortcut shared via iCloud link. User installs it, then replaces the placeholder JSON body with their generated config. This is the lowest-friction path since Apple doesn't support programmatic Shortcut generation.

### 4. Optional Voice-Routed Variant

Instructions for a single Shortcut using Dictate Text to switch between docks/bikes:
- Dictate Text → if contains "bike" set q to "bikes", else "docks"
- Same POST + Speak

---

## Part 4: Hosting

GitHub Pages from the `docs/` folder on `main` branch.

- URL: `https://joshlebed.github.io/citibike-checker/`
- Zero cost, auto-deploys on push
- The Lambda URL is displayed on the setup page (configurable for forks)

The `docs/` folder contains:
- `index.html` — the station picker app
- `stations.json` — bundled station data

Note: `*.html` is currently in `.gitignore` and will need to be excluded from that rule for `docs/` files.

---

## Part 5: Cleanup

- **Delete:** `config.example.json`, `src/lambda_app/config.py`
- **Simplify:** `deploy.sh` (remove config copy)
- **Keep:** `data/stations.json` (source for web app bundle), `scripts/find_nearby_stations.py` (dev tool)
- **Add:** `josh-profiles.json` (gitignored, Josh's current station configs for migration)
- **Update:** `.gitignore` (add `josh-profiles.json`, allow `docs/*.html`)
- **Rewrite:** `README.md` to reflect new setup flow

---

## Non-Goals

- Programmatic `.shortcut` file generation (Apple's format is signed/proprietary)
- User accounts, server-side storage, or databases
- Rate limiting (add later if abuse becomes a problem)
- Supporting bike systems other than Citi Bike
