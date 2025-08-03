#!/usr/bin/env python3
"""
albums.py  –  v1.6
Génère un fichier texte listant les albums d'un artiste puis, après séparation,
les chansons de chaque album, chacune sur sa propre ligne et indentée.

Format du fichier :
    Artiste - Album (AAAA)
    ...
    --------------------
    Artiste - Album (AAAA)
        Titre 1
        Titre 2
        ...

Usage :
    python albums.py "Nom de l'artiste"            # albums studio uniquement
    python albums.py "Nom de l'artiste" --live     # ajoute les albums live
    python albums.py --mbid <MBID>                 # force l'artiste via son MBID

Options :
  -l, --live        Inclure les albums Live
  --mbid <ID>       MBID MusicBrainz de l'artiste

Dépendance :
  pip install musicbrainzngs
"""

from __future__ import annotations
import argparse
import pathlib
import sys
import time
from typing import Dict, List, Tuple

import musicbrainzngs as mb


# ---------------------------------------------------------------------------
# Recherche / sélection de l'artiste
# ---------------------------------------------------------------------------


def find_artist_id(name: str) -> str | None:
    """
    Recherche un artiste dont le nom correspond exactement à 'name'
    (casse ignorée). Si rien ne correspond, renvoie l'ID du 1er résultat.
    """
    res = mb.search_artists(query=f'artist:"{name}"', limit=25)

    if not res["artist-list"]:
        return None

    # Candidats dont le nom correspond exactement
    exact = [a for a in res["artist-list"] if a["name"].lower() == name.lower()]

    if exact:
        # On prend celui qui a le meilleur score MusicBrainz
        exact.sort(key=lambda a: int(a.get("ext:score", "0")), reverse=True)
        return exact[0]["id"]

    # Fallback : premier résultat tout court
    return res["artist-list"][0]["id"]


# ---------------------------------------------------------------------------
# Récupération des albums
# ---------------------------------------------------------------------------

AlbumInfo = Dict[str, str]  # keys: title, year, rgid
TrackDict = Dict[str, List[str]]  # rgid -> [track titles]


def get_albums(artist_id: str, include_live: bool) -> List[AlbumInfo]:
    """
    Renvoie une liste d'albums (dict title/year/rgid).
    - Par défaut on exclut ceux dont le type secondaire est 'Live'.
    - 'include_live=True' ajoute ces albums live.
    """
    rgs = mb.browse_release_groups(
        artist=artist_id,
        release_type="album",
        limit=200,
    )["release-group-list"]

    seen = set()
    albums: List[AlbumInfo] = []

    for rg in rgs:
        title = rg["title"]
        if title.lower() in seen:
            continue
        seen.add(title.lower())

        secondary = [t.lower() for t in rg.get("secondary-type-list", [])]
        is_live = "live" in secondary
        if is_live and not include_live:
            continue

        year = rg.get("first-release-date", "")[:4]  # AAAA ou vide
        albums.append({"title": title, "year": year, "rgid": rg["id"]})

    albums.sort(key=lambda d: (d["year"] or "9999", d["title"].lower()))
    return albums


# ---------------------------------------------------------------------------
# Récupération des pistes pour chaque album
# ---------------------------------------------------------------------------


def choose_release(releases: List[dict]) -> dict:
    """
    Dans la liste de releases d'un même release-group, tente de choisir la plus
    pertinente : d'abord 'Official', sinon la première.
    """
    for rel in releases:
        if rel.get("status", "").lower() == "official":
            return rel
    return releases[0]


def get_tracks_for_release_group(rgid: str) -> List[str]:
    """
    Renvoie la liste (ordonnée) des titres de pistes d'un release-group.
    """
    # 1. Trouver une release représentative
    rels = mb.browse_releases(
        release_group=rgid,
        includes=[],
        limit=25,
    )["release-list"]

    if not rels:
        return []

    release = choose_release(rels)
    release_id = release["id"]

    # 2. Récupérer les pistes de cette release
    rel_data = mb.get_release_by_id(release_id, includes=["recordings"])
    tracks: List[str] = []
    for medium in rel_data["release"].get("medium-list", []):
        for track in medium.get("track-list", []):
            tracks.append(track["recording"]["title"])

    return tracks


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Génère un fichier texte listant albums et chansons d'un artiste."
    )
    parser.add_argument("artist", nargs="?", help="Nom de l'artiste")
    parser.add_argument(
        "-l", "--live", action="store_true", help="Inclure les albums live"
    )
    parser.add_argument("--mbid", help="MBID MusicBrainz de l'artiste")
    args = parser.parse_args()

    if not args.artist and not args.mbid:
        parser.error("indiquez un nom d'artiste ou --mbid.")

    mb.set_useragent("AlbumLister/1.6", "https://example.com", "email@example.com")

    # Sélection de l'artiste
    if args.mbid:
        artist_id = args.mbid
        artist_name = args.artist or "Artiste"
    else:
        artist_name = args.artist
        artist_id = find_artist_id(artist_name)

    if not artist_id:
        print("❌  Artiste introuvable.")
        sys.exit(1)

    albums = get_albums(artist_id, include_live=args.live)
    if not albums:
        print("⚠️  Aucun album trouvé.")
        sys.exit(0)

    # Récupération des pistes (avec respect des limites API)
    print("⏳  Téléchargement des listes de pistes…")
    tracks_by_rg: TrackDict = {}
    for idx, alb in enumerate(albums, 1):
        tracks_by_rg[alb["rgid"]] = get_tracks_for_release_group(alb["rgid"])
        time.sleep(1)  # MusiqueBrainz recommande 1 requête/s
        print(
            f"  • {idx}/{len(albums)} {alb['title']} ({len(tracks_by_rg[alb['rgid']])} pistes)"
        )

    # Écriture du fichier
    safe = "".join(c if c.isalnum() else "_" for c in artist_name.lower())
    path = pathlib.Path(f"albums_{safe}.txt")
    sep_line = "-" * 60

    with path.open("w", encoding="utf-8") as f:
        # Section 1 : albums
        for alb in albums:
            line = f"{artist_name} - {alb['title']}"
            if alb["year"]:
                line += f" ({alb['year']})"
            f.write(line + "\n")

        # Séparation
        f.write(sep_line + "\n")

        # Section 2 : albums + pistes
        for alb in albums:
            line = f"{artist_name} - {alb['title']}"
            if alb["year"]:
                line += f" ({alb['year']})"
            f.write(line + "\n")

            for track in tracks_by_rg.get(alb["rgid"], []):
                f.write(f"    {track}\n")
            f.write("\n")  # ligne blanche entre albums

    tag = " (incluant Live)" if args.live else ""
    print(f"✅  Fichier généré : {path.resolve()}{tag}")


if __name__ == "__main__":
    main()
