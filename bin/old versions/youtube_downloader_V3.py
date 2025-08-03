#!/usr/bin/env python3
# youtube_downloader.py
# Télécharge vidéos / playlists YouTube en MP3 ou MP4 — v2025‑07‑12

import argparse
import os
import re
import sys
import time
import threading
import queue
from yt_dlp import YoutubeDL, DownloadError
from tqdm import tqdm

# --------------------------------------------------------------------------- #
HELP_TEXT = """
Téléchargeur YouTube en MP3 ou MP4
==================================

Dépendances
-----------
  pip install yt-dlp tqdm

FFmpeg (requis pour MP3 & miniatures)
-------------------------------------
  - Ubuntu :  sudo apt install ffmpeg
  - macOS  :  brew install ffmpeg
  - Windows : https://ffmpeg.org/download.html  (ajouter ffmpeg au PATH)

Exemple rapide
--------------
  python youtube_downloader.py --search "rock 90s" --format mp3 --thumbnail

Options
-------
  URLs pos.       URL(s) vidéo ou playlist
  --search STR    Rechercher une playlist (répétable)
  --file PATH     Fichier texte (une URL ou requête par ligne)
  --format FMT    mp3 | mp4                       [défaut : mp4]
  --output DIR    Dossier de sortie (sinon nom playlist ou 'downloads')
  --thumbnail     Télécharger & embarquer miniature
  --verbose       Détails complets (recherche, URLs vidéo, etc.)
  --help          Afficher cette aide
"""
# --------------------------------------------------------------------------- #

INVALID_FS = r'[\\/*?:"<>|]'


def sanitize(name: str) -> str:
    """Nettoie un nom pour le système de fichiers."""
    name = re.sub(INVALID_FS, "_", name).strip().rstrip(".")
    return name[:100] or "playlist"


# --------------------------------------------------------------------------- #
# Progression par vidéo ------------------------------------------------------ #
# --------------------------------------------------------------------------- #
class ProgressBar:
    def __init__(self):
        self.bar = None

    def hook(self, d):
        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            done = d.get("downloaded_bytes", 0)
            if not self.bar and total:
                self.bar = tqdm(
                    total=total,
                    unit="B",
                    unit_scale=True,
                    desc=d.get("filename", "Téléchargement"),
                )
            if self.bar:
                self.bar.n = done
                self.bar.refresh()
        elif d["status"] == "finished" and self.bar:
            self.bar.n = self.bar.total
            self.bar.close()
            self.bar = None


# --------------------------------------------------------------------------- #
# 1. Recherche playlist avec spinner ---------------------------------------- #
# --------------------------------------------------------------------------- #
def score_playlist(entry: dict) -> int:
    title = (entry.get("title") or "").lower()
    count = entry.get("playlist_count") or 0
    return count + 100 * ("full album" in title) + 50 * ("official" in title)


def _yt_search_worker(q_out: queue.Queue, query: str):
    y_opts = {
        "quiet": True,
        "extract_flat": "discard_in_playlist",
        "skip_download": True,
        "ignoreerrors": True,
        "forcejson": True,
        "socket_timeout": 15,
    }
    try:
        with YoutubeDL(y_opts) as ydl:
            res = ydl.extract_info(query, download=False)
        q_out.put(("ok", res))
    except Exception as e:
        q_out.put(("err", e))


def search_playlist(term: str, verbose: bool = False) -> str:
    variants = [f"ytsearch50:{term} playlist", f"ytsearch50:{term} full album playlist"]
    best_entry, best_score = None, -1

    for attempt, query in enumerate(variants, start=1):
        print(f"🔍  ({attempt}/{len(variants)}) Requête YouTube : {query}")
        q = queue.Queue()
        th = threading.Thread(target=_yt_search_worker, args=(q, query), daemon=True)
        th.start()

        spinner = tqdm(total=0, bar_format="{desc}", desc="Recherche YouTube ⏳")
        frames = "|/-\\"
        idx = 0
        while th.is_alive():
            spinner.set_description(f"Recherche YouTube {frames[idx % 4]}")
            idx += 1
            time.sleep(0.2)
        spinner.close()

        status, data = q.get()
        if status == "err":
            print(f"   ⚠️  Erreur YouTube : {data}")
            continue

        entries = data.get("entries") or []
        print(f"   • {len(entries)} playlist(s) potentielles")
        for i, entry in enumerate(entries, start=1):
            if not entry or entry.get("_type") != "playlist":
                continue
            sc = score_playlist(entry)
            if verbose:
                t = entry.get("title") or "« titre inconnu »"
                c = entry.get("playlist_count") or 0
                print(f"     [{i:02}] {t} | vidéos : {c:<3} | score : {sc}")
            if sc > best_score:
                best_score, best_entry = sc, entry

        if best_entry:
            break  # on s’arrête après le premier variant fructueux

    if not best_entry:
        raise Exception(f"Aucune playlist trouvée pour « {term} ».")

    url = best_entry["url"]
    url = (
        url
        if url.startswith("http")
        else f"https://www.youtube.com/playlist?list={url}"
    )
    print(f"✅  Playlist retenue : {best_entry.get('title')}  (score {best_score})")
    return url


# --------------------------------------------------------------------------- #
# 2. Extraire URLs vidéo ---------------------------------------------------- #
# --------------------------------------------------------------------------- #
def get_video_list(link: str, verbose: bool = False):
    opts = {
        "quiet": True,
        "extract_flat": "in_playlist",
        "skip_download": True,
        "ignoreerrors": True,
        "forcejson": True,
        "socket_timeout": 15,
    }
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(link, download=False)

    is_pl = info.get("_type") == "playlist"
    title = info.get("title") or ""
    vids = []

    if is_pl:
        for e in info.get("entries", []):
            if not e:
                continue
            v = e.get("url")
            if v:
                vids.append(
                    v
                    if v.startswith("http")
                    else f"https://www.youtube.com/watch?v={v}"
                )
    else:
        vids = [link]

    if verbose:
        print(f"   • {len(vids)} vidéo(s) détectée(s)")

    if not vids:
        raise Exception("Aucune vidéo exploitable trouvée.")
    return vids, {"is_playlist": is_pl, "title": title}


# --------------------------------------------------------------------------- #
# 3. Options yt‑dlp ---------------------------------------------------------- #
# --------------------------------------------------------------------------- #
def ydl_options(fmt: str, outdir: str, hook, thumb: bool) -> dict:
    o = {
        "outtmpl": os.path.join(outdir, "%(title)s.%(ext)s"),
        "progress_hooks": [hook],
        "quiet": True,
        "socket_timeout": 15,
    }
    if fmt == "mp3":
        o.update(
            {
                "format": "bestaudio/best",
                "postprocessors": [
                    {
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": "mp3",
                        "preferredquality": "192",
                    }
                ],
            }
        )
    else:
        o.update(
            {
                "format": "bestvideo+bestaudio/best",
                "merge_output_format": "mp4",
            }
        )
    if thumb:
        o["writethumbnail"] = True
        o.setdefault("postprocessors", []).append({"key": "EmbedThumbnail"})
        o["prefer_ffmpeg"] = True
    return o


# --------------------------------------------------------------------------- #
# 4. Téléchargement ---------------------------------------------------------- #
# --------------------------------------------------------------------------- #
def download_all(vids, fmt, outdir, thumb, verbose=False, ctx=""):
    os.makedirs(outdir, exist_ok=True)
    print(f"\n⏬  {ctx}  →  dossier : {outdir}")
    bar = tqdm(total=len(vids), desc="Total", unit="vidéo")
    fails = []

    for v in vids:
        if verbose:
            print(f"   → {v}")
        pb = ProgressBar()
        try:
            with YoutubeDL(ydl_options(fmt, outdir, pb.hook, thumb)) as ydl:
                ydl.download([v])
        except DownloadError as e:
            print(f"[Erreur] {v}\n        ↳ {e}")
            fails.append((v, str(e)))
        bar.update(1)

    bar.close()
    if fails:
        print(f"⚠️  {len(fails)} vidéo(s) en échec :")
        for v, err in fails:
            print(f" • {v}  =>  {err}")


# --------------------------------------------------------------------------- #
# 5. Fichier de tâches ------------------------------------------------------ #
# --------------------------------------------------------------------------- #
def read_file(path):
    with open(path, encoding="utf-8") as f:
        return [ln.strip() for ln in f if ln.strip() and not ln.startswith("#")]


# --------------------------------------------------------------------------- #
# 6. CLI -------------------------------------------------------------------- #
# --------------------------------------------------------------------------- #
def help_exit(code=0):
    print(HELP_TEXT)
    sys.exit(code)


def main():
    P = argparse.ArgumentParser(add_help=False)
    P.add_argument("urls", nargs="*")
    P.add_argument("--search", action="append")
    P.add_argument("--file")
    P.add_argument("--format", choices=["mp3", "mp4"], default="mp4")
    P.add_argument("--output")
    P.add_argument("--thumbnail", action="store_true")
    P.add_argument("--verbose", action="store_true")
    P.add_argument("--help", action="store_true")
    args, unknown = P.parse_known_args()
    if args.help or unknown:
        help_exit(0 if args.help else 1)

    tasks = [("url", u) for u in args.urls]
    tasks += [("search", q) for q in (args.search or [])]
    if args.file:
        try:
            tasks += [
                ("url" if l.startswith("http") else "search", l)
                for l in read_file(args.file)
            ]
        except OSError as e:
            print(f"[Erreur] Lecture fichier : {e}")
            sys.exit(1)
    if not tasks:
        help_exit(1)

    for kind, val in tasks:
        try:
            if kind == "search":
                val = search_playlist(val, verbose=args.verbose)

            vids, meta = get_video_list(val, verbose=args.verbose)
            outdir = args.output or (
                sanitize(meta["title"]) if meta["is_playlist"] else "downloads"
            )
            ctx = meta["title"] or val
            download_all(
                vids, args.format, outdir, args.thumbnail, verbose=args.verbose, ctx=ctx
            )
        except Exception as exc:
            print(f"[Erreur {kind}] {val}\n        ↳ {exc}")


if __name__ == "__main__":
    main()
