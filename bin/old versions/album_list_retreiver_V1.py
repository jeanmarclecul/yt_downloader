#!/usr/bin/env python3
"""
Écrit dans un fichier texte la liste des albums d’un artiste
sous la forme : « Nom Artiste - Nom Album (AAAA) ».

Usage :
    python albums.py "Nom de l'artiste"
Dépendance :
    pip install musicbrainzngs
"""

import sys
import pathlib
import musicbrainzngs as mb


def get_artist_id(artist_name: str) -> str | None:
    res = mb.search_artists(artist=artist_name, limit=5)
    return res["artist-list"][0]["id"] if res["artist-list"] else None


def get_albums(artist_id: str) -> list[tuple[str, str]]:
    release_groups = mb.browse_release_groups(
        artist=artist_id,
        release_type="album",
        limit=100,
    )["release-group-list"]

    seen = set()
    albums: list[tuple[str, str]] = []
    for rg in release_groups:
        title = rg["title"]
        if title.lower() in seen:
            continue
        seen.add(title.lower())
        date_full = rg.get("first-release-date", "")  # ex: "1999-03-15" ou "1999"
        year = date_full[:4] if len(date_full) >= 4 else ""  # on garde AAAA
        albums.append((year, title))

    # tri par année puis par titre
    albums.sort(key=lambda t: (t[0] or "9999", t[1].lower()))
    return albums  # [(year, title), …]


def main():
    if len(sys.argv) < 2:
        print('Usage: python albums.py "Nom de l\'artiste"')
        sys.exit(1)
    artist_name = sys.argv[1]

    mb.set_useragent("AlbumLister/1.3", "https://example.com", "email@example.com")

    artist_id = get_artist_id(artist_name)
    if not artist_id:
        print(f"Aucun artiste trouvé pour « {artist_name} »")
        sys.exit(1)

    albums = get_albums(artist_id)
    if not albums:
        print(f"Aucun album trouvé pour « {artist_name} »")
        sys.exit(0)

    safe = "".join(c if c.isalnum() else "_" for c in artist_name.lower())
    path = pathlib.Path(f"albums_{safe}.txt")
    with path.open("w", encoding="utf-8") as f:
        for year, title in albums:
            line = f"{artist_name} - {title}"
            if year:
                line += f" ({year})"
            f.write(line + "\n")

    print(f"{len(albums)} albums écrits dans {path.resolve()}")


if __name__ == "__main__":
    main()
