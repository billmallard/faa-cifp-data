# faa-cifp-data Requirements

This document defines requirements for the faa-cifp-data navigation data management
project. The original scope covers FAA CIFP procedure data; this document extends
that scope to include terrain elevation and obstacle data management, making this
project the single place where MakerPlane avionics operators prepare and maintain
all off-board navigation and terrain datasets.

## Requirement IDs

Format: `NAVDATA-<AREA>-<NNN>`

---

### Project Scope

- **NAVDATA-SCOPE-001:** The project shall manage three categories of avionics navigation data: (1) FAA CIFP procedure/waypoint data (existing), (2) SRTM3 terrain elevation tiles, (3) FAA Digital Obstacle File (DOF) tower/obstacle data.
- **NAVDATA-SCOPE-002:** All data management tools shall be cross-platform (Linux, macOS, Windows) so operators can prepare a microSD card or USB drive on any machine before mounting it in the aircraft.
- **NAVDATA-SCOPE-003:** Data prepared by these tools shall be readable directly by pyEfis and other MakerPlane avionics software without additional transformation steps on the target device.

---

### Terrain Tile Management (SRTM3)

- **NAVDATA-TERRAIN-001:** The project shall include a `download_terrain.py` tool that downloads NASA SRTMGL3 V003 (3 arc-second, 90 m) HGT tiles from the NASA EarthData HTTPS endpoint or a configurable mirror URL.
- **NAVDATA-TERRAIN-002:** The downloader shall support regional download scopes: `global` (all 14,297 land tiles, ~13.6 GB), `north_america`, `south_america`, `europe`, `africa`, `asia`, `oceania`, and arbitrary bounding-box (`--bbox lat_min lon_min lat_max lon_max`).
- **NAVDATA-TERRAIN-003:** Downloaded tiles shall be stored in a standard directory hierarchy: `<tile_path>/srtm3/N<NN>/<tile>.hgt` where tiles follow SRTM naming convention (e.g., `N32W097.hgt` for the tile covering 32°N–33°N, 97°W–96°W).
- **NAVDATA-TERRAIN-004:** The downloader shall verify each tile with a checksum (SHA-256 or MD5 from NASA manifest) and re-download on mismatch. Partially downloaded files shall be detected and resumed.
- **NAVDATA-TERRAIN-005:** The downloader shall produce a SQLite index file (`terrain_index.db`) alongside the tiles recording: tile filename, bounding box (lat_min, lat_max, lon_min, lon_max), file size, checksum, and download timestamp. This index enables fast tile lookup by the pyEfis SVS renderer without filesystem scanning.
- **NAVDATA-TERRAIN-006:** The full global dataset (13.6 GB) shall fit on a 32 GB microSD card alongside CIFP data and the operating system. A 64 GB card is the recommended minimum for a complete installation including future obstacle data. The documentation shall state these storage requirements explicitly.
- **NAVDATA-TERRAIN-007:** The downloader shall support `--update` mode that checks existing tiles against the index and downloads only missing or corrupted tiles, enabling incremental maintenance without full re-download (terrain data changes rarely but NASA occasionally reprocesses voids).
- **NAVDATA-TERRAIN-008:** Progress reporting shall show per-tile download progress, total bytes downloaded vs. expected, estimated time remaining, and a final summary of tiles downloaded, skipped, and failed.

---

### Obstacle Data Management (FAA DOF)

- **NAVDATA-OBSTACLE-001:** The project shall include a `download_obstacles.py` tool that downloads the FAA Digital Obstacle File (DOF) from the FAA aeronav server.
- **NAVDATA-OBSTACLE-002:** The DOF parser shall extract: obstacle position (lat/lon), height AGL (ft), height MSL (ft), obstacle type (tower, building, stack, etc.), lighting status, and horizontal accuracy code.
- **NAVDATA-OBSTACLE-003:** Parsed obstacle data shall be stored in a SQLite database (`obstacles.db`) with a spatial index (R-tree or bounding-box grid) enabling fast lookup by bounding box for a given flight area.
- **NAVDATA-OBSTACLE-004:** The FAA publishes DOF updates on a 56-day cycle; the `download_obstacles.py` tool shall record the publication date and warn when the data is older than 56 days.
- **NAVDATA-OBSTACLE-005:** The obstacle database shall record only obstacles with a height MSL greater than a configurable minimum (default 200 ft AGL) to limit database size while retaining relevant hazards.

---

### CIFP Data Management (Existing — Formalised)

- **NAVDATA-CIFP-001:** The existing `download.py` script shall be retained and renamed `download_cifp.py` for naming consistency with the new tools; a top-level `download_all.py` convenience script shall invoke all three downloaders in sequence.
- **NAVDATA-CIFP-002:** CIFP data shall continue to be published on the 28-day AIRAC cycle with current and next-cycle databases as per existing behaviour.

---

### Deployment

- **NAVDATA-DEPLOY-001:** A `prepare_sd.py` tool (or equivalent documentation) shall guide operators through partitioning and formatting a microSD card, mounting it, and running all three downloaders targeting the card's mount point.
- **NAVDATA-DEPLOY-002:** All tools shall accept a `--dest` argument specifying the root of the data destination (microSD mount point, USB path, or local directory), defaulting to the current working directory.
- **NAVDATA-DEPLOY-003:** The README shall document the recommended directory structure, storage requirements, hardware-specific mount paths for Raspberry Pi and x86 platforms, and the fstab entries needed for automatic mounting at boot.

---

## Notes

- NASA EarthData access for SRTMGL3 requires a free account and bearer token. The downloader shall document the one-time registration step and support token storage in a local config file (not committed to the repository).
- The FAA DOF is a public dataset requiring no authentication.
- Terrain data changes infrequently (years between NASA reprocessing); obstacle data should be refreshed every 56 days in line with FAA publication cycles.
