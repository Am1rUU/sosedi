#!/usr/bin/env python
"""Утилита командной строки Django: запуск сервера, миграции, тесты и т.д."""

import os
import sys


def main():
    """Запускает команду управления проектом."""
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
