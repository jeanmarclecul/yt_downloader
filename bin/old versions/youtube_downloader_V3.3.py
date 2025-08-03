#!/usr/bin/env python3
# youtube_downloader.py – v2025‑07‑14.2
#
#  • --search : choisit la meilleure playlist 📜 ou vidéo 🎞️
#  • Filtre “live” : ignoré si non demandé
#  • Accent “full album” : +400 pts lorsque la requête contient ces mots
#  • Malus “review” ou “cover” : –100 pts si ces mots sont dans le titre
#  • --verbose : affiche titre, métrique, score et URL de chaque candidat
#  • Options : fichier d’entrées, miniatures, dossier auto, barres de progression

import argparse, os, re, sys, time, threading, queue
from yt_dlp import YoutubeDL, DownloadError
from tqdm import tqdm

# ───────── utilitaires
INVALID_FS = r'[\\/*?:"<>|]'


def sanitize(name: str) -> str:
    return (re.sub(INVALID_FS, "_", name).strip().rstrip("."))[:100] or "output"


# ───────── barre par vidéo
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


# ───────── 1) Recherche
def score_entry(e: dict, big_bonus=False) -> tuple[int, str]:
    title = (e.get("title") or "").lower()
    bonus_full = (
        400
        if big_bonus and "full album" in title
        else 100 if "full album" in title else 0
    )
    bonus_off = 50 if "official" in title else 0
    malus = -100 if any(w in title for w in ("review", "cover")) else 0
    if e.get("_type") == "playlist":
        return (
            e.get("playlist_count") or 0
        ) + bonus_full + bonus_off + malus, "playlist"
    views = (e.get("view_count") or 0) // 10_000
    return views + bonus_full + bonus_off + malus, "video"


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
    except Exception as e:
        q.put(("err", e))


def search_best(term, verbose=False):
    want_live = "live" in term.lower()
    big_bonus = "full album" in term.lower()
    queries = (
        [f"ytsearch20:{term}"]
        if big_bonus
        else [f"ytsearch20:{term}", f"ytsearch20:{term} full album"]
    )
    best, best_score, best_kind = None, -1, ""
    for qi, qstr in enumerate(queries, 1):
        print(f"🔍  ({qi}/{len(queries)}) Recherche : {qstr}")
        q = queue.Queue()
        t0 = time.time()
        th = threading.Thread(target=_search_worker, args=(q, qstr), daemon=True)
        th.start()
        spin = tqdm(total=0, bar_format="{desc}")
        frames = "|/-\\"
        k = 0
        while th.is_alive():
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
        bar = tqdm(total=len(entries), desc="Évaluation", unit="rés")
        for idx, e in enumerate(entries, 1):
            bar.update(1)
            if not e:
                continue
            title = (e.get("title") or "").lower()
            if not want_live and "live" in title:
                continue
            sc, kind = score_entry(e, big_bonus)
            if verbose:
                url = e["url"]
                if kind == "playlist" and not url.startswith("http"):
                    url = f"https://www.youtube.com/playlist?list={url}"
                elif kind == "video" and not url.startswith("http"):
                    url = f"https://www.youtube.com/watch?v={url}"
                metric = (
                    f"vidéos:{e.get('playlist_count')}"
                    if kind == "playlist"
                    else f"vues:{e.get('view_count')}"
                )
                print(
                    f"      [{idx:02}] {e.get('title')} ({kind}) | {metric} "
                    f"| score {sc} | {url}"
                )
            if sc > best_score:
                best, best_score, best_kind = e, sc, kind
        bar.close()
        if best:
            break
    if not best:
        raise Exception(f"Aucun résultat pertinent pour « {term} ».")
    url = best["url"]
    if best_kind == "playlist" and not url.startswith("http"):
        url = f"https://www.youtube.com/playlist?list={url}"
    elif best_kind == "video" and not url.startswith("http"):
        url = f"https://www.youtube.com/watch?v={url}"
    print(
        f"✅  {'📜' if best_kind=='playlist' else '🎞️'} Sélection : "
        f"{best.get('title')}  (score {best_score})"
    )
    return url


# ───────── 2) Extraction vidéos
def get_video_list(link, verbose=False):
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
    pl = info.get("_type") == "playlist"
    title = info.get("title") or ""
    urls = []
    if pl:
        for e in info.get("entries", []):
            if e and e.get("url"):
                u = e["url"]
                urls.append(
                    u
                    if u.startswith("http")
                    else f"https://www.youtube.com/watch?v={u}"
                )
    else:
        urls = [link]
    if verbose:
        print(f"   • {len(urls)} vidéo(s) détectée(s)")
    if not urls:
        raise Exception("Aucune vidéo exploitable trouvée.")
    return urls, {"is_playlist": pl, "title": title}


# ───────── 3) Options yt‑dlp
def ydl_options(fmt, outdir, hook, thumb):
    o = {
        "outtmpl": os.path.join(outdir, "%((title)s).%(ext)s"),
        "progress_hooks": [hook],
        "quiet": True,
        "socket_timeout": 10,
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
        o.update({"format": "bestvideo+bestaudio/best", "merge_output_format": "mp4"})
    if thumb:
        o["writethumbnail"] = True
        o.setdefault("postprocessors", []).append({"key": "EmbedThumbnail"})
        o["prefer_ffmpeg"] = True
    return o


# ───────── 4) Téléchargement
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
        except DownloadError as exc:
            print(f"[Erreur] {v}\n        ↳ {exc}")
            fails.append((v, str(exc)))
        bar.update(1)
    bar.close()
    if fails:
        print(f"⚠️  {len(fails)} vidéo(s) en échec :")
        for v, e in fails:
            print(f" • {v}  =>  {e}")


# ───────── 5) Lecture fichier
def read_file(path):
    with open(path, encoding="utf-8") as f:
        return [l.strip() for l in f if l.strip() and not l.startswith("#")]


# ───────── 6) CLI
def main():
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("urls", nargs="*")
    p.add_argument("--search", action="append")
    p.add_argument("--file")
    p.add_argument("--format", choices=["mp3", "mp4"], default="mp4")
    p.add_argument("--output")
    p.add_argument("--thumbnail", action="store_true")
    p.add_argument("--verbose", action="store_true")
    p.add_argument("--help", action="store_true")
    args, unk = p.parse_known_args()
    if args.help or unk:
        print("python youtube_downloader.py [URL …] --search terme … [options]")
        sys.exit(0 if args.help else 1)

    tasks = [("url", u) for u in args.urls] + [
        ("search", q) for q in (args.search or [])
    ]
    if args.file:
        try:
            tasks += [
                ("url" if l.startswith("http") else "search", l)
                for l in read_file(args.file)
            ]
        except OSError as e:
            print(f"[Erreur] Lecture fichier : {e}")
            sys.exit(1)
    if not tasks:
        print("Aucune tâche fournie.")
        sys.exit(1)

    for kind, val in tasks:
        try:
            if kind == "search":
                val = search_best(val, args.verbose)
            vids, meta = get_video_list(val, args.verbose)
            outdir = args.output or (
                sanitize(meta["title"]) if meta["is_playlist"] else "downloads"
            )
            ctx = meta["title"] or val
            download_all(vids, args.format, outdir, args.thumbnail, args.verbose, ctx)
        except Exception as exc:
            print(f"[Erreur {kind}] {val}\n        ↳ {exc}")


if __name__ == "__main__":
    main()
