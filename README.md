# Telegram Multi-Bot Quote Platform

Platforma stanowi fundament do uruchomienia wielu botów Telegrama, które odgrywają różne persony i odpowiadają cytatami dostarczonymi przez społeczność. Moderacja oraz administracja odbywają się w prywatnych czatach Telegrama.

## Najważniejsze funkcje

- **Obsługa wielu botów** – pojedynczy backend obsługuje wiele tokenów botów, a każdy bot posiada własną personę.
- **Treści od społeczności** – użytkownicy przesyłają wiadomości (tekst, obraz, audio), a administratorzy (wszyscy uczestnicy wskazanych czatów administracyjnych) zatwierdzają zgłoszenia.
- **Model subskrypcji** – jednorazowa opłata aktywacyjna (50 Telegram Stars) oraz miesięczna opłata per czat (10 Stars), z możliwością przydzielania darmowych slotów przez administratorów.
- **Hot-reload konfiguracji** – limity i ceny przechowywane są w zmiennych środowiskowych i mogą być przeładowywane bez restartu serwera.
- **Przyjazne audytom dane** – schemat PostgreSQL przechowuje persony, aliasy, zgłoszenia, wyniki moderacji, subskrypcje oraz log audytowy.

## Czat administracyjny

Platforma opiera się na jednym czacie administracyjnym w Telegramie. Jego identyfikator należy ustawić w zmiennej środowiskowej `USER_BOT_ADMIN_CHAT_ID` (dla zgodności wspierane jest także dawne `ADMIN_CHAT_ID`). Każdy uczestnik tego czatu zyskuje uprawnienia moderatorskie, a wykonane akcje zapisują identyfikatory użytkownika i czatu bezpośrednio w polach dzienników (`*_chat_id`). Takie podejście umożliwia audyt działań bez utrzymywania dodatkowych tabel referencyjnych.

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

## Szybki start (Docker Compose)

1. **Sklonuj repozytorium i przejdź do katalogu projektu**
   ```bash
   git clone <adres_repo>
   cd user_bot
   ```
2. **Skopiuj plik konfiguracyjny**
   ```bash
   cp .env.example .env
   ```
   Uzupełnij w nim co najmniej `USER_BOT_WEBHOOK_SECRET`, `USER_BOT_ADMIN_CHAT_ID` (identyfikator jedynego czatu administracyjnego) oraz wartości połączenia z bazą danych (`USER_BOT_DATABASE_URL`), jeśli chcesz skorzystać z zewnętrznego klastra PostgreSQL.
3. **Zbuduj i uruchom stos aplikacji**
   ```bash
   docker compose up --build
   ```
   Komenda utworzy kontenery aplikacji (`app`) i bazy (`postgres`) oraz wystawi interfejs HTTP na porcie wskazanym w `.env` (`USER_BOT_APP_HOST_PORT`, domyślnie `8100`).
4. **Wykonaj migracje schematu**
   Po starcie usług zainicjalizuj bazę poleceniem:
   ```bash
   docker compose exec app alembic upgrade head
   ```
5. **Skonfiguruj webhooki Telegrama**
   Udostępnij aplikację pod publicznym adresem HTTPS (np. przy pomocy [ngrok](https://ngrok.com/)) i dla każdego zarządzanego bota ustaw webhook:
   ```
   https://twoj-host/telegram/<TOKEN_BOTA>?secret=<USER_BOT_WEBHOOK_SECRET>
   ```
   Sekret w adresie musi odpowiadać wartości `USER_BOT_WEBHOOK_SECRET` w `.env`.

## Dodawanie botów

Rejestrowanie botów odbywa się wyłącznie z poziomu czatu administracyjnego wskazanego w `USER_BOT_ADMIN_CHAT_ID`.

1. Upewnij się, że bot operatorski platformy został dodany do czatu administracyjnego i wywołaj w nim komendę `/start`. Bot pokaże menu z przyciskami: „Dodaj bota”, „Lista botów” oraz „Odśwież tokeny”.
2. Z menu bota wybierz akcję „Dodaj bota” i wklej token otrzymany od [@BotFather](https://t.me/BotFather). W razie pomyłki możesz przerwać proces poleceniem `/anuluj`.
3. Wybierz istniejącą personę z listy lub utwórz nową (bot poprosi o nazwę, opis oraz kod języka – domyślnie `auto`).
4. Po zatwierdzeniu bot jest zapisywany w bazie danych i natychmiast dostępny. Cache tokenów odświeża się automatycznie, a jeśli ustawiono `USER_BOT_WEBHOOK_BASE_URL`, aplikacja ustawi webhook w Telegramie za Ciebie.
5. Aby wrócić do menu w dowolnym momencie, użyj komendy `/menu`.

Lista botów oraz person jest dostępna z poziomu przycisku „Lista botów”. Każda pozycja zawiera nazwę i identyfikator rekordu w bazie, co ułatwia dalszą administrację.

W razie potrzeby możesz też wymusić przeładowanie cache tokenów wywołując endpoint:
   ```bash
   curl -X POST \
        -H "X-Telegram-Bot-Api-Secret-Token: ${USER_BOT_WEBHOOK_SECRET}" \
        http://localhost:8000/internal/reload-config
   ```

Manualne modyfikacje w bazie danych (np. poprzez `INSERT`) nie są wspierane i mogą zostać nadpisane przez logikę czatu administracyjnego.

## Jak sprawdzić, czy aplikacja działa poprawnie?

1. **Kontrola zdrowia serwisu** – wywołaj endpoint `/healthz` bez nagłówków uwierzytelniających:
   ```bash
   curl http://localhost:8000/healthz
   ```
   Jeśli wszystko działa, otrzymasz odpowiedź podobną do `{"status": "ok", "bots": 1}` – liczba w polu `bots` oznacza, ile aktywnych tokenów wczytano z bazy.

2. **Inspekcja API** – odwiedź [http://localhost:8000/docs](http://localhost:8000/docs), aby upewnić się, że FastAPI wystawia dokumentację OpenAPI i endpointy działają.

3. **Szybki test webhooka** – po ustawieniu webhooków w Telegramie możesz wysłać wiadomość do bota i obserwować logi aplikacji (`uvicorn` wypisze zdarzenia przychodzące). W przypadku problemów sprawdź nagłówki `X-Telegram-Bot-Api-Secret-Token` i upewnij się, że pokrywają się z `USER_BOT_WEBHOOK_SECRET`.
6. **Skonfiguruj boty i webhooki Telegrama**
   - Upewnij się, że w tabeli `bots` znajdują się wpisy z uzupełnionym polem `api_token` oraz ustawioną flagą `is_active=true` (szczegóły znajdziesz w sekcji [Dodawanie pierwszego bota](#dodawanie-pierwszego-bota)).
   - W `.env` ustaw zmienną `USER_BOT_ADMIN_CHAT_ID` na identyfikator jedynego czatu administracyjnego. Wszyscy uczestnicy tego czatu uzyskają uprawnienia moderatorskie.
   - Wystaw publiczny adres HTTPS (np. za pomocą [ngrok](https://ngrok.com/)).
   - Ustaw zmienną `USER_BOT_WEBHOOK_BASE_URL` na publiczny adres (np. `https://twoj-host`). Dzięki temu aplikacja automatycznie ustawi lub zaktualizuje webhook po dodaniu bota.
   - Jeśli wolisz ręczną konfigurację, ustaw webhook na adres:
     ```
     https://twoj-host/telegram/<TOKEN_BOTA>?secret=<USER_BOT_WEBHOOK_SECRET>
     ```
     Sekret (`USER_BOT_WEBHOOK_SECRET`) musi zgadzać się z wartością w `.env`.

## Dodawanie pierwszego bota

Po wykonaniu migracji baza danych jest pusta. Aby zarejestrować pierwszego bota operatorskiego i uruchomić panel administracyjny:

1. **Skonfiguruj czat administracyjny w `.env`.**  
   Ustaw `USER_BOT_ADMIN_CHAT_ID` na identyfikator jedynego czatu administracyjnego (np. prywatnej grupy). Po zapisaniu pliku zrestartuj kontener `app` lub wywołaj endpoint `/internal/reload-config`, aby aplikacja wczytała nowe ustawienia.

2. **Uruchom skrypt bootstrapujący bota operatorskiego.**  
   Skrypt tworzy (jeśli trzeba) personę operatorską i zapisuje token bota w tabeli `bots`. Uruchom go w kontenerze aplikacji:
   ```bash
   docker compose run --rm app \
     python -m bot_platform.scripts.bootstrap_operator_bot "<TOKEN_Z_BOTFATHER>" \
     --display-name "Bot operatorski" \
     --persona-name "Persona operatorska" \
     --language "pl"
   ```
   Jeśli bot z podanym tokenem już istnieje, wpis zostanie zaktualizowany (token otrzyma nową nazwę/personę, a flaga `is_active` zostanie ustawiona na `true`).

3. **Przeładuj cache tokenów (opcjonalnie, ale zalecane po bootstrapie).**
   ```bash
   curl -X POST \
        -H "X-Telegram-Bot-Api-Secret-Token: ${USER_BOT_WEBHOOK_SECRET}" \
        http://localhost:8000/internal/reload-config
   ```
   Po tej operacji bot operatorski będzie dostępny w interfejsie.

4. **Dodaj bota operatorskiego do czatu i otwórz panel.**  
   Zaproś bota na skonfigurowany czat administracyjny, wyślij `/start` i korzystaj z menu kontekstowego. Od tej chwili wszystkie dalsze operacje (tworzenie person, dodawanie kolejnych botów, zarządzanie nimi) wykonujesz już z poziomu czatu.

5. **Skonfiguruj webhooki dla nowych botów.**  
   Użyj procedury opisanej w sekcji [Skonfiguruj boty i webhooki Telegrama](#skonfiguruj-boty-i-webhooki-telegrama), aby każdy bot otrzymał poprawny adres webhooka i wspólny `USER_BOT_WEBHOOK_SECRET`.

## Jak sprawdzić, czy aplikacja działa poprawnie?

1. **Kontrola zdrowia serwisu** – wywołaj endpoint `/healthz` bez nagłówków uwierzytelniających:
   ```bash
   curl http://localhost:8000/healthz
   ```
   Jeśli wszystko działa, otrzymasz odpowiedź podobną do `{"status": "ok", "bots": 1}` – liczba w polu `bots` oznacza, ile aktywnych tokenów wczytano z bazy.

2. **Inspekcja API** – odwiedź [http://localhost:8000/docs](http://localhost:8000/docs), aby upewnić się, że FastAPI wystawia dokumentację OpenAPI i endpointy działają.

3. **Szybki test webhooka** – po ustawieniu webhooków w Telegramie możesz wysłać wiadomość do bota i obserwować logi aplikacji (`uvicorn` wypisze zdarzenia przychodzące). W przypadku problemów sprawdź nagłówki `X-Telegram-Bot-Api-Secret-Token` i upewnij się, że pokrywają się z `USER_BOT_WEBHOOK_SECRET`.

## Uruchomienie przez Docker Compose

1. Skopiuj plik konfiguracyjny i wypełnij zmienne jak w [Szybkim starcie](#szybki-start-docker-compose):
   ```bash
   cp .env.example .env
   ```
2. (Opcjonalnie) jeżeli port `8100` na hoście jest zajęty, ustaw w `.env` zmienną `USER_BOT_APP_HOST_PORT` na wolny numer (np. `8080`).

3. Zbuduj obraz i wystartuj usługi (aplikacja + PostgreSQL):
   ```bash
   docker compose up --build
   ```
   Jeśli zmienisz `Dockerfile`, dla pewności przebuduj obraz poleceniem `docker compose build app` przed kolejnym krokiem.
4. Po uruchomieniu usług (kontener `postgres` uzyska status „healthy”) wykonaj migracje bezpośrednio na działającym kontenerze aplikacji:
   ```bash
   docker compose exec app alembic upgrade head
   ```
   Jeżeli preferujesz jednorazowy kontener, możesz użyć:
   ```bash
   docker compose run --rm app alembic upgrade head
   ```
   (Czas pierwszego uruchomienia może być dłuższy, bo obraz zostanie przebudowany z uwzględnieniem plików Alembica.)
5. Zatrzymanie całego stosu:
   ```bash
   docker compose down
   ```

## Reverse proxy (Nginx)

W katalogu `deploy/nginx` znajdziesz przykładową konfigurację `bot.content.run.place.conf`,
która (analogicznie do `content_manager`) zawiera blok HTTP→HTTPS, lokalizację dla Certbota oraz proxy
do kontenera `app` nasłuchującego na porcie 8100.
Skopiuj plik na serwer, uaktualnij ścieżki certyfikatów (np. `/etc/letsencrypt/live/bot.content.run.place/...`),
ewentualnie zmień katalog ACME i włącz konfigurację w Nginx – np. poprzez symlinka w `sites-enabled`.

## Zmienne środowiskowe – źródła i wskazówki

Po skopiowaniu `.env.example` uzupełnij przede wszystkim poniższe wpisy:

| Zmienna | Jak zdobyć / rekomendowana wartość |
| --- | --- |
| `USER_BOT_WEBHOOK_SECRET` | Dowolny losowy, trudny do odgadnięcia ciąg znaków. Można go wygenerować poleceniem `openssl rand -hex 32`. Wartość ta trafia do parametru `secret` podczas konfiguracji webhooków i zabezpiecza endpointy przed nieautoryzowanym użyciem (dla zgodności nadal działa dawne `WEBHOOK_SECRET`). |
| `USER_BOT_WEBHOOK_BASE_URL` | Publiczny adres HTTPS instancji (np. `https://bot.example.com`). Dzięki niemu aplikacja automatycznie ustawia webhooki po dodaniu lub aktualizacji bota. Pozostaw puste, jeśli chcesz wykonywać tę operację ręcznie. |
| `USER_BOT_ADMIN_CHAT_ID` | Identyfikator jedynego czatu administracyjnego w Telegramie. Dla supergrup Telegram zwraca wartości ujemne (np. `-1001234567890`) – przepisz je dokładnie z botów typu `@RawDataBot`. Wszyscy uczestnicy tego czatu uzyskują uprawnienia moderatorskie, a ich akcje są rejestrowane z użyciem surowego ID czatu. |
| `USER_BOT_DATABASE_URL` | Adres połączenia z bazą PostgreSQL w formacie `postgresql+asyncpg://user:password@host:port/database`. W środowisku Docker Compose domyślny wpis z `.env.example` będzie poprawny. |
| `USER_BOT_MODERATION_CHAT_ID` | Liczbowe ID czatu (lub kanału) Telegram, w którym moderatorzy mają otrzymywać powiadomienia. Najłatwiej je pozyskać wysyłając dowolną wiadomość do bota `@userinfobot` z danego czatu lub korzystając z narzędzi typu [@RawDataBot](https://t.me/RawDataBot). |

Pozostałe wartości (limity, ceny, ustawienia logowania) można zostawić domyślne lub dostosować do potrzeb. Aplikacja wspiera „hot reload” konfiguracji – zmiana `.env` i ponowne przeładowanie zmiennych środowiskowych (np. restart procesu lub odczyt w harmonogramie) aktualizuje limity w locie.

Tokeny botów są przechowywane bezpośrednio w bazie (kolumna `bots.api_token`). Dzięki temu można je podmieniać bez restartu aplikacji – wystarczy zaktualizować rekord i wywołać endpoint `/internal/reload-config`.

## Migracje bazy danych

Repozytorium zawiera gotową konfigurację Alembic (`alembic.ini` oraz katalog `alembic/`). Aby zsynchronizować schemat bazy z modelami:

```bash
alembic upgrade head
```

Pamiętaj o ustawieniu zmiennej `USER_BOT_DATABASE_URL` przed uruchomieniem polecenia (np. `export USER_BOT_DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/dbname`; starsza nazwa `DATABASE_URL` nadal jest rozpoznawana).

## Testy

Na ten moment repozytorium nie zawiera testów automatycznych. Proponowane polecenie do uruchamiania własnych testów:

```bash
pytest
```

## Autodeploy (GitHub Actions)

Repozytorium zawiera workflow `.github/workflows/deploy.yml`, który po każdym pushu do gałęzi `production`:

- uruchamia testy (`pytest`) na Pythonie 3.11,
- po sukcesie loguje się na serwer produkcyjny przez SSH i odświeża kontenery Docker Compose.

Aby go włączyć, ustaw w ustawieniach repozytorium sekrety GitHub Actions:

| Sekret | Opis |
| --- | --- |
| `VPS_HOST` | Adres IP lub domena serwera produkcyjnego. |
| `VPS_USER` | Użytkownik z uprawnieniami do wykonywania poleceń Docker na serwerze. |
| `VPS_SSH_KEY` | Prywatny klucz SSH (format PEM) przypisany do powyższego użytkownika. |
| `VPS_APP_PATH` | Ścieżka do katalogu projektu na serwerze (np. `/opt/user_bot`). Jeśli nie ustawisz, domyślnie użyjemy `/opt/user_bot`. |
| `VPS_IMAGE` | (Opcjonalnie) Pełna nazwa obrazu GHCR, który ma zostać pobrany podczas deployu. Pozostaw puste, by budować na serwerze. |
| `GHCR_PAT` | (Opcjonalnie) Personal Access Token z uprawnieniem `packages:read` do autoryzacji w GHCR. |

Workflow zakłada, że na serwerze działają `git` oraz `docker compose`, a plik `.env` jest już skonfigurowany.
W razie potrzeby możesz odpalić deploy ręcznie przez „Run workflow” (akcja `workflow_dispatch`).

## Deploy script

Na serwerze możesz uruchomić `./deploy.sh`. Skrypt automatycznie wczytuje zmienne z `.env`,
wykonuje `docker compose pull`, `docker compose up -d --build`, uruchamia migracje Alembic
(`docker compose run --rm app alembic upgrade head`) oraz sprząta obrazy (`docker image prune -f`).
Jeżeli repozytorium znajduje się w innym katalogu niż katalog skryptu, ustaw zmienną
`USER_BOT_REPO_DIR=/ścieżka/do/user_bot` przed uruchomieniem.

Skrypt sprawdza teraz, czy we wskazanym katalogu dostępny jest plik(a) Docker Compose (domyślnie
`docker-compose.yml`, można go nadpisać zmienną `USER_BOT_COMPOSE_FILE`). Przy jego braku zostanie
zwrócony czytelny komunikat zamiast komunikatu z `docker compose`.

Jeżeli ustawisz zmienną `USER_BOT_IMAGE`, zostanie ona użyta jako źródło obrazu aplikacji – skrypt wykona
logowanie do GHCR (jeśli podano `USER_BOT_GHCR_USER` i `USER_BOT_GHCR_PAT`), pobierze obraz i uruchomi kontenery
bez przebudowy lokalnej (`docker compose up --no-build`). Aby wymusić budowanie mimo ustawionego
obrazu, ustaw `USER_BOT_FORCE_BUILD=1`.

Na serwerze możesz także skopiować `deploy/.env.production` do `/opt/user_bot/.env` i ewentualnie zaktualizować wartości dla środowiska produkcyjnego (np. `USER_BOT_DATABASE_URL`, `USER_BOT_WEBHOOK_SECRET`). Skrypt `deploy.sh` automatycznie wczyta ten plik podczas uruchomienia.

## HTTPS / certyfikaty Let's Encrypt

1. Skopiuj plik `deploy/nginx/bot.content.run.place.conf` na serwer jako `/etc/nginx/sites-available/bot.content.run.place`.
2. Upewnij się, że sekcja HTTP zawiera: `location /.well-known/acme-challenge/ { root /var/www/html; }` (lub inny katalog webroot).
3. Uruchom Certbota w trybie webroot, np.:
   ```bash
   sudo certbot certonly --webroot \\
     -w /var/www/html \\
     -d bot.content.run.place
   ```
   Certyfikaty trafią do `/etc/letsencrypt/live/bot.content.run.place/`.
4. W pliku Nginx w sekcji HTTPS ustaw:
   ```nginx
   ssl_certificate     /etc/letsencrypt/live/bot.content.run.place/fullchain.pem;
   ssl_certificate_key /etc/letsencrypt/live/bot.content.run.place/privkey.pem;
   ```
   Jeśli używasz innego katalogu webroot, zaktualizuj też ścieżki w blokach ACME.
5. Utwórz symlink i włącz vhost:
   ```bash
   sudo ln -s /etc/nginx/sites-available/bot.content.run.place \\
             /etc/nginx/sites-enabled/bot.content.run.place
   ```
6. Sprawdź konfigurację (`sudo nginx -t`) i przeładuj serwer: `sudo systemctl reload nginx`.
7. Upewnij się, że proces odnowienia certyfikatów (cron/systemd timer Certbota) korzysta z tego samego webroota.
