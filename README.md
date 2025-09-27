# Telegram Multi-Bot Quote Platform

Platforma stanowi fundament do uruchomienia wielu botów Telegrama, które odgrywają różne persony i odpowiadają cytatami dostarczonymi przez społeczność. Moderacja oraz administracja odbywają się w prywatnych czatach Telegrama.

## Najważniejsze funkcje

- **Obsługa wielu botów** – pojedynczy backend obsługuje wiele tokenów botów, a każdy bot posiada własną personę.
- **Treści od społeczności** – użytkownicy przesyłają wiadomości (tekst, obraz, audio), a administratorzy (wszyscy uczestnicy wskazanych czatów administracyjnych) zatwierdzają zgłoszenia.
- **Model subskrypcji** – jednorazowa opłata aktywacyjna (50 Telegram Stars) oraz miesięczna opłata per czat (10 Stars), z możliwością przydzielania darmowych slotów przez administratorów.
- **Hot-reload konfiguracji** – limity i ceny przechowywane są w zmiennych środowiskowych i mogą być przeładowywane bez restartu serwera.
- **Przyjazne audytom dane** – schemat PostgreSQL przechowuje persony, aliasy, zgłoszenia, wyniki moderacji, subskrypcje oraz log audytowy.

## Czat administracyjny

Zamiast utrzymywać listę pojedynczych administratorów, platforma zakłada, że moderacja odbywa się na dedykowanych czatach Telegrama. W bazie danych rejestrowane są identyfikatory tych czatów (`admin_chats`), a każda osoba uczestnicząca w którymkolwiek z nich posiada prawa administratora. Przy rejestrowaniu działań (moderacja, przydzielanie subskrypcji, operacje na aliasach) zapisywany jest identyfikator użytkownika Telegrama oraz czatu, na którym podjęto akcję. Dzięki temu można łatwo rozszerzyć logikę o synchronizację członków czatu lub audyt działań poszczególnych moderatorów.

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
6. **Skonfiguruj listę czatów administracyjnych i webhooki Telegrama**
   - Wystaw publiczny adres HTTPS (np. za pomocą [ngrok](https://ngrok.com/)).
   - W `.env` ustaw zmienną `ADMIN_CHAT_IDS` na listę identyfikatorów czatów (grup/prywatnych kanałów), w których znajdują się moderatorzy. Każda osoba obecna na tych czatach otrzyma w systemie uprawnienia administracyjne.
   - Dla każdego tokena z listy `BOT_TOKENS` ustaw webhook na adres:
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
3. Po uruchomieniu usług (kontener `postgres` uzyska status „healthy”) możesz wejść do kontenera aplikacji i uruchomić migracje:
   ```bash
   docker compose run --rm app alembic upgrade head
   ```
4. Zatrzymanie całego stosu:
   ```bash
   docker compose down
   ```

## Zmienne środowiskowe – źródła i wskazówki

Po skopiowaniu `.env.example` uzupełnij przede wszystkim poniższe wpisy:

| Zmienna | Jak zdobyć / rekomendowana wartość |
| --- | --- |
| `BOT_TOKENS` | Lista tokenów botów wydanych przez [@BotFather](https://t.me/BotFather). Dla każdego potrzebnego bota wykonaj `/newbot`, a otrzymane tokeny wpisz po przecinku, np. `123456:AAA,654321:BBB`. |
| `WEBHOOK_SECRET` | Dowolny losowy, trudny do odgadnięcia ciąg znaków. Można go wygenerować poleceniem `openssl rand -hex 32`. Wartość ta trafia do parametru `secret` podczas konfiguracji webhooków i zabezpiecza endpointy przed nieautoryzowanym użyciem. |
| `ADMIN_CHAT_IDS` | Lista identyfikatorów czatów administracyjnych w Telegramie (oddzielonych przecinkami). Każdy uczestnik tych czatów jest traktowany jako administrator, a jego działania będą rejestrowane z użyciem identyfikatora użytkownika. |
| `DATABASE_URL` | Adres połączenia z bazą PostgreSQL w formacie `postgresql+asyncpg://user:password@host:port/database`. W środowisku Docker Compose domyślny wpis z `.env.example` będzie poprawny. |

Pozostałe wartości (limity, ceny, ustawienia logowania) można zostawić domyślne lub dostosować do potrzeb. Aplikacja wspiera „hot reload” konfiguracji – zmiana `.env` i ponowne przeładowanie zmiennych środowiskowych (np. restart procesu lub odczyt w harmonogramie) aktualizuje limity w locie.

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
