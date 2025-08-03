#!/usr/bin/env python3
"""
albums.py  –  v1.5
Liste les albums (studio par défaut) d'un artiste dans un fichier texte :
« Nom Artiste - Nom Album (AAAA) »

Usage :
    python albums.py "Nom de l'artiste"          # albums studio uniquement
    python albums.py "Nom de l'artiste" --live   # ajoute les albums live
    python albums.py --mbid 7f625f35-...         # force l'artiste via son MBID

Options :
  -l, --live        Inclure les albums Live
  --mbid <ID>       MBID MusicBrainz de l'artiste (court‑circuite la recherche)
Dépendance :
  pip install musicbrainzngs
"""

from __future__ import annotations
import argparse
import pathlib
import sys
import musicbrainzngs as mb


# ---------------------------------------------------------------------------
# Recherche / sélection de l'artiste
# ---------------------------------------------------------------------------


def find_artist_id(name: str) -> str | None:
    """
    Recherche un artiste dont le nom correspond exactement à 'name'
    (casse ignorée). S'il n'y en a pas, renvoie l'ID du 1er résultat.
    """
    res = mb.search_artists(query=f'artist:"{name}"', limit=25)

    if not res["artist-list"]:
        return None

    # Candidats dont le nom correspond exactement
    exact = [a for a in res["artist-list"] if a["name"].lower() == name.lower()]
    if exact:
        # on prend celui qui a le meilleur score MusicBrainz
        exact.sort(key=lambda a: int(a.get("ext:score", "0")), reverse=True)
        return exact[0]["id"]

    # Fallback : premier résultat tout court
    return res["artist-list"][0]["id"]


# ---------------------------------------------------------------------------
# Récupération des albums
# ---------------------------------------------------------------------------


def get_albums(artist_id: str, include_live: bool) -> list[tuple[str, str]]:
    """
    Renvoie une liste [(année, titre), …] des release‑groups de type 'Album'.
    - Par défaut on exclut ceux dont le type secondaire est 'Live'.
    - 'include_live=True' ajoute ces albums live.
    """
    rgs = mb.browse_release_groups(
        artist=artist_id,
        release_type="album",  # albums (les EP ne sont donc pas inclus)
        limit=200,
    )["release-group-list"]

    seen = set()
    albums: list[tuple[str, str]] = []

    for rg in rgs:
        title = rg["title"]
        if title.lower() in seen:  # dédoublonnage
            continue
        seen.add(title.lower())

        # filtre Live
        secondary = [t.lower() for t in rg.get("secondary-type-list", [])]
        is_live = "live" in secondary
        if is_live and not include_live:
            continue

        year = rg.get("first-release-date", "")[:4]  # AAAA ou vide
        albums.append((year, title))

    albums.sort(key=lambda t: (t[0] or "9999", t[1].lower()))
    return albums


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Génère un fichier texte listant les albums d'un artiste."
    )
    parser.add_argument("artist", nargs="?", help="Nom de l'artiste")
    parser.add_argument(
        "-l", "--live", action="store_true", help="Inclure les albums live"
    )
    parser.add_argument("--mbid", help="MBID MusicBrainz de l'artiste")
    args = parser.parse_args()

    if not args.artist and not args.mbid:
        parser.error("indiquez un nom d'artiste ou --mbid.")

    mb.set_useragent("AlbumLister/1.5", "https://example.com", "email@example.com")

    # Sélection de l'artiste
    artist_id: str | None
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

    safe = "".join(c if c.isalnum() else "_" for c in artist_name.lower())
    path = pathlib.Path(f"albums_{safe}.txt")
    with path.open("w", encoding="utf-8") as f:
        for year, title in albums:
            line = f"{artist_name} - {title}"
            if year:
                line += f" ({year})"
            f.write(line + "\n")

    tag = " (incluant Live)" if args.live else ""
    print(f"✅  {len(albums)} album(s){tag} écrit(s) dans {path.resolve()}")


if __name__ == "__main__":
    main()
