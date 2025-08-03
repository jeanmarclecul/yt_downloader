import argparse
import os
import sys
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError
from tqdm import tqdm

HELP_TEXT = """
Téléchargeur YouTube en MP3 ou MP4

🛠 Dépendances à installer :
  pip install yt-dlp tqdm

🔧 FFmpeg requis pour l'extraction MP3 et les miniatures :
  - Ubuntu :   sudo apt install ffmpeg
  - MacOS :    brew install ffmpeg
  - Windows :  https://ffmpeg.org/download.html (ajoutez ffmpeg au PATH)

📦 Utilisation :

  Télécharger une vidéo en MP4 :
    python youtube_downloader.py "https://youtu.be/XYZ"

  Télécharger une playlist en MP3 avec miniatures :
    python youtube_downloader.py "https://www.youtube.com/playlist?list=XXX" --format mp3 --thumbnail --output mes_videos

🔣 Options :
  url           Lien vers une vidéo ou une playlist YouTube
  --format      Format de sortie : mp3 (audio) ou mp4 (vidéo) [par défaut : mp4]
  --output      Dossier de téléchargement [par défaut : downloads]
  --thumbnail   Télécharger aussi l'image miniature de chaque vidéo
  --help        Affiche cette aide
"""

class ProgressBar:
    def __init__(self):
        self.bar = None

    def hook(self, d):
        if d['status'] == 'downloading':
            total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
            downloaded = d.get('downloaded_bytes', 0)
            if not self.bar and total:
                self.bar = tqdm(total=total, unit='B', unit_scale=True, desc=d.get('filename', 'Téléchargement'))
            if self.bar:
                self.bar.n = downloaded
                self.bar.refresh()
        elif d['status'] == 'finished' and self.bar:
            self.bar.n = self.bar.total
            self.bar.close()
            self.bar = None

def get_video_list(url: str) -> list:
    urls = []
    with YoutubeDL({'quiet': True, 'extract_flat': True, 'forcejson': True}) as ydl:
        try:
            info = ydl.extract_info(url, download=False)
        except DownloadError as e:
            raise Exception(f"Erreur lors de l'analyse de l'URL : {e}")

        if '_type' in info and info['_type'] == 'playlist':
            for entry in info['entries']:
                video_url = entry.get('url')
                if video_url:
                    if not video_url.startswith("http"):
                        video_url = f"https://www.youtube.com/watch?v={video_url}"
                    urls.append(video_url)
        else:
            urls = [url]

    return urls

def get_ydl_options(format_type: str, out_dir: str, progress_hook, include_thumbnail: bool) -> dict:
    options = {
        'outtmpl': os.path.join(out_dir, '%(title)s.%(ext)s'),
        'progress_hooks': [progress_hook],
        'quiet': True,
    }

    if format_type == 'mp3':
        options['format'] = 'bestaudio/best'
        options['postprocessors'] = [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }]
    else:
        options['format'] = 'bestvideo+bestaudio/best'
        options['merge_output_format'] = 'mp4'

    if include_thumbnail:
        options['writethumbnail'] = True
        options['postprocessors'] = options.get('postprocessors', []) + [{
            'key': 'EmbedThumbnail',
        }]
        options['prefer_ffmpeg'] = True

    return options

def download_all(video_urls: list, format_type: str, out_dir: str, include_thumbnail: bool):
    global_bar = tqdm(total=len(video_urls), desc="Total", unit="vidéo")
    failed = []

    for url in video_urls:
        pbar = ProgressBar()
        options = get_ydl_options(format_type, out_dir, pbar.hook, include_thumbnail)
        try:
            with YoutubeDL(options) as ydl:
                ydl.download([url])
        except DownloadError as e:
            print(f"[Erreur] Téléchargement échoué pour {url} : {e}")
            failed.append((url, str(e)))
        global_bar.update(1)

    global_bar.close()

    if failed:
        print(f"\n⚠️ {len(failed)} vidéo(s) n'ont pas pu être téléchargées :")
        for url, error in failed:
            print(f" - {url} => {error}")

def show_help_and_exit(code=0):
    print(HELP_TEXT)
    sys.exit(code)

def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("url", nargs='?', help="URL de la vidéo ou playlist")
    parser.add_argument("--format", choices=["mp3", "mp4"], default="mp4", help="Format de sortie")
    parser.add_argument("--output", help="Dossier de sortie", default="downloads")
    parser.add_argument("--thumbnail", action="store_true", help="Télécharger l'image miniature")
    parser.add_argument("--help", action="store_true", help="Afficher l'aide")

    args, unknown = parser.parse_known_args()

    if args.help or not args.url or unknown:
        show_help_and_exit(0 if args.help else 1)

    out_dir = args.output
    os.makedirs(out_dir, exist_ok=True)

    try:
        urls = get_video_list(args.url)
        download_all(urls, args.format, out_dir, include_thumbnail=args.thumbnail)
    except Exception as e:
        print(f"[Erreur] {e}")
        # show_help_and_exit(1)

if __name__ == "__main__":
    main()
