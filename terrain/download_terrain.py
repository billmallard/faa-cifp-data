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
    EARTHDATA_TOKEN=your_password_or_bearer_token

Or pass on the command line:
    python download_terrain.py --region global --dest D:\\EarthData --user <u> --token <t>
"""

import argparse
import hashlib
import os
import sqlite3
import time
import urllib.parse
import zipfile
from pathlib import Path

import requests

# ---------------------------------------------------------------------------
# NASA EarthData SRTMGL3 V003 endpoint
# ---------------------------------------------------------------------------
SRTM3_BASE  = "https://e4ftl01.cr.usgs.gov/MEASURES/SRTMGL3.003/2000.02.11"
AUTH_HOST   = "urs.earthdata.nasa.gov"

# Pre-defined regional bounding boxes: (lat_min, lon_min, lat_max, lon_max)
REGIONS = {
    "global":        (-56, -180,  60,  180),
    "north_america": (  7, -168,  72,  -52),
    "south_america": (-56,  -82,  13,  -34),
    "europe":        ( 34,  -25,  72,   45),
    "africa":        (-35,  -18,  38,   52),
    "asia":          (  1,   26,  60,  150),
    "oceania":       (-47,  113, -10,  180),
}


# ---------------------------------------------------------------------------
# NASA EarthData session — keeps auth cookies across redirects
# ---------------------------------------------------------------------------

class EarthdataSession(requests.Session):
    """
    requests.Session subclass that correctly handles NASA EarthData's
    OAuth2 redirect flow. Credentials are sent to urs.earthdata.nasa.gov
    but stripped when redirected elsewhere for security.
    """
    def __init__(self, username: str, password: str):
        super().__init__()
        self.auth = (username, password)

    def rebuild_auth(self, prepared_request, response):
        headers = prepared_request.headers
        if "Authorization" in headers:
            original = urllib.parse.urlparse(response.request.url).hostname
            redirect = urllib.parse.urlparse(prepared_request.url).hostname
            if original != redirect and redirect != AUTH_HOST:
                del headers["Authorization"]


# ---------------------------------------------------------------------------
# Tile helpers
# ---------------------------------------------------------------------------

def tile_name(lat: int, lon: int) -> str:
    ns = "N" if lat >= 0 else "S"
    ew = "E" if lon >= 0 else "W"
    return f"{ns}{abs(lat):02d}{ew}{abs(lon):03d}"


def tiles_for_bbox(lat_min: float, lon_min: float, lat_max: float, lon_max: float):
    import math
    for lat in range(int(math.floor(lat_min)), int(math.floor(lat_max)) + 1):
        for lon in range(int(math.floor(lon_min)), int(math.floor(lon_max)) + 1):
            yield lat, lon


def tile_url(name: str) -> str:
    return f"{SRTM3_BASE}/{name}.SRTMGL3.hgt.zip"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# SQLite index
# ---------------------------------------------------------------------------

def open_index(index_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(index_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tiles (
            name          TEXT PRIMARY KEY,
            lat_min       INTEGER,
            lat_max       INTEGER,
            lon_min       INTEGER,
            lon_max       INTEGER,
            file_path     TEXT,
            file_size     INTEGER,
            sha256        TEXT,
            downloaded_at TEXT
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_bbox "
        "ON tiles(lat_min, lat_max, lon_min, lon_max)"
    )
    conn.commit()
    return conn


def tile_in_index(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM tiles WHERE name=?", (name,)
    ).fetchone() is not None


def record_tile(conn: sqlite3.Connection, name: str, lat: int, lon: int,
                file_path: Path, checksum: str):
    conn.execute("""
        INSERT OR REPLACE INTO tiles
            (name, lat_min, lat_max, lon_min, lon_max,
             file_path, file_size, sha256, downloaded_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
    """, (name, lat, lat + 1, lon, lon + 1,
          str(file_path), file_path.stat().st_size, checksum))
    conn.commit()


# ---------------------------------------------------------------------------
# Download a single tile
# ---------------------------------------------------------------------------

def download_tile(name: str, dest_dir: Path,
                  session: EarthdataSession) -> Path | None:
    """
    Download and unzip a single HGT tile.
    Returns the .hgt path on success, None if the tile does not exist
    (ocean / void — normal for SRTM3).
    """
    url = tile_url(name)
    zip_path  = dest_dir / f"{name}.hgt.zip"
    hgt_path  = dest_dir / f"{name}.hgt"

    try:
        resp = session.get(url, stream=True, timeout=60)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()

        with open(zip_path, "wb") as f:
            for chunk in resp.iter_content(65536):
                f.write(chunk)

        with zipfile.ZipFile(zip_path) as zf:
            hgt_names = [n for n in zf.namelist() if n.lower().endswith(".hgt")]
            if not hgt_names:
                return None
            zf.extract(hgt_names[0], dest_dir)
            extracted = dest_dir / hgt_names[0]
            if extracted != hgt_path:
                extracted.rename(hgt_path)

        return hgt_path

    except requests.exceptions.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            return None
        raise
    finally:
        if zip_path.exists():
            zip_path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Download SRTM3 terrain tiles for MakerPlane SVS"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--region", choices=list(REGIONS.keys()),
                       help="Predefined region")
    group.add_argument("--bbox", nargs=4, type=float,
                       metavar=("LAT_MIN", "LON_MIN", "LAT_MAX", "LON_MAX"),
                       help="Custom bounding box")
    parser.add_argument("--dest",   default=".",
                        help="Destination root directory (default: current dir)")
    parser.add_argument("--update", action="store_true",
                        help="Skip tiles already in index; re-download missing/corrupt only")
    parser.add_argument("--user",  default=os.environ.get("EARTHDATA_USER"),
                        help="NASA EarthData username (or set EARTHDATA_USER env var)")
    parser.add_argument("--token", default=os.environ.get("EARTHDATA_TOKEN"),
                        help="NASA EarthData password/token (or set EARTHDATA_TOKEN env var)")
    args = parser.parse_args()

    if not args.user or not args.token:
        parser.error(
            "NASA EarthData credentials required.\n"
            "Set EARTHDATA_USER and EARTHDATA_TOKEN environment variables,\n"
            "or pass --user and --token on the command line."
        )

    dest      = Path(args.dest)
    tile_root = dest / "srtm3"
    tile_root.mkdir(parents=True, exist_ok=True)
    index_path = dest / "terrain_index.db"

    bbox = REGIONS[args.region] if args.region else tuple(args.bbox)
    lat_min, lon_min, lat_max, lon_max = bbox

    session = EarthdataSession(args.user, args.token)
    conn    = open_index(index_path)

    all_tiles  = list(tiles_for_bbox(lat_min, lon_min, lat_max, lon_max))
    total      = len(all_tiles)
    downloaded = skipped = missing = failed = 0
    start_time = time.time()

    print(f"Region   : {args.region or 'custom bbox'}")
    print(f"Tiles    : {total:,} to check")
    print(f"Dest     : {tile_root}")
    print(f"Index    : {index_path}")
    print()

    for i, (lat, lon) in enumerate(all_tiles, 1):
        name    = tile_name(lat, lon)
        lat_dir = tile_root / f"{'N' if lat >= 0 else 'S'}{abs(lat):02d}"
        lat_dir.mkdir(exist_ok=True)
        hgt_path = lat_dir / f"{name}.hgt"

        if args.update and tile_in_index(conn, name) and hgt_path.exists():
            skipped += 1
            continue

        elapsed  = time.time() - start_time
        done     = downloaded + missing + failed
        rate     = done / elapsed if elapsed > 0 else 0
        remaining = total - i
        eta      = f"{remaining / rate:.0f}s" if rate > 0 else "?"
        print(f"[{i:>6}/{total}] {name}  dl:{downloaded}  skip:{skipped}"
              f"  void:{missing}  fail:{failed}  ETA:{eta}",
              end="\r", flush=True)

        try:
            result = download_tile(name, lat_dir, session)
            if result is None:
                missing += 1
            else:
                checksum = sha256_file(result)
                record_tile(conn, name, lat, lon, result, checksum)
                downloaded += 1
        except Exception as e:
            print(f"\n  FAILED {name}: {e}")
            failed += 1

    elapsed = time.time() - start_time
    print(f"\n\nFinished in {elapsed:.0f}s  ({elapsed/60:.1f} min)")
    print(f"  Downloaded : {downloaded:>6,}")
    print(f"  Skipped    : {skipped:>6,}  (already current)")
    print(f"  No data    : {missing:>6,}  (ocean/void — normal)")
    print(f"  Failed     : {failed:>6,}")
    print(f"  Index      : {index_path}")
    conn.close()


if __name__ == "__main__":
    main()
