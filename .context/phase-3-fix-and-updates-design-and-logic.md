# Phase 2.5 / 8 / 9 / 10 — Auth hotfix + Multi-exchange + Turnstile + Grok-style Login

## Context

После Phase 2 (Identity Providers) на проде вылезли проблемы и появились новые требования:

1. **Telegram login → 500.** Логи бэка показывают `value is not a valid email address: The part after the @-sign is a special-use or reserved name that cannot be used with email. input_value='telegram-463431445@telegram.local'`. HMAC и выпуск JWT проходят успешно, но затем `UserOut.model_validate(user)` ([backend/src/api/schemas/auth.py](backend/src/api/schemas/auth.py)) падает на synthetic email из [identity_service.py:_synth_email](backend/src/services/identity_service.py): TLD `.local` запрещён `email-validator` (RFC 6761 special-use).
2. **hCaptcha медленный** — заменяем на Cloudflare Turnstile (пользователь дал ключи: site `0x4AAAAAADRPdRR8t2m5Kd2h`, secret `0x4AAAAAADRPddcwDPWym9vlbRbIrskxVTI`).
3. **Добавить биржи** — Bybit, OKX, MEXC (Kraken/Coinbase без testnet → пропускаем). OKX требует `passphrase` — нужна миграция БД.
4. **Динамический список монет** — endpoint `GET /api/exchanges/{name}/symbols` с кэшем в Redis, фронт показывает топ-10 пар против USDT через MUI Autocomplete.
5. **Login в стиле grok.com** — глобальный theme override (палитра, glass-morphism, soft radius), переписать только `/login` (остальные страницы подхватят override). Остальные не трогаем.

Все правки разбиваются на **четыре атомарных PR-набора** (можно мерджить отдельно):
- A) Hotfix Telegram email
- B) Multi-exchange (+passphrase, +symbols endpoint, +Settings/CreateStrategy фронт)
- C) Turnstile (вместо hCaptcha)
- D) Grok-style Login

---

## A) Hotfix Telegram email — `[BACKEND]`

### A.1 Послабить EmailStr в UserOut
Файл: [backend/src/api/schemas/auth.py](backend/src/api/schemas/auth.py).

```python
# было
class UserOut(BaseModel):
    email: EmailStr
# стало
class UserOut(BaseModel):
    email: str   # synthetic emails (.local TLD от Telegram) валидны как идентификатор
```

`EmailStr` всё ещё остаётся в `EmailRequestIn`/`EmailVerifyIn` ([email_auth.py](backend/src/api/schemas/email_auth.py)) — там это вход, и проверка нужна.

### A.2 Сменить synthetic-домен (защита на будущее)
Файл: [backend/src/services/identity_service.py:_synth_email](backend/src/services/identity_service.py).

```python
# было
def _synth_email(provider: str, subject: str) -> str:
    return f"{provider}-{subject}@{provider}.local"
# стало (используем реальный поддомен фронта)
_SYNTH_EMAIL_DOMAIN = "noreply.invalid"  # либо вытащим в Settings.synthetic_email_domain
def _synth_email(provider: str, subject: str) -> str:
    return f"{provider}-{subject}@{_SYNTH_EMAIL_DOMAIN}"
```

Альтернативно — использовать домен сайта (`noreply.crypto.shilkaphilosophy.ru`), это пройдёт даже строгий валидатор.

### A.3 Тест
Файл: [backend/tests/unit/test_identity_service.py](backend/tests/unit/test_identity_service.py) (новый, минимальный):
- `_synth_email("telegram", "12345")` валиден через `email_validator.validate_email(..., check_deliverability=False)`.

---

## B) Multi-exchange + per-exchange passphrase + symbols selector — `[BACKEND]` `[ENGINE]` `[FRONTEND]`

### B.1 БД миграция `0003_add_passphrase.py`
Файл: `backend/alembic/versions/0003_add_passphrase.py`.

```python
op.add_column(
    "exchange_credentials",
    sa.Column("passphrase_enc", sa.String, nullable=True),
)
```

Понятно: nullable — большинство бирж его не требуют.

### B.2 Бэк: schema + сервис + валидатор + репо
- [backend/src/models/exchange_credential.py](backend/src/models/exchange_credential.py): `passphrase_enc: Mapped[str | None] = mapped_column(String, nullable=True)`.
- [backend/src/api/schemas/credential.py](backend/src/api/schemas/credential.py): `passphrase: str | None = Field(default=None, min_length=1, max_length=256)`.
- [backend/src/infrastructure/exchange_validator.py](backend/src/infrastructure/exchange_validator.py): `_build_client(..., passphrase: str | None = None)` → добавляет `"passphrase": passphrase` в ccxt-config, если задан.
- [backend/src/services/credential_service.py](backend/src/services/credential_service.py): `create_for_user(..., passphrase: str | None = None)` → передаёт в validator и шифрует через `self._cipher.encrypt(passphrase)` для `passphrase_enc`.
- [backend/src/repositories/credential_repo.py](backend/src/repositories/credential_repo.py): `create(..., passphrase_enc: str | None = None)`.
- [backend/src/api/routers/credentials.py](backend/src/api/routers/credentials.py): пробросить `body.passphrase`.

**Whitelist бирж (анти-typo):** `_SUPPORTED_EXCHANGES = {"binance", "bybit", "okx", "mexc"}` в [exchange_validator.py](backend/src/infrastructure/exchange_validator.py). Раньше было `hasattr(ccxt, exchange)` — слишком широко (любой typo проходит).

**Per-exchange sandbox**: OKX в новых версиях CCXT принимает `set_sandbox_mode(True)`; если не сработает — `client.options['defaultType']` и `?demo=1`. Уточнить в коде после `pip show ccxt`.

### B.3 Движок: те же изменения
- [trade-engine-crypto/src/infrastructure/db_models.py](trade-engine-crypto/src/infrastructure/db_models.py): добавить `passphrase_enc` (зеркало).
- [trade-engine-crypto/src/infrastructure/db_repositories.py](trade-engine-crypto/src/infrastructure/db_repositories.py):
  - `DecryptedCredential`: `passphrase: str | None = None`.
  - `get_decrypted()`: расшифровка `passphrase_enc` Fernet'ом если есть.
- [trade-engine-crypto/src/infrastructure/ccxt_exchange_adapter.py](trade-engine-crypto/src/infrastructure/ccxt_exchange_adapter.py):
  - `SUPPORTED_EXCHANGES = frozenset({"binance", "bybit", "okx", "mexc"})`.
  - `__init__(..., passphrase: str | None = None)` → передавать в ccxt config.
- [trade-engine-crypto/src/engine_main.py:_exchange_factory](trade-engine-crypto/src/engine_main.py): пробросить `passphrase=cred.passphrase`.

### B.4 Symbols endpoint — `[BACKEND]`
Новый файл: `backend/src/api/routers/exchanges.py`.

```python
@router.get("/api/exchanges/{name}/symbols", response_model=list[str])
async def list_symbols(name: str, redis: RedisDep) -> list[str]:
    # 1) cache key f"exchanges:symbols:{name}", TTL 1 час
    cached = await redis.get(key)
    if cached: return json.loads(cached)
    # 2) ccxt.load_markets() (async), фильтр USDT-quoted, top по volume desc, limit 50
    # 3) сохранить в redis ex=3600
    # 4) вернуть
```

Использовать `ccxt.async_support.<name>().load_markets()`. Топ по `info.quoteVolume` или fallback `info.volume`. Не требует API-ключей (publicendpoints).

Также добавить:
- `GET /api/exchanges/supported` → `["binance", "bybit", "okx", "mexc"]` + per-exchange описание `{requires_passphrase: bool, supports_testnet: bool}`. Один источник правды для фронта.

### B.5 Frontend: Settings — выбор биржи + passphrase
Файл: [frontend/src/app/pages/Settings.tsx](frontend/src/app/pages/Settings.tsx).

```
[ Select биржи: Binance | Bybit | OKX | MEXC ]   ← Autocomplete
[ Label ]
[ API Key ]
[ Secret Key ]
[ Passphrase ]   ← показывается только если exchange.requires_passphrase
[ Сохранить ]
```

Перед сабмитом — `GET /api/exchanges/supported` (кэшируется в React state на mount). По `requires_passphrase` показывать поле.

### B.6 Frontend: CreateStrategy — symbols Autocomplete
Файл: [frontend/src/app/pages/CreateStrategy.tsx](frontend/src/app/pages/CreateStrategy.tsx).

- При выборе credential — извлечь `exchange` из credential.
- Дёрнуть `GET /api/exchanges/{exchange}/symbols` → топ-10 USDT-пар (BTC/USDT, ETH/USDT, SOL/USDT, XRP/USDT, TON/USDT, BNB/USDT, DOGE/USDT, ADA/USDT, AVAX/USDT, MATIC/USDT — в порядке отдачи от бэка по volume).
- MUI `<Autocomplete freeSolo>` — пользователь видит топ-10, может вписать любой (например `LINK/USDT`).

### B.7 TS types
Файл: [frontend/src/api/types.ts](frontend/src/api/types.ts):
```typescript
export interface CredentialIn {
  exchange: string;
  label: string;
  api_key: string;
  api_secret: string;
  passphrase?: string;
  testnet?: boolean;
}
export interface ExchangeMeta {
  name: string;
  display_name: string;
  requires_passphrase: boolean;
  supports_testnet: boolean;
}
```

### B.8 API клиенты — `[FRONTEND]`
Файл: `frontend/src/api/exchanges.ts` (новый):
```typescript
export const listSupportedExchanges = (): Promise<ExchangeMeta[]> => apiFetch("/api/exchanges/supported");
export const listExchangeSymbols = (name: string): Promise<string[]> => apiFetch(`/api/exchanges/${name}/symbols`);
```

---

## C) Cloudflare Turnstile вместо hCaptcha — `[BACKEND]` `[FRONTEND]`

### C.1 Бэк
Файл: [backend/src/infrastructure/captcha.py](backend/src/infrastructure/captcha.py).
- Заменить `HCAPTCHA_VERIFY_URL` на `https://challenges.cloudflare.com/turnstile/v0/siteverify`.
- Body тот же формат (`secret`, `response`, `remoteip`).
- Класс `CaptchaError`, функция `verify_turnstile()` (переименовать из `verify_hcaptcha`). Старое имя оставить алиасом на 1 коммит для backwards compat.

Файл: [backend/src/config.py](backend/src/config.py).
- Удалить `hcaptcha_secret`.
- Добавить `turnstile_secret: str = ""`.

Файл: [backend/src/services/email_auth_service.py](backend/src/services/email_auth_service.py):
- `verify_turnstile(secret=self._settings.turnstile_secret, ...)`.

### C.2 Фронт
- `pnpm remove @hcaptcha/react-hcaptcha`
- `pnpm add @marsidev/react-turnstile` (популярная обёртка Turnstile для React).
- Файл: [frontend/src/app/components/auth/EmailCodeForm.tsx](frontend/src/app/components/auth/EmailCodeForm.tsx) — заменить `<HCaptcha sitekey theme="dark">` на `<Turnstile siteKey theme="dark" onSuccess>`.
- ENV-переменная: `VITE_HCAPTCHA_SITEKEY` → `VITE_TURNSTILE_SITEKEY`.

### C.3 Deploy / secrets
- `.github/workflows/deploy.yml`: 
  - Build-arg для frontend: `VITE_TURNSTILE_SITEKEY` вместо `VITE_HCAPTCHA_SITEKEY`.
  - Env для backend: `TURNSTILE_SECRET` вместо `HCAPTCHA_SECRET`.
- `docker-compose.yml`: env-mapping переименован.
- `.env.example`: новые ключи.
- **GitHub Secrets:** добавить `CLOUDFLARE_TURNSTILE_SITE_KEY` и `CLOUDFLARE_TURNSTILE_SECRET` (значения уже даны). Старые `HCAPTCHA_*` после деплоя удалить вручную.

### C.4 Тесты
- [backend/tests/unit/test_captcha.py](backend/tests/unit/test_captcha.py) — заменить URL/respMock.

---

## D) Login в стиле grok.com — `[FRONTEND]`

### D.1 Theme overrides — глобально
Файл: [frontend/src/app/theme.ts](frontend/src/app/theme.ts):
- Palette:
  - `background.default`: `#0a0a0a` (почти чёрный — grok)
  - `background.paper`: `rgba(20, 20, 22, 0.6)` (полупрозрачная карточка для glass)
  - `primary.main`: `#ffffff` (белый акцент — как у grok)
  - `divider`: `rgba(255, 255, 255, 0.08)` (очень тонкий)
- Component overrides:
  - `MuiCard.styleOverrides.root.borderRadius`: `16` (было 12)
  - `MuiCard.styleOverrides.root.backdropFilter`: `"blur(20px)"`
  - `MuiCard.styleOverrides.root.border`: `"1px solid rgba(255,255,255,0.08)"`
  - `MuiButton.styleOverrides.root.borderRadius`: `12` (было 8), `fontWeight: 500`
  - `MuiOutlinedInput.styleOverrides.root.borderRadius`: `12` (было 8)
- Typography: добавить `letterSpacing: "-0.01em"` на `h1`-`h3`.

Файл: [frontend/src/styles/theme.css](frontend/src/styles/theme.css):
- В `.dark` и `:root` добавить:
  ```css
  --glass-bg: rgba(20, 20, 22, 0.6);
  --glass-border: rgba(255, 255, 255, 0.08);
  --glass-blur: 20px;
  --glow-primary: rgba(255, 255, 255, 0.12);
  ```

### D.2 Переписать Login.tsx
Файл: [frontend/src/app/pages/Login.tsx](frontend/src/app/pages/Login.tsx).

Структура (по референсу grok.com login):
```
Background: фиксированный с тонким radial gradient (тёмно-синий → чёрный)
↓
Card (max-width 400px, центрирована, glass-morphism, radius 16):
  ↓
  ─ Logo / название "Crypto Dashboard" — крупный, white, lh 1.1
  ─ Subtitle "Войдите чтобы начать торговать" — gray, sm
  ↓
  ─ 4 социальные кнопки в одну строку (44x44, ghost-style — bg=transparent, border 1px white/10):
    [G] [Я] [TG] [GH]    ← hover: bg=white/5, scale-105
  ↓
  ─ Divider: тонкая линия + текст "или email"
  ↓
  ─ TextField email — без label сверху, placeholder "you@example.com", radius 12,
    bg=white/3, border=white/8, focus: border=white/30
  ↓
  ─ Turnstile widget (theme="dark", compact)
  ↓
  ─ Button "Continue" — full-width, bg=white, color=black, radius 12, fw 500
    hover: bg=white/90
```

Анимации (только Login):
- Card: `transform: scale(0.96) → 1`, `opacity: 0 → 1`, 300ms ease-out при mount.
- Социальные кнопки: stagger fade-in 50ms.
- Через CSS keyframes в одном `<style>` блоке (без motion lib).

### D.3 Удалить unused deps
- `pnpm remove motion tw-animate-css` (по результатам разведки — нигде не используются, -30KB).

### D.4 SocialIcons — увеличить иконки до 24px (grok-style крупные)
Файл: [frontend/src/app/components/auth/SocialIcons.tsx](frontend/src/app/components/auth/SocialIcons.tsx).
- Все 4 SVG до `width=24 height=24` (сейчас 22-24, унифицировать).

### D.5 Что НЕ трогаем
- `/auth/callback`, `AuthCallback.tsx`.
- Layout, Header, Sidebar (подхватят MUI theme overrides автоматически — Drawer/AppBar получат blur).
- Dashboard/Strategies/Settings/CreateStrategy/Trades/Logs страницы — Card/Button перерисуются через overrides, ручная работа не нужна.

---

## Критичные файлы (быстрый чек-лист по PR'ам)

### A) Hotfix
- [backend/src/api/schemas/auth.py](backend/src/api/schemas/auth.py) — `email: str`
- [backend/src/services/identity_service.py](backend/src/services/identity_service.py) — synthetic email domain
- [backend/tests/unit/test_identity_service.py](backend/tests/unit/test_identity_service.py) — новый

### B) Multi-exchange
**Backend:**
- `backend/alembic/versions/0003_add_passphrase.py` (новый)
- [backend/src/models/exchange_credential.py](backend/src/models/exchange_credential.py)
- [backend/src/api/schemas/credential.py](backend/src/api/schemas/credential.py)
- [backend/src/infrastructure/exchange_validator.py](backend/src/infrastructure/exchange_validator.py)
- [backend/src/services/credential_service.py](backend/src/services/credential_service.py)
- [backend/src/repositories/credential_repo.py](backend/src/repositories/credential_repo.py)
- [backend/src/api/routers/credentials.py](backend/src/api/routers/credentials.py)
- `backend/src/api/routers/exchanges.py` (новый)
- [backend/src/main.py](backend/src/main.py) — `app.include_router(exchanges.router)`

**Engine:**
- [trade-engine-crypto/src/infrastructure/db_models.py](trade-engine-crypto/src/infrastructure/db_models.py)
- [trade-engine-crypto/src/infrastructure/db_repositories.py](trade-engine-crypto/src/infrastructure/db_repositories.py)
- [trade-engine-crypto/src/infrastructure/ccxt_exchange_adapter.py](trade-engine-crypto/src/infrastructure/ccxt_exchange_adapter.py)
- [trade-engine-crypto/src/engine_main.py](trade-engine-crypto/src/engine_main.py)

**Frontend:**
- [frontend/src/api/types.ts](frontend/src/api/types.ts)
- `frontend/src/api/exchanges.ts` (новый)
- [frontend/src/app/pages/Settings.tsx](frontend/src/app/pages/Settings.tsx)
- [frontend/src/app/pages/CreateStrategy.tsx](frontend/src/app/pages/CreateStrategy.tsx)

### C) Turnstile
- [backend/src/infrastructure/captcha.py](backend/src/infrastructure/captcha.py)
- [backend/src/config.py](backend/src/config.py)
- [backend/src/services/email_auth_service.py](backend/src/services/email_auth_service.py)
- [backend/tests/unit/test_captcha.py](backend/tests/unit/test_captcha.py) (новый)
- [frontend/package.json](frontend/package.json), [frontend/pnpm-lock.yaml](frontend/pnpm-lock.yaml)
- [frontend/src/app/components/auth/EmailCodeForm.tsx](frontend/src/app/components/auth/EmailCodeForm.tsx)
- [frontend/.env.example](frontend/.env.example), [frontend/Dockerfile](frontend/Dockerfile)
- [.github/workflows/deploy.yml](.github/workflows/deploy.yml), [docker-compose.yml](docker-compose.yml), [.env.example](.env.example)

### D) Grok Login
- [frontend/src/app/theme.ts](frontend/src/app/theme.ts)
- [frontend/src/styles/theme.css](frontend/src/styles/theme.css)
- [frontend/src/app/pages/Login.tsx](frontend/src/app/pages/Login.tsx)
- [frontend/src/app/components/auth/SocialIcons.tsx](frontend/src/app/components/auth/SocialIcons.tsx)
- [frontend/package.json](frontend/package.json) — `pnpm remove motion tw-animate-css`

---

## Секреты, которые нужно поменять в GitHub Secrets

**Добавить** (значения даны пользователем):
- `CLOUDFLARE_TURNSTILE_SITE_KEY=0x4AAAAAADRPdRR8t2m5Kd2h`
- `CLOUDFLARE_TURNSTILE_SECRET=0x4AAAAAADRPddcwDPWym9vlbRbIrskxVTI`

**Переименовать в deploy.yml** (значения те же):
- `HCAPTCHA_SECRET` → `TURNSTILE_SECRET` (после деплоя удалить старый)
- `HCAPTCHA_SITEKEY` → `TURNSTILE_SITEKEY` (либо `VITE_TURNSTILE_SITEKEY`)

**Можно удалить** (после успешного деплоя):
- `HCAPTCHA_SECRET`, `HCAPTCHA_SITEKEY`

---

## Verification (DoD)

### A) Telegram
- Открыть `/login`, нажать Telegram, в Telegram popup подтвердить → редирект на `/` без ошибки.
- В БД: `SELECT email FROM users WHERE email LIKE 'telegram-%' LIMIT 1;` — должен быть `telegram-<id>@noreply.invalid` (или новый домен).
- `pytest backend/tests/unit/test_identity_service.py` зелёный.

### B) Multi-exchange
- `curl https://crypto.shilkaphilosophy.ru/api/exchanges/supported` → 4 биржи.
- `curl https://crypto.shilkaphilosophy.ru/api/exchanges/binance/symbols` → массив строк `["BTC/USDT", "ETH/USDT", "SOL/USDT", ...]` минимум 10 элементов.
- В UI: Settings → выбрать OKX → появляется поле passphrase → ввести валидные testnet-ключи → сохраняется без ошибки → запись в БД с `passphrase_enc IS NOT NULL`.
- CreateStrategy → выбрать credential → видим Autocomplete с топ-10 пар.
- Запустить SmaCross на `ETH/USDT` через Binance Testnet credentials → стратегия стартует, движок принимает.

### C) Turnstile
- На `/login` виджет с надписью "Cloudflare Turnstile" появляется за <1 сек (вместо hCaptcha).
- Email-код проходит как раньше.
- `pytest backend/tests/unit/test_captcha.py` зелёный.

### D) Grok Login
- `/login` — тёмный градиент-фон, тонкая glass-карточка по центру, белая основная кнопка, иконки соц-сетей в одной строке без bg.
- В DevTools: `Card` имеет `backdrop-filter: blur(20px)`, `border-radius: 16px`.
- Bundle size после удаления `motion` и `tw-animate-css`: ~990 KB JS (было 1.02 MB).
- Pages Dashboard/Strategies/Settings — Card получили новые радиусы и тонкие borders, но layout не сломан.

---

## Финал — коммиты

4 коммита параллельно в submodules + 1 root-bump:

1. `backend`: `fix(auth): allow non-EmailStr in UserOut + multi-exchange (passphrase, symbols endpoint) + Turnstile`
2. `frontend`: `feat: multi-exchange Settings form + symbols autocomplete + Turnstile + Grok-style Login`
3. `trade-engine-crypto`: `feat(exchange): support Bybit/OKX/MEXC + passphrase in CCXTExchangeAdapter`
4. `crypto-dashboard` (root): `feat: bump submodules + Turnstile secrets in deploy + Grok theme tweaks landed`

Затем `.context/phase-2.5-3-4-implementation-report.md` — отчёт по образцу `.context/phase-2-auth-implementation-report.md`.

---

## Что НЕ делается в этой пачке

- Динамический список бирж не из whitelist (если CCXT поддерживает Bitget/HTX — пока не добавляем; легко расширить позже).
- Redesign других страниц (Dashboard виджеты, Strategies карточки — подхватят theme overrides, но не получат ручной grok-style).
- Удаление колонки `password_hash` из БД (она nullable, осталась с Phase 2 — почистим позже).
- 2FA (отдельно если решим).
