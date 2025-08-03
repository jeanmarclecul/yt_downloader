#!/usr/bin/env python3
"""
Écrit dans un fichier texte la liste des albums studio (par défaut) d’un artiste
sous la forme : « Nom Artiste - Nom Album (AAAA) ».

Usage :
    python albums.py "Nom de l'artiste"            # albums non‑live
    python albums.py "Nom de l'artiste" --live     # inclut les albums live

Options :
    -l, --live   Inclure aussi les release‑groups dont le type secondaire est « Live ».

Dépendance :
    pip install musicbrainzngs
"""

from __future__ import annotations
import argparse
import pathlib
import sys
import musicbrainzngs as mb


def get_artist_id(name: str) -> str | None:
    res = mb.search_artists(artist=name, limit=5)
    return res["artist-list"][0]["id"] if res["artist-list"] else None


def get_albums(artist_id: str, include_live: bool) -> list[tuple[str, str]]:
    rgs = mb.browse_release_groups(
        artist=artist_id,
        release_type="album",  # on veut uniquement les albums
        limit=200,  # 100 par défaut, on élargit un peu
    )["release-group-list"]

    seen = set()
    albums: list[tuple[str, str]] = []

    for rg in rgs:
        title = rg["title"]
        if title.lower() in seen:
            continue
        seen.add(title.lower())

        # Détecte si c’est un Live via les secondary types
        secondary = [t.lower() for t in rg.get("secondary-type-list", [])]
        is_live = "live" in secondary

        if is_live and not include_live:
            continue  # on ignore les albums live si l’option n’est pas activée

        year = (
            rg.get("first-release-date", "")[:4] if rg.get("first-release-date") else ""
        )
        albums.append((year, title))

    # Tri : année (si connue) puis titre
    albums.sort(key=lambda t: (t[0] or "9999", t[1].lower()))
    return albums


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Liste les albums d'un artiste dans un fichier texte."
    )
    parser.add_argument("artist", help="Nom de l'artiste à interroger")
    parser.add_argument(
        "-l", "--live", action="store_true", help="Inclure aussi les albums live"
    )
    args = parser.parse_args()

    mb.set_useragent("AlbumLister/1.4", "https://example.com", "email@example.com")

    artist_id = get_artist_id(args.artist)
    if not artist_id:
        print(f"Aucun artiste trouvé pour « {args.artist} »")
        sys.exit(1)

    albums = get_albums(artist_id, include_live=args.live)
    if not albums:
        print("Aucun album trouvé.")
        sys.exit(0)

    safe = "".join(c if c.isalnum() else "_" for c in args.artist.lower())
    path = pathlib.Path(f"albums_{safe}.txt")
    with path.open("w", encoding="utf-8") as f:
        for year, title in albums:
            line = f"{args.artist} - {title}"
            if year:
                line += f" ({year})"
            f.write(line + "\n")

    live_note = " (incluant Live)" if args.live else ""
    print(f"{len(albums)} albums{live_note} écrits dans {path.resolve()}")


if __name__ == "__main__":
    main()
