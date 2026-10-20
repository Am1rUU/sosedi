#!/usr/local/bin/python3
"""Мини-замена curl и wget для проверки здоровья контейнера.

Хостинг (Timeweb) раз в 30 секунд вызывает внутри контейнера curl или wget
с адресом /healthz/. Ставить настоящие curl и wget через apt долго
(на сборщике Timeweb это занимало ~9 минут), поэтому здесь простой скрипт:
берёт из аргументов первый адрес http(s)://..., запрашивает его и
выходит с кодом 0, если ответ успешный, и с ненулевым кодом иначе.
"""

import sys
import urllib.request


def main() -> int:
    url = next((a for a in sys.argv[1:] if a.startswith(("http://", "https://"))), None)
    if url is None:
        print("Нужен адрес вида http://...", file=sys.stderr)
        return 2
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            response.read()
            return 0 if response.status < 400 else 22
    except Exception as exc:  # 4xx/5xx, нет соединения, таймаут
        print(f"Проверка не прошла: {exc}", file=sys.stderr)
        return 22


if __name__ == "__main__":
    sys.exit(main())
