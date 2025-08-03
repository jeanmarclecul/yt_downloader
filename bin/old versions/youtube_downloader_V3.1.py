#!/usr/bin/env python3
# youtube_downloader.py – v2025-07-13
#
# • Recherche (--search) évalue playlists ET vidéos :
#     playlist_score = nb_videos  + bonus « full album » + bonus « official »
#     video_score    = vues/10 000 + mêmes bonus
#   → Si la meilleure vidéo dépasse la meilleure playlist, on télécharge la vidéo.
# • ytsearch20 + socket_timeout 10 s  → recherche plus rapide
# • Spinner + chrono pendant la requête réseau
# • Dossier auto = nom de la playlist (nettoyé) si --output absent
# • Toutes les autres fonctionnalités antérieures restent inchangées

import argparse
import os
import re
import sys
import time
import threading
import queue
from yt_dlp import YoutubeDL, DownloadError
from tqdm import tqdm

# ──────────────────────────  utilitaires  ──────────────────────────
INVALID_FS = r'[\\/*?:"<>|]'

def sanitize(name: str) -> str:
    """Nettoie un nom pour un système de fichiers générique."""
    name = re.sub(INVALID_FS, "_", name).strip().rstrip(".")
    return name[:100] or "output"

# ───────────────────────  barre par vidéo  ───────────────────────
class ProgressBar:
    def __init__(self):
        self.bar = None

    def hook(self, d):
        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            done  = d.get("downloaded_bytes", 0)
            if not self.bar and total:
                self.bar = tqdm(total=total, unit="B", unit_scale=True,
                                desc=d.get("filename", "Téléchargement"))
            if self.bar:
                self.bar.n = done
                self.bar.refresh()
        elif d["status"] == "finished" and self.bar:
            self.bar.n = self.bar.total
            self.bar.close()
            self.bar = None

# ─────────────────────── 1) Recherche mixte ───────────────────────
def score_entry(e: dict) -> tuple[int, str]:
    """Retourne (score, 'playlist'|'video')."""
    title = (e.get("title") or "").lower()
    bonus = 100 * ("full album" in title) + 50 * ("official" in title)

    if e.get("_type") == "playlist":
        score = (e.get("playlist_count") or 0) + bonus
        return score, "playlist"

    # vidéo
    views = (e.get("view_count") or 0) // 10_000  # 10 000 vues = 1 pt
    score = views + bonus
    return score, "video"

def _search_worker(out_q: queue.Queue, query: str):
    """Thread worker : exécute yt_dlp avec extract_flat."""
    opts = {
        "quiet": True,
        "extract_flat": True,          # plus rapide
        "skip_download": True,
        "ignoreerrors": True,
        "forcejson": True,
        "socket_timeout": 10,
    }
    try:
        with YoutubeDL(opts) as ydl:
            res = ydl.extract_info(query, download=False)
        out_q.put(("ok", res))
    except Exception as e:
        out_q.put(("err", e))

def search_best(term: str, verbose: bool = False) -> str:
    """
    Retourne l'URL de la meilleure playlist OU vidéo pour la requête.
    Affiche un spinner pendant la requête et un log des scores.
    """
    queries = [
        f"ytsearch20:{term}",               # résultats mixtes
        f"ytsearch20:{term} full album"     # deuxième tentative
    ]
    best_entry, best_score, best_type = None, -1, ""

    for qi, qstr in enumerate(queries, 1):
        print(f"🔍  ({qi}/{len(queries)}) Recherche : {qstr}")
        q = queue.Queue()
        t0 = time.time()
        th = threading.Thread(target=_search_worker, args=(q, qstr), daemon=True)
        th.start()

        # spinner
        spin = tqdm(total=0, bar_format="{desc}")
        frames = "|/-\\"
        k = 0
        while th.is_alive():
            spin.set_description(f"Recherche YouTube {frames[k % 4]}")
            k += 1
            time.sleep(0.2)
        spin.close()

        status, data = q.get()
        if status == "err":
            print(f"   ⚠️  Erreur : {data}")
            continue

        entries = data.get("entries") or []
        print(f"   • {len(entries)} résultat(s) en {time.time()-t0:.1f}s")

        bar = tqdm(total=len(entries), desc="Évaluation", unit="rés")
        for n, e in enumerate(entries, 1):
            bar.update(1)
            if not e or e.get("_type") not in ("playlist", "video"):
                continue
            sc, lbl = score_entry(e)
            if verbose:
                tit = e.get("title") or "(titre inconnu)"
                if lbl == "playlist":
                    extra = f"vidéos : {e.get('playlist_count')}"
                else:
                    extra = f"vues : {e.get('view_count')}"
                print(f"      [{n:02}] {tit}  ({lbl})  | {extra} | score {sc}")
            if sc > best_score:
                best_entry, best_score, best_type = e, sc, lbl
        bar.close()

        if best_entry:   # on garde le meilleur du premier tour fructueux
            break

    if not best_entry:
        raise Exception(f"Aucun résultat pertinent pour « {term} ».")

    url = best_entry["url"]
    if best_type == "playlist" and not url.startswith("http"):
        url = f"https://www.youtube.com/playlist?list={url}"
    elif best_type == "video" and not url.startswith("http"):
        url = f"https://www.youtube.com/watch?v={url}"

    icon = "📜" if best_type == "playlist" else "🎞️"
    print(f"✅  {icon} Sélection : {best_entry.get('title')}  (score {best_score})")
    return url

# ─────────────────────── 2) Extraction vidéos ───────────────────────
def get_video_list(link: str, verbose: bool = False):
    opts = {
        "quiet": True,
        "extract_flat": "in_playlist",
        "skip_download": True,
        "ignoreerrors": True,
        "forcejson": True,
        "socket_timeout": 10,
    }
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(link, download=False)

    is_pl = info.get("_type") == "playlist"
    title = info.get("title") or ""
    urls  = []

    if is_pl:
        for e in info.get("entries", []):
            if not e:
                continue
            v = e.get("url")
            if v:
                urls.append(v if v.startswith("http")
                            else f"https://www.youtube.com/watch?v={v}")
    else:
        urls = [link]

    if verbose:
        print(f"   • {len(urls)} vidéo(s) détectée(s)")
    if not urls:
        raise Exception("Aucune vidéo exploitable trouvée.")
    return urls, {"is_playlist": is_pl, "title": title}

# ─────────────────────── 3) Options yt-dlp  ───────────────────────
def ydl_options(fmt: str, outdir: str, hook, thumb: bool) -> dict:
    o = {
        "outtmpl": os.path.join(outdir, "%(title)s.%(ext)s"),
        "progress_hooks": [hook],
        "quiet": True,
        "socket_timeout": 10,
    }
    if fmt == "mp3":
        o.update({
            "format": "bestaudio/best",
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }],
        })
    else:
        o.update({
            "format": "bestvideo+bestaudio/best",
            "merge_output_format": "mp4",
        })
    if thumb:
        o["writethumbnail"] = True
        o.setdefault("postprocessors", []).append({"key": "EmbedThumbnail"})
        o["prefer_ffmpeg"] = True
    return o

# ─────────────────────── 4) Téléchargement listé ───────────────────────
def download_all(vids, fmt, outdir, thumb, verbose=False, ctx=""):
    os.makedirs(outdir, exist_ok=True)
    print(f"\n⏬  {ctx}  → dossier : {outdir}")
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

# ─────────────────────── 5) Lecture fichier texte ───────────────────────
def read_file(path):
    with open(path, encoding="utf-8") as f:
        return [ln.strip() for ln in f if ln.strip() and not ln.startswith("#")]

# ─────────────────────── 6) Interface CLI  ───────────────────────
HELP_TEXT = """
Usage
=====
python youtube_downloader.py [URL …] [--search « terme » …] [options]

Si --search est fourni, le script choisit *automatiquement* la meilleure
playlist *ou* vidéo et la télécharge.

Options principaux
------------------
  --file TXT      Fichier texte : une URL ou requête par ligne
  --format mp3|mp4   Format de sortie (défaut : mp4)
  --output DIR    Dossier de sortie (défaut : nom playlist ou downloads)
  --thumbnail     Télécharge et intègre la miniature
  --verbose       Affiche la liste des candidats et chaque URL vidéo
"""

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

    # Agrège toutes les tâches
    tasks = [("url", u) for u in args.urls]
    tasks += [("search", q) for q in (args.search or [])]
    if args.file:
        try:
            tasks += [("url" if l.startswith("http") else "search", l)
                      for l in read_file(args.file)]
        except OSError as e:
            print(f"[Erreur] Lecture fichier : {e}")
            sys.exit(1)
    if not tasks:
        help_exit(1)

    # Boucle principale
    for kind, val in tasks:
        try:
            if kind == "search":
                val = search_best(val, verbose=args.verbose)

            vids, meta = get_video_list(val, verbose=args.verbose)
            outdir = args.output or (
                sanitize(meta["title"]) if meta["is_playlist"] else "downloads"
            )
            ctx = meta["title"] or val
            download_all(vids, args.format, outdir, args.thumbnail,
                         verbose=args.verbose, ctx=ctx)
        except Exception as exc:
            print(f"[Erreur {kind}] {val}\n        ↳ {exc}")

if __name__ == "__main__":
    main()
    