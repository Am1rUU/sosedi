#!/usr/local/bin/python3
"""Мини-замена curl и wget для проверки здоровья контейнера.

Хостинг (Timeweb) раз в 30 секунд вызывает внутри контейнера curl или wget
с адресом /healthz/. Ставить настоящие curl и wget через apt долго
(на сборщике Timeweb это занимало ~9 минут), поэтому здесь простой скрипт,
который понимает самые частые варианты вызова:

    curl -f http://localhost:8000/healthz/
    curl -fsS localhost:8000/healthz/                      (адрес без http://)
    curl -s -o /dev/null -w "%{http_code}" http://...      (печатает код ответа)
    wget -q --spider http://...  /  wget -qO- http://...

Код выхода: 0 — ответ успешный (2xx/3xx), иначе ненулевой.
Любой вызов без адреса (например, «curl --version») завершается успешно.
"""

import sys
import urllib.error
import urllib.request

# Опции curl/wget, у которых есть значение отдельным аргументом: «-o файл», «-w формат» и т.п.
OPTIONS_WITH_VALUE = {
    "-o", "--output", "-w", "--write-out", "-H", "--header", "-X", "--request", "-m", "--max-time",
    "--connect-timeout", "-u", "--user", "-A", "--user-agent", "-e", "--referer", "-d", "--data",
    "-O", "--output-document", "-T", "--timeout", "-t", "--tries", "--retry", "-U", "--retry-delay",
    "-b", "--cookie", "-c", "--cookie-jar", "--resolve", "-x", "--proxy",
}


def parse(argv: list[str]) -> tuple[str | None, str | None, bool]:
    """Возвращает (адрес, формат для -w, нужно ли печатать тело ответа)."""
    url = None
    write_out = None
    print_body = False
    args = iter(argv)
    for arg in args:
        if arg in OPTIONS_WITH_VALUE:
            value = next(args, "")
            if arg in ("-w", "--write-out"):
                write_out = value
            if arg in ("-O", "--output-document") and value == "-":
                print_body = True
            continue
        if arg.startswith("--write-out="):
            write_out = arg.split("=", 1)[1]
            continue
        if arg.startswith("-"):
            if arg.startswith("-") and not arg.startswith("--") and arg.endswith("O-"):
                print_body = True  # wget -qO-
            continue
        if arg.startswith("/"):
            continue  # путь к файлу, а не адрес
        url = arg
    if url and "://" not in url:
        url = "http://" + url
    return url, write_out, print_body


def main() -> int:
    url, write_out, print_body = parse(sys.argv[1:])
    if url is None:
        return 0  # «curl --version» и подобные вызовы без адреса
    status = 0
    body = b""
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            status = response.status
            body = response.read()
    except urllib.error.HTTPError as exc:
        status = exc.code
    except Exception as exc:  # нет соединения, таймаут
        print(f"Проверка не прошла: {exc}", file=sys.stderr)
        if write_out:
            sys.stdout.write(write_out.replace("%{http_code}", "000").replace("\\n", "\n"))
        return 7
    if print_body:
        sys.stdout.buffer.write(body)
    if write_out:
        sys.stdout.write(write_out.replace("%{http_code}", str(status)).replace("\\n", "\n"))
    return 0 if status < 400 else 22


if __name__ == "__main__":
    sys.exit(main())
