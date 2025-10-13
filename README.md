# Telegram Multi-Bot Quote Platform

Platforma stanowi fundament do uruchomienia wielu botów Telegrama, które odgrywają różne persony i odpowiadają cytatami dostarczonymi przez społeczność. Moderacja oraz administracja odbywają się w prywatnych czatach Telegrama.

## Najważniejsze funkcje

- **Obsługa wielu botów** – pojedynczy backend obsługuje wiele tokenów botów, a każdy bot posiada własną personę.
- **Treści od społeczności** – użytkownicy przesyłają wiadomości (tekst, obraz, audio), a administratorzy (wszyscy uczestnicy wskazanych czatów administracyjnych) zatwierdzają zgłoszenia.
- **Model subskrypcji** – jednorazowa opłata aktywacyjna (50 Telegram Stars) oraz miesięczna opłata per czat (10 Stars), z możliwością przydzielania darmowych slotów przez administratorów.
- **Hot-reload konfiguracji** – limity i ceny przechowywane są w zmiennych środowiskowych i mogą być przeładowywane bez restartu serwera.
- **Przyjazne audytom dane** – schemat PostgreSQL przechowuje persony, aliasy, zgłoszenia, wyniki moderacji, subskrypcje oraz log audytowy.

## Czat administracyjny

Platforma opiera się na jednym czacie administracyjnym w Telegramie. Jego identyfikator należy ustawić w zmiennej środowiskowej `ADMIN_CHAT_ID`. Każdy uczestnik tego czatu zyskuje uprawnienia moderatorskie, a wykonane akcje zapisują identyfikatory użytkownika i czatu bezpośrednio w polach dzienników (`*_chat_id`). Takie podejście umożliwia audyt działań bez utrzymywania dodatkowych tabel referencyjnych.

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
   Uzupełnij w nim co najmniej `WEBHOOK_SECRET`, `ADMIN_CHAT_ID` (identyfikator jedynego czatu administracyjnego) oraz wartości połączenia z bazą danych, jeśli chcesz skorzystać z zewnętrznego klastra PostgreSQL.
3. **Zbuduj i uruchom stos aplikacji**
   ```bash
   docker compose up --build
   ```
   Komenda utworzy kontenery aplikacji (`app`) i bazy (`postgres`) oraz wystawi interfejs HTTP na porcie wskazanym w `.env` (`APP_HOST_PORT`, domyślnie `8000`).
4. **Wykonaj migracje schematu**
   Po starcie usług zainicjalizuj bazę poleceniem:
   ```bash
   docker compose exec app alembic upgrade head
   ```
5. **Skonfiguruj webhooki Telegrama**
   Udostępnij aplikację pod publicznym adresem HTTPS (np. przy pomocy [ngrok](https://ngrok.com/)) i dla każdego zarządzanego bota ustaw webhook:
   ```
   https://twoj-host/telegram/<TOKEN_BOTA>?secret=<WEBHOOK_SECRET>
   ```
   Sekret w adresie musi odpowiadać wartości `WEBHOOK_SECRET` w `.env`.

## Dodawanie botów

Rejestrowanie botów odbywa się wyłącznie z poziomu czatu administracyjnego wskazanego w `ADMIN_CHAT_ID`.

1. Upewnij się, że bot operatorski platformy został dodany do czatu administracyjnego i wywołaj w nim komendę `/start`.
2. Z menu bota wybierz akcję „Dodaj bota” (lub odpowiadającą jej komendę tekstową) i wklej token otrzymany od [@BotFather](https://t.me/BotFather).
3. Wybierz lub utwórz personę, która ma być przypisana do nowego bota. Platforma poprosi o opis i język, aby spójnie odpowiadać użytkownikom.
4. Po zatwierdzeniu bot jest zapisywany w bazie danych i natychmiast dostępny. W razie potrzeby możesz wymusić przeładowanie cache tokenów wywołując endpoint:
   ```bash
   curl -X POST \
        -H "X-Telegram-Bot-Api-Secret-Token: ${WEBHOOK_SECRET}" \
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

3. **Szybki test webhooka** – po ustawieniu webhooków w Telegramie możesz wysłać wiadomość do bota i obserwować logi aplikacji (`uvicorn` wypisze zdarzenia przychodzące). W przypadku problemów sprawdź nagłówki `X-Telegram-Bot-Api-Secret-Token` i upewnij się, że pokrywają się z `WEBHOOK_SECRET`.
6. **Skonfiguruj boty i webhooki Telegrama**
   - Upewnij się, że w tabeli `bots` znajdują się wpisy z uzupełnionym polem `api_token` oraz ustawioną flagą `is_active=true` (szczegóły znajdziesz w sekcji [Dodawanie pierwszego bota](#dodawanie-pierwszego-bota)).
   - W `.env` ustaw zmienną `ADMIN_CHAT_IDS` na listę identyfikatorów czatów (grup/prywatnych kanałów), w których znajdują się moderatorzy. Każda osoba obecna na tych czatach otrzyma w systemie uprawnienia administracyjne.
   - Wystaw publiczny adres HTTPS (np. za pomocą [ngrok](https://ngrok.com/)).
   - Dla każdego tokena z bazy ustaw webhook na adres:
     ```
     https://twoj-host/telegram/<TOKEN_BOTA>?secret=<WEBHOOK_SECRET>
     ```
   - Sekret (`WEBHOOK_SECRET`) musi zgadzać się z wartością w `.env`.

## Dodawanie pierwszego bota

Po wykonaniu migracji baza danych jest pusta. Aby zarejestrować pierwszego bota oraz nadać mu personę i czaty administracyjne, wykonaj poniższe kroki (przykład zakłada użycie `psql` i lokalnej bazy `user_bot`).

1. **Dodaj czat administracyjny** – każdy uczestnik tego czatu będzie miał uprawnienia administratora w panelu moderatorów.
   ```sql
   INSERT INTO admin_chats (chat_id, title, created_at, is_active)
   VALUES (-1001234567890, 'Moderatorzy', NOW(), TRUE)
   ON CONFLICT (chat_id) DO NOTHING;
   ```

2. **Utwórz personę** – boty muszą być powiązane z personami opisującymi ich charakter.
   ```sql
   INSERT INTO personas (name, description, language, created_at, is_active)
   VALUES ('Cytaty klasyków', 'Bot cytujący klasyków literatury', 'pl', NOW(), TRUE)
   RETURNING id;
   ```
   Zanotuj wartość `id`, będzie potrzebna w kolejnym kroku.

3. **Przygotuj hash tokena** – kolumna `token_hash` przechowuje kryptograficzny skrót tokena. Użyj `sha512`, aby zachować zgodność z limitem 128 znaków:
   ```bash
   python - <<'PY'
   import hashlib

   token = "1234567890:ABCDEF"  # wstaw token wygenerowany przez @BotFather
   print(hashlib.sha512(token.encode()).hexdigest())
   PY
   ```
   Skopiuj wynik (128-znakowy ciąg hex).

4. **Dodaj bota** – uzupełnij pola `api_token`, `token_hash` oraz przypisz wcześniej utworzoną personę.
   ```sql
   INSERT INTO bots (api_token, token_hash, display_name, persona_id, created_at, is_active)
   VALUES (
       '1234567890:ABCDEF',
       '<WYNIK_SHA512>',
       'Cytaty klasyków',
       <ID_PERSONY>,
       NOW(),
       TRUE
   )
   RETURNING id;
   ```

5. **Przeładuj cache tokenów** – aby działająca aplikacja od razu wczytała nowego bota, wywołaj endpoint reload (podstaw swój sekret i adres hosta):
   ```bash
   curl -X POST \
        -H "X-Telegram-Bot-Api-Secret-Token: ${WEBHOOK_SECRET}" \
        http://localhost:8000/internal/reload-config
   ```
   Oczekuj odpowiedzi `{"status": "reloaded"}`.

## Jak sprawdzić, czy aplikacja działa poprawnie?

1. **Kontrola zdrowia serwisu** – wywołaj endpoint `/healthz` bez nagłówków uwierzytelniających:
   ```bash
   curl http://localhost:8000/healthz
   ```
   Jeśli wszystko działa, otrzymasz odpowiedź podobną do `{"status": "ok", "bots": 1}` – liczba w polu `bots` oznacza, ile aktywnych tokenów wczytano z bazy.

2. **Inspekcja API** – odwiedź [http://localhost:8000/docs](http://localhost:8000/docs), aby upewnić się, że FastAPI wystawia dokumentację OpenAPI i endpointy działają.

3. **Szybki test webhooka** – po ustawieniu webhooków w Telegramie możesz wysłać wiadomość do bota i obserwować logi aplikacji (`uvicorn` wypisze zdarzenia przychodzące). W przypadku problemów sprawdź nagłówki `X-Telegram-Bot-Api-Secret-Token` i upewnij się, że pokrywają się z `WEBHOOK_SECRET`.

## Uruchomienie przez Docker Compose

1. Skopiuj plik konfiguracyjny i wypełnij zmienne jak w [Szybkim starcie](#szybki-start-docker-compose):
   ```bash
   cp .env.example .env
   ```
2. (Opcjonalnie) jeżeli port `8000` na hoście jest zajęty, ustaw w `.env` zmienną `APP_HOST_PORT` na wolny numer (np. `8080`).

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

## Zmienne środowiskowe – źródła i wskazówki

Po skopiowaniu `.env.example` uzupełnij przede wszystkim poniższe wpisy:

| Zmienna | Jak zdobyć / rekomendowana wartość |
| --- | --- |
| `WEBHOOK_SECRET` | Dowolny losowy, trudny do odgadnięcia ciąg znaków. Można go wygenerować poleceniem `openssl rand -hex 32`. Wartość ta trafia do parametru `secret` podczas konfiguracji webhooków i zabezpiecza endpointy przed nieautoryzowanym użyciem. |
| `ADMIN_CHAT_ID` | Identyfikator jedynego czatu administracyjnego w Telegramie. Wszyscy uczestnicy tego czatu uzyskują uprawnienia moderatorskie, a ich akcje są rejestrowane z użyciem surowego ID czatu. |
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
