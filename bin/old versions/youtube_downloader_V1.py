import argparse
import sys
import os
from yt_dlp import YoutubeDL


def is_playlist(url: str) -> bool:
    return "playlist" in url or "list=" in url


def get_ydl_options(output_format: str, is_audio: bool) -> dict:
    if is_audio:
        return {
            "format": "bestaudio/best",
            "outtmpl": "%(title)s.%(ext)s",
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": output_format,
                    "preferredquality": "192",
                }
            ],
            "noplaylist": False,
        }
    else:
        return {
            "format": "bestvideo+bestaudio/best",
            "outtmpl": "%(title)s.%(ext)s",
            "merge_output_format": output_format,
            "noplaylist": False,
        }


def download(url: str, output_format: str):
    is_audio = output_format == "mp3"
    options = get_ydl_options(output_format, is_audio)
    with YoutubeDL(options) as ydl:
        try:
            ydl.download([url])
        except Exception as e:
            print(f"[Erreur] Impossible de télécharger : {e}")
            sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Télécharge une vidéo ou playlist YouTube en MP3 ou MP4."
    )
    parser.add_argument("url", help="URL de la vidéo ou playlist YouTube")
    parser.add_argument(
        "--format",
        choices=["mp3", "mp4"],
        default="mp4",
        help="Format de sortie (mp3 pour audio, mp4 pour vidéo)",
    )

    args = parser.parse_args()
    download(args.url, args.format)


if __name__ == "__main__":
    main()
