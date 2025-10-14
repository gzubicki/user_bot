"""Ustawienia wspólne dla testów."""
from __future__ import annotations

import sys
from pathlib import Path

# Pytest uruchamia się z katalogu głównego repozytorium, jednak w niektórych
# środowiskach (np. przy korzystaniu z wirtualnychenv narzędzi typu `pyenv`)
# bieżący katalog nie zawsze zostaje umieszczony na `sys.path`. Aby umożliwić
# import modułu ``bot_platform`` bez konieczności instalowania pakietu w trybie
# editable, dodajemy katalog repozytorium na początek ścieżki wyszukiwania.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
