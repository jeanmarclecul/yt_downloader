#!/usr/bin/env python3
# youtube_downloader.py – v2025-07-14.9
"""
Télécharge vidéos ou playlists YouTube en MP3 / MP4 **avec métadonnées complètes**.

Nouveautés (v14.9)
------------------
• Les MP3 contiennent désormais les tags ID3 : `title`, `artist`, `album`,
  `track`, `date`, ainsi que la miniature (si disponible) grâce aux
  post‐processeurs **FFmpegExtractAudio ➜ FFmpegMetadata ➜ EmbedThumbnail**.
• Score amélioré : bonus pour titres « artiste - titre (année) ».
• Filtre Live, bonus Full-Album, malus Review/Cover, vues pondérées (1 pt / 100 000).
• Affichage `--verbose` trié par score (durée, URL, score).
• Gestion playlists / vidéos uniques, dossier auto, fichier d’entrées, etc.

Dépendances : `yt-dlp`, `ffmpeg`, `tqdm`
"""

import argparse
import datetime
import os
import queue
import re
import sys
import threading
import time
from typing import List, Tuple

from yt_dlp import YoutubeDL, DownloadError
from tqdm import tqdm


# ────────────────────────── utilitaires ──────────────────────────
INVALID_FS = r'[\\/*?:"<>|]'


def sanitize(name: str) -> str:
    return (re.sub(INVALID_FS, "_", name).strip().rstrip("."))[:100] or "output"


def sec_to_hms(sec: int | None) -> str:
    return "?" if not sec else str(datetime.timedelta(seconds=sec))


# ───────────────────────── barre individuelle ─────────────────────────
class ProgressBar:
    def __init__(self):
        self.bar = None

    def hook(self, d):
        if d["status"] == "downloading":
            tot = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            done = d.get("downloaded_bytes", 0)
            if not self.bar and tot:
                self.bar = tqdm(
                    total=tot,
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


# ───────────────────────── 1) Recherche & scoring ─────────────────────────
def score_entry(entry: dict, boost_full: bool) -> Tuple[int, str]:
    """Retourne (score, kind) ; kind ∈ {'playlist','video'}."""
    title = (entry.get("title") or "").lower()

    bonus_struct = 300 if re.search(r".+ - .+\(\d{4}\)", title) else 0
    bonus_full = (
        400
        if boost_full and "full album" in title
        else 100 if "full album" in title else 0
    )
    bonus_off = 50 if "official" in title else 0
    malus = -100 if any(w in title for w in ("review", "cover")) else 0

    if entry.get("_type") == "playlist":
        score = (
            (entry.get("playlist_count") or 0)
            + bonus_struct
            + bonus_full
            + bonus_off
            + malus
        )
        return score, "playlist"

    # video
    views_pts = (entry.get("view_count") or 0) // 100_000  # 1 pt / 100 000 vues
    score = views_pts + bonus_struct + bonus_full + bonus_off + malus
    return score, "video"


def _search_worker(q: queue.Queue, query: str):
    opts = {
        "quiet": True,
        "extract_flat": True,
        "skip_download": True,
        "ignoreerrors": True,
        "forcejson": True,
        "socket_timeout": 10,
    }
    try:
        with YoutubeDL(opts) as ydl:
            q.put(("ok", ydl.extract_info(query, download=False)))
    except Exception as exc:
        q.put(("err", exc))


def search_best(term: str, verbose: bool = False) -> str:
    want_live = "live" in term.lower()
    boost_full = "full album" in term.lower()
    queries = (
        [f"ytsearch20:{term}"]
        if boost_full
        else [f"ytsearch20:{term}", f"ytsearch20:{term} full album"]
    )

    best_entry, best_score, best_kind = None, -1, ""
    for qi, qstr in enumerate(queries, 1):
        print(f"🔍  ({qi}/{len(queries)}) Recherche : {qstr}")
        q = queue.Queue()
        t0 = time.time()
        threading.Thread(target=_search_worker, args=(q, qstr), daemon=True).start()

        spin = tqdm(total=0, bar_format="{desc}")
        frames = "|/-\\"
        k = 0
        while spin.total == 0 or not q.qsize():
            spin.set_description(f"Recherche YouTube {frames[k%4]}")
            k += 1
            time.sleep(0.2)
        spin.close()

        status, data = q.get()
        if status == "err":
            print(f"   ⚠️  Erreur : {data}")
            continue
        entries = data.get("entries") or []
        print(f"   • {len(entries)} résultat(s) en {time.time()-t0:.1f}s")

        cands = []
        for idx, e in enumerate(entries, 1):
            if not e:
                continue
            ttl = (e.get("title") or "").lower()
            if not want_live and "live" in ttl:
                continue
            score, kind = score_entry(e, boost_full)
            url = e["url"]
            if kind == "playlist" and not url.startswith("http"):
                url = f"https://www.youtube.com/playlist?list={url}"
            elif kind == "video" and not url.startswith("http"):
                url = f"https://www.youtube.com/watch?v={url}"
            metric = (
                f"vidéos:{e.get('playlist_count')}"
                if kind == "playlist"
                else f"vues:{e.get('view_count') or 0}"
            )
            dur = sec_to_hms(e.get("duration")) if kind == "video" else "—"
            cands.append(
                {
                    "idx": idx,
                    "entry": e,
                    "score": score,
                    "kind": kind,
                    "metric": metric,
                    "url": url,
                    "dur": dur,
                }
            )
        cands.sort(key=lambda c: (-c["score"], c["idx"]))

        if verbose:
            print("Résultats triés :")
            for c in cands:
                print(
                    f"  [{c['idx']:02}] {c['entry'].get('title')} ({c['kind']}) | "
                    f"{c['metric']} | dur:{c['dur']} | score {c['score']} | {c['url']}"
                )

        if cands:
            best_entry, best_score, best_kind = (
                cands[0]["entry"],
                cands[0]["score"],
                cands[0]["kind"],
            )
            break

    if not best_entry:
        raise Exception(f"Aucun résultat pertinent pour « {term} ».")

    fin_url = best_entry["url"]
    if best_kind == "playlist" and not fin_url.startswith("http"):
        fin_url = f"https://www.youtube.com/playlist?list={fin_url}"
    elif best_kind == "video" and not fin_url.startswith("http"):
        fin_url = f"https://www.youtube.com/watch?v={fin_url}"

    print(
        f"✅  {'📜' if best_kind=='playlist' else '🎞️'} Sélection : "
        f"{best_entry.get('title')}  (score {best_score})"
    )
    return fin_url


# ───────────────────────── 2) Extraction infos ─────────────────────────
def get_video_list(url: str):
    opts = {
        "quiet": True,
        "extract_flat": "in_playlist",
        "skip_download": True,
        "ignoreerrors": True,
        "forcejson": True,
        "socket_timeout": 10,
    }
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    if info.get("_type") == "playlist":
        urls = []
        for e in info.get("entries", []):
            if not e:
                continue
            vid = e["url"]
            urls.append(
                vid
                if vid.startswith("http")
                else f"https://www.youtube.com/watch?v={vid}"
            )
        title = info.get("title") or "playlist"
        return urls, True, title
    else:
        return [url], False, info.get("title") or "video"


# ───────────────────────── 3) Options yt-dlp ─────────────────────────
def build_ydl_opts(fmt: str, outtmpl: str, embed_thumb: bool) -> dict:
    opts = {
        "outtmpl": outtmpl,
        "quiet": True,
        "no_warnings": True,
        "progress_hooks": [],
        "ignoreerrors": True,
        "socket_timeout": 10,
    }
    if fmt == "mp3":
        opts["format"] = "bestaudio/best"
        opts["postprocessors"] = [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            },
            {"key": "FFmpegMetadata"},  # ⇦ ajoute tags ID3
        ]
        if embed_thumb:
            opts["postprocessors"].append({"key": "EmbedThumbnail"})
            opts["writethumbnail"] = True
    else:
        opts["format"] = "bestvideo+bestaudio/best"
        opts["merge_output_format"] = "mp4"
        if embed_thumb:
            opts["writethumbnail"] = True
            opts["postprocessors"] = [{"key": "EmbedThumbnail"}]
    return opts


def download_list(
    urls: List[str],
    fmt: str,
    outdir: str,
    is_playlist: bool,
    verbose: bool,
    embed_thumb: bool,
):
    os.makedirs(outdir, exist_ok=True)
    tot = len(urls)
    bar = tqdm(total=tot, desc="Total", unit="vidéo")
    fails = []
    for i, url in enumerate(urls, 1):
        pb = ProgressBar()
        name_tmpl = (
            "%(title)s.%(ext)s" if not is_playlist else f"{i:03d} - %(title)s.%(ext)s"
        )
        opts = build_ydl_opts(fmt, os.path.join(outdir, name_tmpl), embed_thumb)
        opts["progress_hooks"] = [pb.hook]

        try:
            with YoutubeDL(opts) as ydl:
                ydl.download([url])
        except DownloadError as e:
            fails.append((url, str(e)))
            if verbose:
                print(f"[Erreur] {url} -> {e}")
        bar.update(1)
    bar.close()
    if fails:
        print(f"⚠️  {len(fails)} vidéo(s) en erreur :")
        for u, err in fails:
            print(f" • {u}  =>  {err}")


# ───────────────────────── 4) CLI principal ─────────────────────────
HELP = """\
Usage :
  yt_dl.py [URL…] [--search TERME] [--file LISTE] [options]

Options :
  --format mp3|mp4     Format de sortie (défaut mp4)
  --output DIR         Choisir le répertoire de sortie
  --thumbnail          Intégrer la miniature (si possible)
  --verbose            Afficher détails (scores, urls…)
  --help               Cette aide
"""


def gather_tasks(args) -> List[Tuple[str, str]]:
    tasks = []
    for inp in args.inputs:
        if os.path.isfile(inp):
            with open(inp, encoding="utf-8") as f:
                for l in f:
                    l = l.strip()
                    if not l:
                        continue
                    tasks.append(("search" if not l.startswith("http") else "url", l))
        else:
            tasks.append(("search" if not inp.startswith("http") else "url", inp))
    if args.search:
        tasks.append(("search", args.search))
    return tasks


def cli():
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("inputs", nargs="*")
    p.add_argument("--search")
    p.add_argument("--format", choices=["mp3", "mp4"], default="mp4")
    p.add_argument("--output")
    p.add_argument("--thumbnail", action="store_true")
    p.add_argument("--verbose", action="store_true")
    p.add_argument("--help", action="store_true")
    args = p.parse_args()

    if args.help or (not args.inputs and not args.search):
        print(HELP)
        sys.exit(0)

    tasks = gather_tasks(args)
    if not tasks:
        print("Aucune tâche.")
        sys.exit(1)

    for kind, val in tasks:
        try:
            url = val
            if kind == "search":
                url = search_best(val, verbose=args.verbose)

            urls, is_pl, title = get_video_list(url)
            outdir = args.output or (sanitize(title) if is_pl else "downloads")
            if args.verbose:
                print(f"⬇️  Téléchargement vers '{outdir}' ({len(urls)} fichier(s))")
            download_list(
                urls,
                args.format,
                outdir,
                is_pl,
                verbose=args.verbose,
                embed_thumb=args.thumbnail,
            )
        except Exception as exc:
            print(f"[Erreur] {val}\n        ↳ {exc}")


if __name__ == "__main__":
    cli()
