"""
SRTM3 terrain tile downloader for MakerPlane avionics.

Downloads NASA SRTMGL3 V003 (3 arc-second / 90m) HGT tiles and builds a
SQLite spatial index for fast lookup by pyEfis SVS renderer.

Usage:
    python download_terrain.py --region north_america --dest /media/sdcard
    python download_terrain.py --region global --dest /media/sdcard
    python download_terrain.py --bbox 25 -125 50 -65 --dest /media/sdcard
    python download_terrain.py --region north_america --dest /media/sdcard --update

NASA EarthData account required. Set credentials via environment variables:
    EARTHDATA_USER=your_username
    EARTHDATA_TOKEN=your_bearer_token

Or store them in ~/.netrc:
    machine urs.earthdata.nasa.gov login <user> password <token>
"""

import argparse
import hashlib
import os
import sqlite3
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

# ---------------------------------------------------------------------------
# NASA EarthData SRTMGL3 V003 endpoint
# Tile URL pattern: https://e4ftl01.cr.usgs.gov/MEASURES/SRTMGL3.003/2000.02.11/<TILE>.SRTMGL3.hgt.zip
# ---------------------------------------------------------------------------
SRTM3_BASE = "https://e4ftl01.cr.usgs.gov/MEASURES/SRTMGL3.003/2000.02.11"

# Pre-defined regional bounding boxes: (lat_min, lon_min, lat_max, lon_max)
REGIONS = {
    "global":        (-56,  -180,  60,  180),
    "north_america": (  7,  -168,  72,  -52),
    "south_america": (-56,   -82,  13,  -34),
    "europe":        ( 34,   -25,  72,   45),
    "africa":        (-35,   -18,  38,   52),
    "asia":          (  1,    26,  60,  150),
    "oceania":       (-47,   113, -10,  180),
}


def tile_name(lat: int, lon: int) -> str:
    """Return the SRTM HGT tile name for the 1°×1° tile whose SW corner is (lat, lon)."""
    ns = "N" if lat >= 0 else "S"
    ew = "E" if lon >= 0 else "W"
    return f"{ns}{abs(lat):02d}{ew}{abs(lon):03d}"


def tiles_for_bbox(lat_min: float, lon_min: float, lat_max: float, lon_max: float):
    """Yield (lat, lon) SW-corner integers for all tiles overlapping the bounding box."""
    for lat in range(int(lat_min), int(lat_max) + 1):
        for lon in range(int(lon_min), int(lon_max) + 1):
            yield lat, lon


def tile_url(name: str) -> str:
    return f"{SRTM3_BASE}/{name}.SRTMGL3.hgt.zip"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def open_index(index_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(index_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tiles (
            name      TEXT PRIMARY KEY,
            lat_min   INTEGER,
            lat_max   INTEGER,
            lon_min   INTEGER,
            lon_max   INTEGER,
            file_path TEXT,
            file_size INTEGER,
            sha256    TEXT,
            downloaded_at TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_bbox ON tiles(lat_min, lat_max, lon_min, lon_max)")
    conn.commit()
    return conn


def tile_in_index(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute("SELECT sha256 FROM tiles WHERE name=?", (name,)).fetchone()
    return row is not None


def record_tile(conn: sqlite3.Connection, name: str, lat: int, lon: int,
                file_path: Path, checksum: str):
    conn.execute("""
        INSERT OR REPLACE INTO tiles
            (name, lat_min, lat_max, lon_min, lon_max, file_path, file_size, sha256, downloaded_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
    """, (name, lat, lat + 1, lon, lon + 1, str(file_path), file_path.stat().st_size, checksum))
    conn.commit()


def download_tile(name: str, dest_dir: Path, auth_handler) -> Path | None:
    """
    Download and unzip a single HGT tile. Returns the .hgt path on success, None if
    the tile does not exist at the server (ocean / void tile — normal for SRTM3).
    """
    url = tile_url(name)
    zip_path = dest_dir / f"{name}.hgt.zip"
    hgt_path = dest_dir / f"{name}.hgt"

    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req) as resp, open(zip_path, "wb") as out:
            total = int(resp.headers.get("Content-Length", 0))
            downloaded = 0
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                out.write(chunk)
                downloaded += len(chunk)
        # Unzip the single HGT file inside
        import zipfile
        with zipfile.ZipFile(zip_path) as zf:
            hgt_names = [n for n in zf.namelist() if n.endswith(".hgt")]
            if not hgt_names:
                zip_path.unlink(missing_ok=True)
                return None
            zf.extract(hgt_names[0], dest_dir)
            extracted = dest_dir / hgt_names[0]
            if extracted != hgt_path:
                extracted.rename(hgt_path)
        zip_path.unlink(missing_ok=True)
        return hgt_path

    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None   # ocean / no-data tile — expected
        raise
    finally:
        if zip_path.exists():
            zip_path.unlink(missing_ok=True)


def setup_auth(user: str | None, token: str | None):
    """Install a password manager for NASA EarthData authentication."""
    if user and token:
        mgr = urllib.request.HTTPPasswordMgrWithDefaultRealm()
        mgr.add_password(None, "https://urs.earthdata.nasa.gov", user, token)
        handler = urllib.request.HTTPBasicAuthHandler(mgr)
        opener = urllib.request.build_opener(handler)
        urllib.request.install_opener(opener)


def main():
    parser = argparse.ArgumentParser(description="Download SRTM3 terrain tiles for MakerPlane SVS")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--region", choices=list(REGIONS.keys()), help="Predefined region")
    group.add_argument("--bbox", nargs=4, type=float, metavar=("LAT_MIN", "LON_MIN", "LAT_MAX", "LON_MAX"),
                       help="Custom bounding box")
    parser.add_argument("--dest", default=".", help="Destination root directory (default: current dir)")
    parser.add_argument("--update", action="store_true",
                        help="Skip tiles already in index; re-download only missing/corrupt")
    parser.add_argument("--user", default=os.environ.get("EARTHDATA_USER"),
                        help="NASA EarthData username (or set EARTHDATA_USER env var)")
    parser.add_argument("--token", default=os.environ.get("EARTHDATA_TOKEN"),
                        help="NASA EarthData bearer token (or set EARTHDATA_TOKEN env var)")
    args = parser.parse_args()

    dest = Path(args.dest)
    tile_root = dest / "srtm3"
    tile_root.mkdir(parents=True, exist_ok=True)
    index_path = dest / "terrain_index.db"

    if args.region:
        bbox = REGIONS[args.region]
    else:
        bbox = tuple(args.bbox)

    lat_min, lon_min, lat_max, lon_max = bbox

    setup_auth(args.user, args.token)
    conn = open_index(index_path)

    all_tiles = list(tiles_for_bbox(lat_min, lon_min, lat_max, lon_max))
    total = len(all_tiles)
    downloaded = skipped = missing = failed = 0
    start_time = time.time()

    print(f"Region: {args.region or 'custom bbox'}")
    print(f"Tiles to check: {total}")
    print(f"Destination: {tile_root}")
    print(f"Index: {index_path}")
    print()

    for i, (lat, lon) in enumerate(all_tiles, 1):
        name = tile_name(lat, lon)
        lat_dir = tile_root / f"{'N' if lat >= 0 else 'S'}{abs(lat):02d}"
        lat_dir.mkdir(exist_ok=True)
        hgt_path = lat_dir / f"{name}.hgt"

        if args.update and tile_in_index(conn, name) and hgt_path.exists():
            skipped += 1
            continue

        elapsed = time.time() - start_time
        rate = (downloaded + missing) / elapsed if elapsed > 0 else 0
        remaining = total - i
        eta = f"{remaining / rate:.0f}s" if rate > 0 else "?"
        print(f"[{i}/{total}] {name}  ETA:{eta}", end="\r", flush=True)

        try:
            result = download_tile(name, lat_dir, None)
            if result is None:
                missing += 1  # ocean/void tile — normal
            else:
                checksum = sha256_file(result)
                record_tile(conn, name, lat, lon, result, checksum)
                downloaded += 1
        except Exception as e:
            print(f"\n  FAILED {name}: {e}")
            failed += 1

    elapsed = time.time() - start_time
    print(f"\n\nComplete in {elapsed:.0f}s")
    print(f"  Downloaded: {downloaded}")
    print(f"  Skipped (already current): {skipped}")
    print(f"  No data (ocean/void): {missing}")
    print(f"  Failed: {failed}")
    print(f"  Index: {index_path}")
    conn.close()


if __name__ == "__main__":
    main()
