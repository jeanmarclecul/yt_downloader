import argparse
import re
import os
from typing import List, Dict
from yt_dlp import YoutubeDL
from datetime import timedelta

# --- Configuration ---
DEFAULT_MAX_RESULTS = 20
DEFAULT_TOP_RESULTS = 5
BLACKLIST_KEYWORDS = {
    "full": [
        "live",
        "cover",
        "reaction",
        "react",
        "tribute",
        "interview",
        "trailer",
        "teaser",
        "remix",
    ],
    "live": ["cover", "reaction", "react", "tribute"],
    "cover": ["reaction", "react"],
    "react": [],
}

# --- Argparse avec --help enrichi ---
parser = argparse.ArgumentParser(
    description="Recherche des albums sur YouTube (vidéos ou playlists) avec ou sans clé API.\n\n"
    "🔧 Dépendances requises :\n"
    " - yt-dlp\n"
    " - google-api-python-client (optionnel sauf si usage API)\n\n"
    "💡 Exemples :\n"
    "  python youtube_album_search.py --album 'The Warning - ERROR (2022)' --type full --no-api\n"
    "  python youtube_album_search.py --file albums.txt --type live",
    formatter_class=argparse.RawTextHelpFormatter,
)
group = parser.add_mutually_exclusive_group(required=True)
group.add_argument(
    "--album", help="Titre de l'album : 'Artiste - Nom Album (année optionnelle)')"
)
group.add_argument("--file", help="Fichier texte avec un album par ligne")
parser.add_argument(
    "--type",
    choices=["full", "live", "cover", "react"],
    required=True,
    help="Type de recherche",
)
parser.add_argument(
    "--max-results",
    type=int,
    default=DEFAULT_MAX_RESULTS,
    help="Nombre max de résultats analysés",
)
parser.add_argument(
    "--top", type=int, default=DEFAULT_TOP_RESULTS, help="Nombre de résultats affichés"
)
parser.add_argument(
    "--no-api", action="store_true", help="Utiliser yt-dlp sans API key"
)
parser.add_argument("--output", default="results.txt", help="Fichier de sortie")
args = parser.parse_args()


# --- Formatage durée ---
def format_duration(seconds: int) -> str:
    return str(timedelta(seconds=seconds))


# --- Nettoyage du titre ---
def clean_title(title: str) -> str:
    title = re.sub(r"\(\d{4}\)", "", title)  # Remove (year)
    title = title.replace("-", " ")
    return re.sub(r"\s+", " ", title).strip()


# --- yt-dlp wrapper corrigé ---
def search_youtube_yt_dlp(query: str, max_results: int) -> List[Dict]:
    ydl_opts = {
        "quiet": True,
        "skip_download": True,
        "default_search": f"ytsearch{max_results}",
        "dump_single_json": True,
        "format": "bestaudio/best",
    }
    with YoutubeDL(ydl_opts) as ydl:
        try:
            result = ydl.extract_info(query, download=False)
            entries = result.get("entries", [])
            return [
                {
                    "title": entry.get("title"),
                    "url": entry.get("url"),
                    "duration": entry.get("duration"),
                    "webpage_url": entry.get("webpage_url"),
                    "type": (
                        "playlist"
                        if "playlist" in entry.get("webpage_url", "")
                        else "video"
                    ),
                }
                for entry in entries
                if entry
            ]
        except Exception as e:
            print(f"Erreur yt-dlp : {e}")
            return []


# --- Filtrage par mots-clés ---
def filter_results(results: List[Dict], mode: str) -> List[Dict]:
    blacklist = BLACKLIST_KEYWORDS.get(mode, [])
    filtered = []
    for r in results:
        title = r.get("title", "").lower()
        if any(bad in title for bad in blacklist):
            continue
        if "single" in title:
            continue
        if r.get("duration", 0) < 900:
            continue  # Moins de 15 min = probablement un single
        filtered.append(r)
    return filtered


# --- Recherche ---
def process_album(
    title: str, search_type: str, max_results: int, top_n: int, no_api: bool
):
    query = clean_title(title)
    search_query = f"{query} {search_type} album"

    print(f"\n🔍 Recherche pour : {query} ({search_type})")

    results = search_youtube_yt_dlp(search_query, max_results)

    playlists = [r for r in results if r.get("type") == "playlist"]
    videos = [r for r in results if r.get("type") == "video"]

    filtered_playlists = filter_results(playlists, search_type)[:top_n]
    filtered_videos = filter_results(videos, search_type)[:top_n]

    # Affichage
    def show_section(name: str, section: List[Dict]):
        print(f"\n📂 {name}")
        for i, r in enumerate(section, 1):
            duration = (
                format_duration(r.get("duration", 0)) if r.get("duration") else "??:??"
            )
            print(f"{i}. {r['title']} [{duration}]\n   {r.get('webpage_url', '')}")

    show_section("Playlists", filtered_playlists)
    show_section("Vidéos", filtered_videos)

    return {
        "album": query,
        "search_type": search_type,
        "playlists": filtered_playlists,
        "videos": filtered_videos,
    }


# --- Traitement principal ---
def main():
    entries = []

    if args.album:
        entries.append(args.album)
    elif args.file:
        if not os.path.exists(args.file):
            print(f"❌ Fichier introuvable : {args.file}")
            return
        with open(args.file, "r", encoding="utf-8") as f:
            entries = [line.strip() for line in f if line.strip()]

    results = []
    for entry in entries:
        res = process_album(entry, args.type, args.max_results, args.top, args.no_api)
        results.append(res)

    # Sauvegarde fichier
    with open(args.output, "w", encoding="utf-8") as f:
        for res in results:
            f.write(f"\n=== {res['album']} ({res['search_type']}) ===\n")
            for section in ["playlists", "videos"]:
                f.write(f"\n{section.upper()}:\n")
                for r in res[section]:
                    duration = (
                        format_duration(r.get("duration", 0))
                        if r.get("duration")
                        else "??:??"
                    )
                    f.write(
                        f"- {r['title']} [{duration}]\n  {r.get('webpage_url', '')}\n"
                    )
    print(f"\n✅ Résultats enregistrés dans {args.output}")


if __name__ == "__main__":
    main()
