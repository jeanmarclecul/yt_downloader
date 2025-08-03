#!/usr/bin/env python3
"""
youtube_album_search.py

Recherche les meilleures playlists et vidéos YouTube correspondant à un album
(spécifié individuellement ou via un fichier), puis affiche/écrit les résultats.

• Dépendances : google-api-python-client, isodate, python-dotenv (facultatif)
• Clé API     : placer YT_API_KEY dans l’environnement ou passer --api-key

Exemple :
    python youtube_album_search.py \
        --album "Iron Maiden - Powerslave (1984)" \
        --type full \
        --exclude-keywords "remaster,remastered" \
        --max-results 30 --top-n 5 --output results.txt
"""
import argparse
import os
import re
import sys
from datetime import timedelta
from typing import List, Tuple

import isodate
from googleapiclient.discovery import build

YOUTUBE_API_SERVICE_NAME = "youtube"
YOUTUBE_API_VERSION = "v3"


# ---------- Argument parsing -------------------------------------------------
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Cherche playlists et vidéos YouTube correspondant à un album."
    )
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--album", help="Artiste - Album (année optionnelle)")
    g.add_argument("--input-file", help="Fichier avec un album par ligne")

    p.add_argument(
        "--type",
        choices=["full", "live", "cover", "react"],
        default="full",
        help="Type de contenu privilégié",
    )
    p.add_argument(
        "--exclude-keywords",
        default="",
        help="Mots-clefs exclus (séparés par des virgules)",
    )
    p.add_argument("--max-results", type=int, default=25)
    p.add_argument("--top-n", type=int, default=5)
    p.add_argument("--output", default="results.txt")
    p.add_argument("--api-key", help="Clé API YouTube (écrase YT_API_KEY)")

    return p.parse_args()


# ---------- Helpers ----------------------------------------------------------
def clean_query(q: str) -> Tuple[str, str]:
    """Renvoie (original, nettoyé) – sans année ni tiret."""
    cleaned = re.sub(r"\(\d{4}\)", "", q).replace(" - ", " ").strip()
    return q.strip(), cleaned


def build_search_terms(album: str, kind: str) -> Tuple[str, List[str]]:
    inc, exc = [], []
    if kind == "full":
        inc.append("full album")
        exc += ["live", "cover", "reaction", "react", "tribute"]
    elif kind == "live":
        inc.append("live full concert")
        exc += ["cover", "reaction", "tribute"]
    elif kind == "cover":
        inc.append("cover full album")
        exc += ["live", "reaction", "tribute"]
    elif kind == "react":
        inc.append("reaction full album")

    return f"{album} {' '.join(inc)}", exc


def iso_to_hms(iso: str) -> str:
    try:
        td = isodate.parse_duration(iso)
        tot = int(td.total_seconds() if isinstance(td, timedelta) else td)
        h, r = divmod(tot, 3600)
        m, s = divmod(r, 60)
        return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
    except Exception:
        return "?"


def yt_client(key: str):
    return build(
        YOUTUBE_API_SERVICE_NAME,
        YOUTUBE_API_VERSION,
        developerKey=key,
        cache_discovery=False,
    )


def search_yt(yt, query: str, max_res: int, kind: str) -> List[dict]:
    return (
        yt.search()
        .list(q=query, part="id,snippet", maxResults=max_res, type=kind)
        .execute()
        .get("items", [])
    )


def durations_for(yt, vids: List[dict]) -> None:
    ids = [v["id"]["videoId"] for v in vids]
    for chunk in (ids[i : i + 50] for i in range(0, len(ids), 50)):
        resp = (
            yt.videos()
            .list(id=",".join(chunk), part="contentDetails")
            .execute()
            .get("items", [])
        )
        iso = {v["id"]: v["contentDetails"]["duration"] for v in resp}
        for v in vids:
            if (vid := v["id"]["videoId"]) in iso:
                v["duration"] = iso_to_hms(iso[vid])


def filter_items(items: List[dict], excl: List[str]) -> List[dict]:
    excl = [e.lower() for e in excl]
    return [
        it for it in items if not any(k in it["snippet"]["title"].lower() for k in excl)
    ]


def line_for(item: dict, kind: str) -> str:
    if kind == "video":
        url = f"https://www.youtube.com/watch?v={item['id']['videoId']}"
        dur = item.get("duration", "?")
    else:
        url = f"https://www.youtube.com/playlist?list={item['id']['playlistId']}"
        dur = "N/A"
    return f"{url}\t{dur}\t{item['snippet']['title']}"


# ---------- Main workflow ----------------------------------------------------
def one_album(
    yt,
    album_query: str,
    kind: str,
    max_res: int,
    top_n: int,
    extra_excl: List[str],
) -> List[str]:
    out = [f"==== {album_query} ===="]
    q, auto_excl = build_search_terms(album_query, kind)
    excl = auto_excl + extra_excl

    # Vidéos
    vids = search_yt(yt, q, max_res, "video")
    durations_for(yt, vids)
    vids = filter_items(vids, excl)[:top_n]

    # Playlists
    pls = search_yt(yt, q, max_res, "playlist")
    pls = filter_items(pls, excl)[:top_n]

    out += ["-- Videos --", *[line_for(v, "video") for v in vids]]
    out += ["-- Playlists --", *[line_for(p, "playlist") for p in pls], ""]
    return out


def main() -> None:
    args = parse_args()
    key = args.api_key or os.getenv("YT_API_KEY")
    if not key:
        sys.exit("Erreur : fournissez une clé API via --api-key ou YT_API_KEY")

    yt = yt_client(key)
    extra_excl = [e.strip() for e in args.exclude_keywords.split(",") if e.strip()]

    albums = (
        [args.album]
        if args.album
        else [l.strip() for l in open(args.input_file, encoding="utf-8") if l.strip()]
    )

    lines: List[str] = []
    for alb in albums:
        raw, cleaned = clean_query(alb)
        res = one_album(yt, raw, args.type, args.max_results, args.top_n, extra_excl)
        if len(res) <= 3:  # rien trouvé ? on réessaie sans l'année
            res = one_album(
                yt, cleaned, args.type, args.max_results, args.top_n, extra_excl
            )
        lines += res

    with open(args.output, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print("\n".join(lines))


if __name__ == "__main__":
    main()
