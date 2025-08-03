#!/usr/bin/env python3
"""
search_album_youtube.py

Recherche les meilleures vidéos ou playlists YouTube correspondant à
un album, avec filtrage par type (full album, live, cover, react).

pip install youtube-search-python "httpx<0.24"

Usage :
    # recherche simple
    python search_album_youtube.py \
        --album "Metallica - Master of Puppets (1986)" \
        --type full \
        --out results.txt

    # recherche en batch
    python search_album_youtube.py \
        --file albums.txt \
        --type live
"""

import argparse
import pathlib
import sys
from datetime import timedelta
from typing import List, Dict, Tuple

from youtubesearchpython import VideosSearch, PlaylistsSearch


# ------------------------------------------------------------
# Utils
# ------------------------------------------------------------
EXCLUDE_FOR_FULL = ("live", "cover", "reaction", "react", "tribute", "rehearsal")
DURATION_THRESHOLD_MINUTES = (
    25  # en-dessous on suppose que ce n’est pas un album complet
)


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Cherche albums complets sur YouTube (vidéos ou playlists)."
    )
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--album", help='Ex : "Artist - Album (1986)"')
    g.add_argument(
        "--file", type=pathlib.Path, help="Fichier texte, un album par ligne"
    )

    ap.add_argument(
        "--type",
        choices=["full", "live", "cover", "react"],
        default="full",
        help="Type de recherche (défaut : full)",
    )
    ap.add_argument(
        "--out",
        type=pathlib.Path,
        default=pathlib.Path("youtube_album_results.txt"),
        help="Fichier où écrire les résultats",
    )
    return ap.parse_args()


def clean_duration(s: str) -> int:
    """
    '1:05:33' -> 3933 secondes
    '38:17'   -> 2297 secondes
    ''        -> 0
    """
    if not s:
        return 0
    parts = list(map(int, s.split(":")))
    if len(parts) == 3:
        h, m, s_ = parts
    elif len(parts) == 2:
        h, m, s_ = 0, *parts
    else:
        return 0
    return h * 3600 + m * 60 + s_


def is_result_valid(
    result: Dict, search_type: str, original_query: str
) -> Tuple[bool, str]:
    """Filtrer selon le type et la durée minimale."""
    title = result["title"].lower()
    duration_sec = clean_duration(result.get("duration", ""))
    # full album : bannir certains mots
    if search_type == "full" and any(k in title for k in EXCLUDE_FOR_FULL):
        return False, "Mot-clé exclu"
    # live / cover / react : doit contenir le mot-clé correspondant
    if search_type != "full" and search_type not in title:
        return False, f"'{search_type}' absent"
    if duration_sec and duration_sec < DURATION_THRESHOLD_MINUTES * 60:
        return False, "Durée trop courte"
    return True, ""


def search_one_album(query: str, search_type: str) -> List[Dict]:
    """
    Retourne les 3 meilleurs résultats pertinents (playlist ou vidéo).
    Stratégie :
        1. Rechercher des playlists qui contiennent le nom de l'album
        2. Compléter avec des vidéos si besoin
    """
    wanted = []

    # 1) Playlists
    playlist_search = PlaylistsSearch(f"{query} {search_type} album", limit=10)
    for p in playlist_search.result()["result"]:
        entry = {
            "link": p["link"],
            "title": p["title"],
            "duration": f'{p["videoCount"]} vidéos',
            "type": "playlist",
        }
        ok, _ = is_result_valid(entry, search_type, query)
        if ok:
            wanted.append(entry)
        if len(wanted) >= 3:
            break

    # 2) Vidéos
    if len(wanted) < 3:
        videos_search = VideosSearch(f"{query} {search_type} album", limit=20)
        for v in videos_search.result()["result"]:
            entry = {
                "link": v["link"],
                "title": v["title"],
                "duration": v.get("duration", ""),
                "type": "video",
            }
            ok, _ = is_result_valid(entry, search_type, query)
            if ok:
                wanted.append(entry)
            if len(wanted) >= 3:
                break

    return wanted[:3]


def process_queries(queries: List[str], search_type: str) -> Dict[str, List[Dict]]:
    all_results = {}
    for q in queries:
        q_clean = q.strip()
        if not q_clean:
            continue
        results = search_one_album(q_clean, search_type)
        all_results[q_clean] = results
    return all_results


def display_and_save(all_results: Dict[str, List[Dict]], outfile: pathlib.Path) -> None:
    """Affiche sur stdout et écrit un fichier plat."""
    with outfile.open("w", encoding="utf-8") as fh:
        for album, items in all_results.items():
            header = f"\n=== {album} ==="
            print(header)
            fh.write(header + "\n")
            if not items:
                msg = "  Aucun résultat pertinent trouvé."
                print(msg)
                fh.write(msg + "\n")
                continue
            for idx, it in enumerate(items, 1):
                line = f"  {idx}. {it['link']} | {it['title']} | {it['duration']}"
                print(line)
                fh.write(line + "\n")


# ------------------------------------------------------------
# Entrée script
# ------------------------------------------------------------
def main() -> None:
    args = parse_args()

    # Construire la liste de requêtes
    if args.album:
        queries = [args.album]
    else:
        if not args.file.exists():
            sys.exit(f"Fichier {args.file} introuvable.")
        queries = args.file.read_text(encoding="utf-8").splitlines()

    results = process_queries(queries, args.type)
    display_and_save(results, args.out)
    print(f"\nRésultats écrits dans {args.out.resolve()}")


if __name__ == "__main__":
    main()
