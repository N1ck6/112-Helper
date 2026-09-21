"""
Реализация "воспроизведения" для MVP этапа 4.

Почему именно так: браузеры умеют нативно проигрывать .wav и .mp3 по
прямой ссылке (тег <audio> при клике/скачивании) — не нужно писать
отдельный аудио-плеер. http.server с directory-листингом даёт это
"бесплатно": заходишь в браузере на http://<host>:8090/, видишь список
файлов, кликаешь — играет. Простейшее решение, которое реально
проверяется руками за 10 секунд, легко заменить на что-то более
специфичное в старших этапах (например, endpoint в Backend API).

Использование:
    python serve_recordings.py            # слушает 0.0.0.0:8090
"""

import functools
import http.server
import os

RECORDINGS_DIR = "/recordings"
PORT = int(os.environ.get("SERVE_PORT", "8090"))


def main():
    os.makedirs(RECORDINGS_DIR, exist_ok=True)
    handler = functools.partial(
        http.server.SimpleHTTPRequestHandler, directory=RECORDINGS_DIR
    )
    with http.server.ThreadingHTTPServer(("0.0.0.0", PORT), handler) as httpd:
        print(f"Отдаю {RECORDINGS_DIR} на http://0.0.0.0:{PORT}/")
        httpd.serve_forever()


if __name__ == "__main__":
    main()
