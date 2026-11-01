# Phase 0 — Identity decoupling

**Status:** 📋 planned
**Estimate:** 3-5 days
**Depends on:** nothing
**Blocks:** everything else in the epic

---

## Goal

A person can create a PaceMind account and stay logged in **without a Strava
account**. Strava becomes one revocable *connection*, not the identity itself.

## Current state

- `backend/models/user.py:42` — `strava_user_id = db.Column(db.Integer, unique=True, nullable=False)`
- `backend/api/auth.py:54,61,150` — the only auth flow is Strava OAuth
- `backend/repositories/user_repository.py:14` — `find_or_create_from_strava(athlete)`
- Tokens live directly on `User` (`_access_token`, `_refresh_token`,
  `expires_at`), encrypted with Fernet (`backend/models/user.py:34`)

## Design

### 1. `user_connections` table (new)

One row per (user, provider). This is what makes phase 3 cheap: adding Garmin
means inserting a row, not adding columns to `users`.

```python
class UserConnection(db.Model):
    __tablename__ = 'user_connections'
    __table_args__ = (
        db.UniqueConstraint('provider', 'external_user_id',
                            name='uq_connection_provider_external'),
        db.UniqueConstraint('user_id', 'provider',
                            name='uq_connection_user_provider'),
    )

    id               = db.Column(db.Integer, primary_key=True)
    user_id          = db.Column(db.Integer, db.ForeignKey('users.id'),
                                 nullable=False)
    provider         = db.Column(db.String(32), nullable=False)   # strava|garmin|polar|coros|suunto
    external_user_id = db.Column(db.String(128), nullable=False)
    _access_token    = db.Column('access_token', db.LargeBinary, nullable=True)
    _refresh_token   = db.Column('refresh_token', db.LargeBinary, nullable=True)
    expires_at       = db.Column(db.Integer, nullable=True)
    scopes           = db.Column(db.String(512), nullable=True)
    connected_at     = db.Column(db.DateTime, default=utcnow)
    last_sync_at     = db.Column(db.DateTime, nullable=True)
    status           = db.Column(db.String(32), default='active')  # active|revoked|error
```

Reuse the existing Fernet cipher pattern from `backend/models/user.py:34` —
extract it into `backend/models/_crypto.py` so both models share one key
lifecycle rather than duplicating the dev-key-on-disk fallback.

Register in `backend/models/__init__.py` (per `database.py:init_db()` this is
enough for auto-registration) and add `UserConnectionRepository` to
`backend/repositories/__init__.py`.

### 2. `users` changes

```
strava_user_id   -> nullable=True   (keep the column and its unique index for
                                     now; it is read in ~9 places and dropping
                                     it is a separate, later cleanup)
email            -> keep nullable=True for now, becomes the login key
password_hash    -> NEW, nullable (null for OAuth-only accounts)
auth_provider    -> NEW, String(32), default 'strava'
email_verified_at-> NEW, DateTime nullable
```

Do **not** drop `strava_user_id` in this phase. Making it nullable is enough to
unblock signup; removing it is mechanical cleanup once phase 1 lands.

### 3. Second login path — magic link

Recommended over password or Google:

- We already have JWT issuance/verification (`backend/api/auth.py:23,31`) and
  httpOnly cookie handling (`:42`). A magic link reuses all of it.
- No password reset flow, no credential storage, no OAuth client registration.
- Cost: one transactional mailer (Resend / Postmark / SES) — a few lines.

Flow:

```
POST /api/auth/magic-link  {email}     -> 202, always (no account enumeration)
GET  /api/auth/magic-link/verify?token -> sets jwt_token cookie, redirects
```

The token is a short-lived (15 min) single-use signed JWT with a dedicated
`purpose: 'magic_link'` claim, stored-hash or `jti`-blacklisted so it cannot be
replayed. Rate-limit both endpoints via the existing Flask-Limiter setup.

Google OAuth can be added later as a third `auth_provider` without schema
changes.

### 4. Strava callback becomes account-linking

`backend/api/auth.py:61` splits into two behaviours:

| Caller state | Behaviour |
|---|---|
| Not logged in | Find `UserConnection(strava, athlete.id)` → log that user in. If none, create a `User` **and** the connection (preserves today's UX exactly). |
| Already logged in | Attach the connection to `current_user`. Reject with a clear error if that Strava athlete is already linked to a different account. |

`find_or_create_from_strava` moves to a `ConnectionService.link(user, provider, payload)`
and keeps a thin backwards-compatible wrapper until callers are migrated.

### 5. Migration

New Alembic revision after `m1a2b3c4d5f2_add_ftp_pref`. Per
`backend/MIGRATIONS.md`, guard everything:

1. `create_table('user_connections')` if not exists.
2. **Backfill**: for every `users` row with a non-null `strava_user_id`, insert
   a `user_connections` row copying `access_token`, `refresh_token`,
   `expires_at` verbatim (they are already-encrypted `LargeBinary` — copy the
   bytes, do not decrypt/re-encrypt).
3. `alter_column('users','strava_user_id', nullable=True)`.
4. Add the three new `users` columns.

Downgrade must be written and must not drop `users` columns that hold data.
Run `./scripts/lint_migration.sh` before committing.

### 6. Frontend

- `AuthGate.vue` — "Sign in" (email) as the primary action; "Continue with
  Strava" as a secondary one.
- New `ConnectionsPanel` in settings: list providers, connect/disconnect state.
- `stores/auth.js` — user object no longer guarantees `strava_username`; every
  read of it needs a fallback. Grep: `frontend/src/` has ~23 files referencing
  Strava, most are display strings.
- Empty states everywhere that assumes activities exist: `Predict.vue`,
  `Training.vue`, `ActivitySelector.vue` must degrade to "no data yet — import
  your history" rather than "connect Strava".
- Respect the existing rule from project memory: views must await
  `ensureAuthReady()`; a 401 must never redirect.

## Risks

| Risk | Mitigation |
|---|---|
| Backfill mis-copies encrypted tokens → every user logged out of Strava | Copy raw `LargeBinary`; add a migration test that round-trips one decrypt on a fixture DB before/after |
| Account takeover via magic link to an unverified email that matches an existing Strava-created account | Strava-created accounts start with `email_verified_at = NULL`; a magic link to an unverified email creates a *new* account rather than adopting the old one, and linking is done explicitly by a logged-in user |
| Two accounts for the same human (one Strava, one email) | Ship an explicit "link Strava to this account" flow in the same release; consider a later merge tool |

## Acceptance criteria

- [ ] Sign up by email, log out, log back in — no Strava involved.
- [ ] Existing Strava users log in exactly as before, with no re-authorization.
- [ ] A logged-in email user can attach Strava and see their activities.
- [ ] Disconnecting Strava keeps the account and all imported activities.
- [ ] `pytest` green; new tests cover the backfill and the link/collision cases.
