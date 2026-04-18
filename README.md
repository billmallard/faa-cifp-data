# FAA CIFP Data Package

**Status:** Open Source — Experimental Amateur-Built Category  
**License:** Build tooling is open source; CIFP data is FAA public data (see FAA disclaimers in the data zip)  
**Distribution:** Snap package on snapcraft.io (`faa-cifp-data`)

---

## What This Is

This repository contains the build tooling to package **FAA CIFP (Coded Instrument Flight Procedures) data** as a Snap content package for consumption by [pyEfis](../pyEfis) and other MakerPlane/MAOS avionics software.

CIFP is the FAA's machine-readable database of:
- **Instrument approach procedures** (ILS, RNAV/GPS, VOR, NDB approaches for every airport with an instrument approach)
- **Standard Instrument Departures (SIDs)**
- **Standard Terminal Arrivals (STARs)**
- **Airways** (Victor airways, jet routes, RNAV Q/T routes)
- **Waypoints, fixes, VORs, NDBs** with geographic coordinates
- **Airport reference data**

This data is published by the FAA on a 28-day AIRAC cycle. This package builder fetches the current cycle (and optionally the next cycle) and packages them so that pyEfis can render **Virtual VFR**, approach plate overlays, and IFR navigation context on the moving map display.

## How It Works

The `download.py` script:
1. Fetches the current `FAACIFP18` file from the FAA
2. Builds an `index.bin` for fast spatial lookups
3. Packages both as a Snap content provider with a `metadata.yaml` containing the expiration date of the current cycle
4. Optionally includes the next AIRAC cycle as `next.db`/`next.bin` so the display transitions seamlessly at cycle rollover

pyEfis reads `metadata.yaml` and automatically loads `current.db` or `next.db` based on the system date.

## Data Contents (Filed as)

| File | Description |
|---|---|
| `current.db` | FAA CIFP18 database for the current AIRAC cycle |
| `current.bin` | Spatial index for fast procedure/waypoint lookup |
| `next.db` | Next AIRAC cycle data (if available at build time) |
| `next.bin` | Spatial index for next cycle |
| `metadata.yaml` | Cycle expiration dates for automatic handoff logic |

## Installation

### As a Snap (Easiest)

If using the pyEfis snap, this data snap is connected automatically:

```bash
sudo snap install faa-cifp-data
```

### Within pyEfis Configuration

Point your screen definition at the data path:

```yaml
metadata: /usr/share/makerplane/CIFP/metadata.yaml
```

### Building From Source

```bash
python download.py
```

Requires network access to FAA data servers. See `download.py` for authentication and URL configuration.

## Role in the MakerPlane / MAOS Ecosystem

This is the **IFR navigation database** for the MAOS avionics stack. It enables:

- Rendering instrument approach procedure courses on the [pyAvMap](../pyAvMap) moving map
- Waypoint identification by name (fixes, VORs, NDBs, airports)
- Airway routing for IFR flight planning
- Procedure depiction during approach briefing

For an IFR-capable MAOS cockpit, this data package (refreshed every 28 days) is a required component alongside pyEfis and pyAvMap.

## Important Disclaimer

> FAA CIFP data is provided as a convenience for Experimental Amateur-Built aircraft use.  
> This data must **not** be used as a primary navigation source for IFR flight without verification against current official FAA publications.  
> See the FAA disclaimer included in the CIFP data download for full terms of use.  
> The FAA publishes updated CIFP data every 28 days; operators are responsible for maintaining current data.


## Using the snap
### pyefis
Simply install the pyefis snap from the snapcraft.io store, this snap will be downloaded automatically and connected. You may need to edit your configuration files to update the path to the CIFP data.
Within your screen definition these settings will work when running the pyefis snap:
```
    metadata: /usr/share/makerplane/CIFP/metadata.yaml
```
It is safe to leave the `dbpath` and `indexpath` settings in place, if metadata.yaml exists it will be used, otherwise pyefis will try using `dbpath` and `indexpath`

### Consuming from your custom snap
If you want to include this within your custom snap you will first add a plug to your snapcraft.yaml:
```
plugs:
  faa-cifp-data:
    interface : content
    target: $SNAP/faa-cifp-data
    default-provider: faa-cifp-data
```

From within your snap the data is accessible at the path `$SNAP/faa-cifp-data/CIFP`
If you do not want to use `$SNAP` to reference the the data you can update your layout and add a symbolic link in your snapcraft.yaml:
```
layout:
  /my/custom/path/CIFP:
    symlink: $SNAP/faa-cifp-data/CIFP
```
Makerplane snaps that consume this content will use `/usr/share/makerplane/CIFP` for `/my/custom/path/CIFP`
If we implement other sets of FAA data such as DOF for obsticles, that data could be symlinked as `/usr/share/makerplane/DOF` providing a consistent predictable path for accessing data.


After building and installing your snap you will need to connect it to the faa-cifp-snap:
```
snap connect mynap:faa-cifp-data faa-cifp-data
```
Snaps published by makerplane, such as pyefis, will perform this step automatically.

Now you can access the data from within the snap using `/my/custom/path/CIFP`


