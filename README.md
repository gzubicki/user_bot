# Telegram Multi-Bot Quote Platform

Platforma stanowi fundament do uruchomienia wielu botów Telegrama, które odgrywają różne persony i odpowiadają cytatami dostarczonymi przez społeczność. Moderacja oraz administracja odbywają się w prywatnych czatach Telegrama.

## Najważniejsze funkcje

- **Obsługa wielu botów** – pojedynczy backend obsługuje wiele tokenów botów, a każdy bot posiada własną personę.
- **Treści od społeczności** – użytkownicy przesyłają wiadomości (tekst, obraz, audio), a administratorzy zatwierdzają zgłoszenia.
- **Model subskrypcji** – jednorazowa opłata aktywacyjna (50 Telegram Stars) oraz miesięczna opłata per czat (10 Stars), z możliwością przydzielania darmowych slotów przez administratorów.
- **Hot-reload konfiguracji** – limity i ceny przechowywane są w zmiennych środowiskowych i mogą być przeładowywane bez restartu serwera.
- **Przyjazne audytom dane** – schemat PostgreSQL przechowuje persony, aliasy, zgłoszenia, wyniki moderacji, subskrypcje oraz log audytowy.

## Struktura repozytorium

```
bot_platform/
  __init__.py
  config.py
  database.py
  models.py
  rate_limiting.py
  services/
    __init__.py
    moderation.py
    personas.py
    quotes.py
    subscriptions.py
  telegram/
    __init__.py
    dispatcher.py
    webhooks.py
pyproject.toml
README.md
.env.example
```

## Szybki start (lokalne środowisko)

1. **Sklonuj repozytorium i wejdź do katalogu projektu**
   ```bash
   git clone <adres_repo>
   cd user_bot
   ```
2. **Utwórz wirtualne środowisko (Python 3.11+) i zainstaluj zależności**
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -e .[dev]
   ```
3. **Skopiuj plik konfiguracyjny i przygotuj zmienne środowiskowe**
   ```bash
   cp .env.example .env
   ```
   Następnie zaktualizuj `.env` zgodnie z sekcją [Zmienne środowiskowe](#zmienne-środowiskowe--źródła-i-wskazówki).
4. **Uruchom migracje bazy danych (opcjonalnie przy pierwszym starcie)**
   Ustaw `DATABASE_URL` w `.env` (np. dla lokalnej bazy `postgresql+asyncpg://postgres:postgres@localhost:5432/user_bot`) i wykonaj:
   ```bash
   alembic upgrade head
   ```
5. **Uruchom aplikację FastAPI z webhookami**
   ```bash
   uvicorn bot_platform.telegram.webhooks:app --reload
   ```
6. **Skonfiguruj boty i webhooki Telegrama**
   - Upewnij się, że w tabeli `bots` znajdują się wpisy z uzupełnionym polem `api_token` oraz ustawioną flagą `is_active=true`.
     Rekord możesz dodać np. za pomocą konsoli psql lub narzędzia `alembic revision --autogenerate` przygotowującego seed.
   - Wystaw publiczny adres HTTPS (np. za pomocą [ngrok](https://ngrok.com/)).
   - Dla każdego tokena z bazy ustaw webhook na adres:
     ```
     https://twoj-host/telegram/<TOKEN_BOTA>?secret=<WEBHOOK_SECRET>
     ```
   - Sekret (`WEBHOOK_SECRET`) musi zgadzać się z wartością w `.env`.

## Uruchomienie przez Docker Compose

1. Skopiuj plik konfiguracyjny i wypełnij zmienne jak w [Szybkim starcie](#szybki-start-lokalne-środowisko):
   ```bash
   cp .env.example .env
   ```
2. Zbuduj obraz i wystartuj usługi (aplikacja + PostgreSQL):
   ```bash
   docker compose up --build
   ```
   Jeśli zmienisz `Dockerfile`, dla pewności przebuduj obraz poleceniem `docker compose build app` przed kolejnym krokiem.
3. Po uruchomieniu usług (kontener `postgres` uzyska status „healthy”) wykonaj migracje bezpośrednio na działającym kontenerze aplikacji:
   ```bash
   docker compose exec app alembic upgrade head
   ```
   Jeżeli preferujesz jednorazowy kontener, możesz użyć:
   ```bash
   docker compose run --rm app alembic upgrade head
   ```
   (Czas pierwszego uruchomienia może być dłuższy, bo obraz zostanie przebudowany z uwzględnieniem plików Alembica.)
4. Zatrzymanie całego stosu:
   ```bash
   docker compose down
   ```

## Zmienne środowiskowe – źródła i wskazówki

Po skopiowaniu `.env.example` uzupełnij przede wszystkim poniższe wpisy:

| Zmienna | Jak zdobyć / rekomendowana wartość |
| --- | --- |
| `WEBHOOK_SECRET` | Dowolny losowy, trudny do odgadnięcia ciąg znaków. Można go wygenerować poleceniem `openssl rand -hex 32`. Wartość ta trafia do parametru `secret` podczas konfiguracji webhooków i zabezpiecza endpointy przed nieautoryzowanym użyciem. |
| `DATABASE_URL` | Adres połączenia z bazą PostgreSQL w formacie `postgresql+asyncpg://user:password@host:port/database`. W środowisku Docker Compose domyślny wpis z `.env.example` będzie poprawny. |
| `MODERATION_CHAT_ID` | Liczbowe ID czatu (lub kanału) Telegram, w którym moderatorzy mają otrzymywać powiadomienia. Najłatwiej je pozyskać wysyłając dowolną wiadomość do bota `@userinfobot` z danego czatu lub korzystając z narzędzi typu [@RawDataBot](https://t.me/RawDataBot). |

Pozostałe wartości (limity, ceny, ustawienia logowania) można zostawić domyślne lub dostosować do potrzeb. Aplikacja wspiera „hot reload” konfiguracji – zmiana `.env` i ponowne przeładowanie zmiennych środowiskowych (np. restart procesu lub odczyt w harmonogramie) aktualizuje limity w locie.

Tokeny botów są przechowywane bezpośrednio w bazie (kolumna `bots.api_token`). Dzięki temu można je podmieniać bez restartu aplikacji – wystarczy zaktualizować rekord i wywołać endpoint `/internal/reload-config`.

## Migracje bazy danych

Repozytorium zawiera gotową konfigurację Alembic (`alembic.ini` oraz katalog `alembic/`). Aby zsynchronizować schemat bazy z modelami:

```bash
alembic upgrade head
```

Pamiętaj o ustawieniu zmiennej `DATABASE_URL` przed uruchomieniem polecenia (np. `export DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/dbname`).

## Testy

Na ten moment repozytorium nie zawiera testów automatycznych. Proponowane polecenie do uruchamiania własnych testów:

```bash
pytest
```
