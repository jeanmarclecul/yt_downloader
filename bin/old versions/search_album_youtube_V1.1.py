#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
search_album_youtube.py
-----------------------

Petit utilitaire CLI pour trouver des playlists ou vidéos YouTube
correspondant à un album, filtré par type (full, live, cover, react).

Dépendances (sans clé API) :
    pip install "youtube-search-python" "httpx<0.24"

Exemples :
    # recherche auto (playlists prioritaires)
    python search_album_youtube.py --album "The Warning - ERROR (2022)" --type full

    # même requête mais uniquement en vidéos longues
    python search_album_youtube.py --album "The Warning - ERROR (2022)" --type full --mode video

    # batch
    python search_album_youtube.py --file albums.txt --type live --mode playlist
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys
from typing import Dict, List

from youtubesearchpython import PlaylistsSearch, VideosSearch

# --------------------------------------------------------------------------- #
#  Paramètres globaux                                                         #
# --------------------------------------------------------------------------- #
EXCLUDE_FOR_FULL = (
    " live ",
    " cover ",
    " reaction ",
    " react ",
    " tribute ",
    " review ",
)
DURATION_THRESHOLD_MINUTES = 25


# --------------------------------------------------------------------------- #
#  Helpers                                                                    #
# --------------------------------------------------------------------------- #
def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Recherche d'albums sur YouTube.")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--album", help='Titre complet : "Artiste - Album (année)"')
    src.add_argument(
        "--file", type=pathlib.Path, help="Fichier texte, un album par ligne"
    )

    ap.add_argument(
        "--type",
        choices=["full", "live", "cover", "react"],
        default="full",
        help="Type recherché (défaut : full)",
    )
    ap.add_argument(
        "--mode",
        choices=["auto", "playlist", "video"],
        default="auto",
        help="Source de recherche : playlists, vidéos, ou auto (défaut)",
    )
    ap.add_argument(
        "--out",
        type=pathlib.Path,
        default=pathlib.Path("youtube_album_results.txt"),
        help="Fichier texte de sortie",
    )
    return ap.parse_args()


def clean_duration(s: str) -> int:
    if not s:
        return 0
    parts = [int(x) for x in s.split(":")]
    if len(parts) == 3:
        h, m, sec = parts
    elif len(parts) == 2:
        h, m, sec = 0, *parts
    else:
        return 0
    return h * 3600 + m * 60 + sec


def is_valid(result: Dict, search_type: str) -> bool:
    title_low = f" {result['title'].lower()} "

    if search_type == "full":
        if any(k in title_low for k in EXCLUDE_FOR_FULL):
            return False
    else:
        if search_type not in title_low:
            return False

    if result["type"] == "video":
        if clean_duration(result.get("duration", "")) < DURATION_THRESHOLD_MINUTES * 60:
            return False

    return True


# --------------------------------------------------------------------------- #
#  Recherche                                                                  #
# --------------------------------------------------------------------------- #
def search_playlists(query: str, search_type: str, limit: int = 50) -> List[Dict]:
    wanted: List[Dict] = []
    ps = PlaylistsSearch(f"{query} {search_type} album", limit=limit)
    for p in ps.result().get("result", []):
        entry = {
            "link": p["link"],
            "title": p["title"],
            "duration": f'{p["videoCount"]} vidéos',
            "type": "playlist",
        }
        if is_valid(entry, search_type):
            wanted.append(entry)
        if len(wanted) >= 3:
            break
    return wanted


def search_videos(query: str, search_type: str, limit: int = 30) -> List[Dict]:
    wanted: List[Dict] = []
    vs = VideosSearch(f"{query} {search_type} album", limit=limit)
    for v in vs.result().get("result", []):
        entry = {
            "link": v["link"],
            "title": v["title"],
            "duration": v.get("duration", ""),
            "type": "video",
        }
        if is_valid(entry, search_type):
            wanted.append(entry)
        if len(wanted) >= 3:
            break
    return wanted


def search_one_album(query: str, search_type: str, mode: str) -> List[Dict]:
    if mode == "playlist":
        return search_playlists(query, search_type)
    if mode == "video":
        return search_videos(query, search_type)

    # mode auto : playlists d'abord, vidéos ensuite
    results = search_playlists(query, search_type)
    if len(results) < 3:
        results.extend(search_videos(query, search_type))
    return results[:3]


# --------------------------------------------------------------------------- #
#  Pipeline                                                                   #
# --------------------------------------------------------------------------- #
def process(queries: List[str], search_type: str, mode: str) -> Dict[str, List[Dict]]:
    return {q: search_one_album(q, search_type, mode) for q in queries if q.strip()}


def display(res: Dict[str, List[Dict]], outfile: pathlib.Path) -> None:
    with outfile.open("w", encoding="utf-8") as fh:
        for album, items in res.items():
            hdr = f"\n=== {album} ==="
            print(hdr)
            fh.write(hdr + "\n")

            if not items:
                msg = "  Aucun résultat pertinent trouvé."
                print(msg)
                fh.write(msg + "\n")
                continue

            for idx, it in enumerate(items, 1):
                line = f"  {idx}. {it['link']} | {it['title']} | {it['duration']}"
                print(line)
                fh.write(line + "\n")
    print(f"\nRésultats écrits dans {outfile.resolve()}")


# --------------------------------------------------------------------------- #
#  Entrée                                                                      #
# --------------------------------------------------------------------------- #
def main() -> None:
    args = parse_args()

    if args.album:
        queries = [args.album.strip()]
    else:
        if not args.file.exists():
            sys.exit(f"Fichier introuvable : {args.file}")
        queries = [
            l.strip() for l in args.file.read_text(encoding="utf-8").splitlines()
        ]

    res = process(queries, args.type, args.mode)
    display(res, args.out)


if __name__ == "__main__":
    main()
