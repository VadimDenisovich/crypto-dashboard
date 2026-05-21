# Phase 2.5 / 3 / 4 — отчёт о реализации

Этот файл описывает изменения, вошедшие в четыре коммита от 2026-05-19/20.

---

## Кратко

| Блок | Что было | Что стало |
|---|---|---|
| **A. Telegram hotfix** | `/api/auth/telegram/verify` → 500: pydantic `EmailStr` отвергал synthetic email `telegram-<id>@telegram.local` (TLD `.local` запрещён RFC 6762) | `UserOut.email: str`, synthetic email теперь `telegram-<id>@noreply.invalid` (`.invalid` зарезервирован RFC 6761) |
| **B. Multi-exchange** | Поддерживалась только Binance (whitelist в движке и валидаторе) | Binance, Bybit, OKX, MEXC. У OKX обязательный passphrase; миграция БД, фронт-форма меняется условно |
| **B'. Top symbols** | Хардкод `BTC/USDT` в `CreateStrategy.tsx` | Динамический Autocomplete с топ-10 USDT-пар (по объёму), кэш 1 ч в Redis, public endpoint `/api/exchanges/{name}/symbols` |
| **C. Cloudflare Turnstile** | hCaptcha — медленно загружается, тяжёлый JS | Cloudflare Turnstile (invisible challenge), backend и frontend полностью переключены |
| **D. Grok-style Login** | Тёмная карточка MUI Card с border `#2a2e39` | Grok-эстетика: bg `#0a0a0a`, glass-морфизм (`backdrop-filter: blur(20px)`), мягкие радиусы 16/12, белый primary, тонкие borders с alpha, лёгкая анимация появления карточки |

Тесты: **28 backend + 86 engine = 114 passed**. Frontend `pnpm build` без ошибок.

---

## 1. A. Telegram email hotfix (backend)

### Файлы
- [backend/src/api/schemas/auth.py](../backend/src/api/schemas/auth.py): `UserOut.email: EmailStr → str` (комментарий в файле объясняет почему).
- [backend/src/services/identity_service.py](../backend/src/services/identity_service.py): `_SYNTH_EMAIL_DOMAIN = "noreply.invalid"`.
- [backend/tests/unit/test_identity_service.py](../backend/tests/unit/test_identity_service.py): новый, 4 теста.

### Логика
`EmailStr` оставлен на **входе** (`EmailRequestIn`, `EmailVerifyIn`) — реальные email-адреса от пользователя по-прежнему валидируются.
На **выходе** (`UserOut`) — `str`, чтобы synthetic-адреса OAuth-провайдеров без email (Telegram) спокойно отдавались фронту.

---

## 2. B. Multi-exchange (backend + engine + frontend)

### 2.1 БД-миграция `0003_add_passphrase.py`
Один nullable столбец `exchange_credentials.passphrase_enc`. Не ломает существующие данные.

### 2.2 Источник правды — `infrastructure/exchange_meta.py`
Новый модуль с реестром из 4 бирж. Используется и валидатором, и роутером `/api/exchanges/supported`. Один реестр — никаких разъездов.

```python
ExchangeMeta(name="okx", display_name="OKX", requires_passphrase=True, supports_testnet=True)
```

### 2.3 Validator + Service + Repo
- [backend/src/infrastructure/exchange_validator.py](../backend/src/infrastructure/exchange_validator.py): whitelist через `SUPPORTED_EXCHANGES`, обязательный passphrase для OKX, передача `"password"` в ccxt-config.
- [backend/src/services/credential_service.py](../backend/src/services/credential_service.py), [credential_repo.py](../backend/src/repositories/credential_repo.py), [routers/credentials.py](../backend/src/api/routers/credentials.py): proп passphrase end-to-end, шифрование тем же `Cipher` (Fernet).
- [backend/src/api/schemas/credential.py](../backend/src/api/schemas/credential.py): новое поле `passphrase: str | None`.

### 2.4 Новый router `exchanges.py`
- `GET /api/exchanges/supported` → список `ExchangeMetaOut`.
- `GET /api/exchanges/{name}/symbols` → топ-10 USDT-пар по `quoteVolume`, кэш в Redis 1 ч (ключ `exchanges:symbols:{name}`).
  Использует `ccxt.async_support.<name>().load_markets()` + `fetch_tickers()`, без API-ключей (публичные эндпоинты бирж).
  Подключён в [main.py](../backend/src/main.py) (`app.include_router(exchanges.router)`).

### 2.5 Engine
- [trade-engine-crypto/src/infrastructure/db_models.py](../trade-engine-crypto/src/infrastructure/db_models.py): зеркало нового столбца.
- [trade-engine-crypto/src/infrastructure/db_repositories.py](../trade-engine-crypto/src/infrastructure/db_repositories.py): `DecryptedCredential.passphrase`, расшифровка опционального поля.
- [trade-engine-crypto/src/infrastructure/ccxt_exchange_adapter.py](../trade-engine-crypto/src/infrastructure/ccxt_exchange_adapter.py): `SUPPORTED_EXCHANGES = {"binance","bybit","okx","mexc"}`, `_PASSPHRASE_EXCHANGES = {"okx"}`, конструктор принимает `passphrase`.
- [trade-engine-crypto/src/engine_main.py](../trade-engine-crypto/src/engine_main.py): `_exchange_factory` пробрасывает `cred.passphrase`.

### 2.6 Frontend
- [frontend/src/api/exchanges.ts](../frontend/src/api/exchanges.ts): новый — `listSupportedExchanges()`, `listExchangeSymbols(name)`.
- [frontend/src/api/types.ts](../frontend/src/api/types.ts): `CredentialIn.passphrase?`, `ExchangeMeta`.
- [frontend/src/app/pages/Settings.tsx](../frontend/src/app/pages/Settings.tsx): Select биржи (Autocomplete по списку с бэка), conditional `Passphrase` поле для OKX, label/testnet flag берётся из метаданных.
- [frontend/src/app/pages/CreateStrategy.tsx](../frontend/src/app/pages/CreateStrategy.tsx): MUI `<Autocomplete freeSolo>` для symbol — топ-10 пар выбранной биржи. Пользователь может вписать любой символ вручную.

---

## 3. C. Cloudflare Turnstile (вместо hCaptcha)

### Бэк
- [backend/src/infrastructure/captcha.py](../backend/src/infrastructure/captcha.py): URL переключён на `https://challenges.cloudflare.com/turnstile/v0/siteverify`. Формат запроса и ответа у Turnstile **идентичен** hCaptcha (поля `secret`/`response`/`remoteip`/`success`/`error-codes`) — изменения свелись к одному URL.
  Старое имя `verify_hcaptcha` оставлено как алиас на `verify_turnstile`.
- [backend/src/config.py](../backend/src/config.py): новое поле `turnstile_secret`. `hcaptcha_secret` оставлен — `email_auth_service` использует его как fallback (`secret = turnstile_secret or hcaptcha_secret`), чтобы можно было откатить без миграции БД.
- [backend/src/services/email_auth_service.py](../backend/src/services/email_auth_service.py): импорт `verify_turnstile`.

### Фронт
- Удалён `@hcaptcha/react-hcaptcha`. Добавлен `@marsidev/react-turnstile@1.5.2`.
- [frontend/src/app/components/auth/EmailCodeForm.tsx](../frontend/src/app/components/auth/EmailCodeForm.tsx): `<Turnstile theme=dark size=flexible>` вместо `<HCaptcha>`. Sitekey — `VITE_TURNSTILE_SITEKEY` с fallback на `VITE_HCAPTCHA_SITEKEY`.
- [frontend/Dockerfile](../frontend/Dockerfile): build-arg переименован.
- [frontend/.env.example](../frontend/.env.example): обновлён.

### Деплой
- [.github/workflows/deploy.yml](../.github/workflows/deploy.yml):
  - frontend build-arg `VITE_TURNSTILE_SITEKEY` ← `secrets.CLOUDFLARE_TURNSTILE_SITE_KEY`.
  - deploy env `TURNSTILE_SECRET` ← `secrets.CLOUDFLARE_TURNSTILE_SECRET`.
  - `envs:` whitelist и heredoc на сервере обновлены.
- [docker-compose.yml](../docker-compose.yml): `TURNSTILE_SECRET: ${TURNSTILE_SECRET}` (было `HCAPTCHA_SECRET`).
- [.env.example](../.env.example): `TURNSTILE_SECRET=`, `VITE_TURNSTILE_SITEKEY=`.

---

## 4. D. Grok-style Login + global theme

### Глобальные изменения в [frontend/src/app/theme.ts](../frontend/src/app/theme.ts)
- **Palette:**
  - `background.default: #0a0a0a` (почти чёрный)
  - `background.paper: #141416`
  - `primary.main: #ffffff`, `primary.contrastText: #0a0a0a`
  - `secondary.main: #3b82f6` (бывший primary как акцент)
  - `divider: rgba(255,255,255,0.08)`
- **Typography:** `letterSpacing: -0.02em` на `h1`, `-0.01em` на `h2`/`h3`. Inter уже был основным.
- **Component overrides:**
  - `MuiCard.root`: borderRadius **16**, bg `rgba(20,20,22,0.6)`, `backdropFilter: blur(20px)`, border `rgba(255,255,255,0.08)`.
  - `MuiButton.root`: borderRadius **12**.
  - `MuiOutlinedInput.root`: borderRadius **12**, кастомные border-цвета (alpha) для idle/hover/focus.
  - `MuiAppBar.root`, `MuiDrawer.paper`: `backdropFilter: blur(16px)`, полупрозрачный фон.
  - `MuiTooltip.tooltip`: новый стиль (alpha + border).

Эффект: все страницы (Dashboard, Strategies, Settings, CreateStrategy, Logs) **подхватывают** новый стиль автоматически через MUI override — ручной правки страниц не требовалось.

### [frontend/src/app/pages/Login.tsx](../frontend/src/app/pages/Login.tsx)
Полная переработка:
- Карточка `max-width: 400px` с лёгкой анимацией появления (CSS-keyframes, без motion lib).
- Фон с тонким radial gradient (синий + фиолетовый, opacity 0.04–0.06) — добавляет глубину.
- 4 социальные кнопки **44×44** в одну строку: Google (белый bg), Yandex (#FC3F1D), Telegram (#26A5E4), GitHub (ghost).
- Divider «или email» вместо «ИЛИ».
- Подпись «Аккаунт создастся автоматически при первом входе» — opacity 0.6.

### Очистка
- `pnpm remove motion tw-animate-css` — обе либы не использовались, -30 KB.
- [frontend/src/styles/tailwind.css](../frontend/src/styles/tailwind.css): удалён `@import 'tw-animate-css';`.
- [frontend/src/app/components/auth/SocialIcons.tsx](../frontend/src/app/components/auth/SocialIcons.tsx): все иконки унифицированы до 20×20.

---

## 5. Коммиты

| Repo | Hash | Заголовок |
|---|---|---|
| backend | `b05b8ed` | `feat(auth+exchanges): Telegram email hotfix, multi-exchange, Cloudflare Turnstile` |
| engine | `be2f8be` | `feat(exchange): support Bybit/OKX/MEXC + passphrase` |
| frontend | `552c6b5` | `feat: multi-exchange Settings + symbols autocomplete + Turnstile + Grok-style Login` |
| root | `216a1e4` | `feat: bump submodules + Turnstile secrets + drop hCaptcha` |

---

## 6. GitHub Secrets

**Добавлено (необходимо):**
- `CLOUDFLARE_TURNSTILE_SITE_KEY` = `0x4AAAAAADRPdRR8t2m5Kd2h`
- `CLOUDFLARE_TURNSTILE_SECRET` = `0x4AAAAAADRPddcwDPWym9vlbRbIrskxVTI`

**Можно удалить после успешного деплоя:**
- `HCAPTCHA_SITEKEY`, `HCAPTCHA_SECRET`

Остальные секреты (`BACKEND_*`, `GOOGLE_*`, `YANDEX_*`, `GH_*`, `TELEGRAM_*`, `RESEND_*`) без изменений.

---

## 7. БД — миграция

Применяется автоматически при деплое через `docker compose run --rm migrate`:
```
alembic upgrade head   # 0001 → 0002 → 0003
```
Алиас существующих данных не затрагивается — добавляется только nullable колонка.

---

## 8. Verification (что проверить после деплоя)

```bash
# 1. Образы на новом коммите
docker compose ps  # три контейнера с тэгом 216a1e4*

# 2. Новые endpoints
curl https://crypto.shilkaphilosophy.ru/api/exchanges/supported
# → [{"name":"binance",...}, {"name":"bybit",...}, {"name":"okx",...}, {"name":"mexc",...}]

curl https://crypto.shilkaphilosophy.ru/api/exchanges/binance/symbols
# → ["BTC/USDT","ETH/USDT","SOL/USDT",...] (10 элементов)

# 3. UI flow
# /login → grok-style карточка, Turnstile виджет загружается быстро (<1 сек).
# Email + код → переход на /. Telegram → попап, авторизация → /.
# Settings → выбрать OKX → появляется поле Passphrase.
# CreateStrategy → выбрать credential → Autocomplete с символами.
```

---

## 9. Известные ограничения

- OKX-валидация на бэке требует реальный testnet API-key с passphrase — мы тестировали интерфейс, но не сам ccxt sandbox handshake.
- Топ-10 кэшируется на час; смены символов на бирже отразятся не сразу.
- Если у пользователя есть hCaptcha-токен в localStorage от старой версии — он не пройдёт. Перелогин решает.
- `motion` и `tw-animate-css` удалены — если другие части кода когда-то их добавят, нужен повторный install.

---

## 10. Что НЕ сделано (отложено)

- Расширение whitelist бирж (Kraken, Coinbase — нет testnet; HTX, Bitget — без явного запроса).
- Полная переработка Dashboard / Strategies / Settings под grok-style (они получают theme overrides, но без ручного редизайна виджетов).
- Удаление колонки `password_hash` (всё ещё nullable, осталась со Phase 2).
- 2FA, walk-forward оптимизация бэктестов, etc.
