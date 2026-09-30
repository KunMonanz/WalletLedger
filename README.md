# WalletLedger

A backend wallet and payments system built around a **double-entry ledger**, with Paystack integration, idempotent transfers, and concurrency-safe balance updates.

Built as a portfolio project to demonstrate production-grade patterns for handling money: correctness under concurrent load, safe retries, and auditability.

## Why a ledger, not a balance column

A wallet's balance is never written directly. It is derived from a log of immutable entries. Every movement of money is a **transaction** made of two or more **ledger entries** that sum to zero: one account is debited, another is credited. Nothing is ever updated or deleted — a mistake is corrected with a reversing transaction, not an edit.

This means:

- The system can always answer "why is this balance what it is?"
- The books can be mechanically verified: the sum of all entries is always zero.
- A cached `balance` field exists on `Wallet` purely for fast reads. The ledger is the source of truth; the cache is a performance shortcut that is always derivable from it.

Amounts are stored as **integers in kobo**, never floats or naira, since floating-point arithmetic is not exact (`0.1 + 0.2 != 0.3`) and Paystack's API itself speaks in kobo.

## Architecture

```
Client
  │
  ├─ POST /api/wallets/transfer/                (user-to-user transfer)
  ├─ POST /api/wallets/fund/                    (initiate Paystack funding)
  ├─ GET  /api/wallets/fund/<reference>/verify/ (on-demand funding status check)
  ├─ POST /api/wallets/paystack/webhook/        (Paystack → server, signed)
  ├─ GET  /api/wallets/me/                      (wallet balance)
  └─ GET  /api/wallets/ledgers/                 (transaction history, filtered + paginated)

Celery Beat (every 5 min)
  └─ reconcile_pending_fundings                (verifies stuck intents against Paystack directly)
```

**Models**

- `Wallet` — one per user (plus system wallets, e.g. `paystack_clearing`), holds the cached `balance`
- `Transaction` — one row per money-moving event (funding, transfer), carries `idempotency_key` and `request_fingerprint`
- `LedgerEntry` — one row per side of a transaction (`debit` / `credit`), always created in pairs
- `FundingIntent` — created before a Paystack payment starts; links a `reference` to a wallet and expected amount, tracks `pending` / `successful` / `failed`

**Service layer** (`ledger/services.py`)
All balance-affecting logic lives here, never in views or serializers:

- `TransactionCommandService.transfer()` — wallet-to-wallet transfer
- `FundingService.initiate_funding()` / `.complete_funding()` / `.fail_funding()` — Paystack funding lifecycle
- `LedgerQueryService`, `WalletQueryService` — read paths

**Background jobs** (`ledger/tasks.py`, Celery)

- `reconcile_pending_fundings` — periodic sweep of stuck `FundingIntent`s, verified directly against Paystack

## Concurrency and correctness

Every money-moving operation follows the same shape, inside a single `transaction.atomic()` block:

1. **Validate input** (amount > 0, sender ≠ recipient) before touching the database.
2. **Lock both accounts** with `select_for_update()`, fetched in one query and **ordered by id**. Consistent lock ordering prevents two opposite operations (A→B and B→A) from deadlocking each other.
3. **Check funds on the locked row**, after the lock is held — checking before locking is the classic TOCTOU race that lets concurrent requests overspend.
4. **Write the transaction and both ledger entries** as one `bulk_create`.
5. **Update both cached balances** and save.
6. **Mark the transaction successful last.** If any prior step raises, the whole block rolls back — there is never a half-posted transfer.

Cache invalidation for affected wallets is deferred with `transaction.on_commit()`, so a reader can never observe a cache miss that falls through to a not-yet-committed (i.e. stale) balance.

## Caching

Wallet balances and ledger history are cached in Redis, invalidated on every write rather than left to expire on TTL alone.

- **Wallet balance** — a single cache entry per wallet, deleted directly (`cache.delete`) whenever a transfer or funding event touches that wallet.
- **Ledger history** — filtering and cursor pagination mean a single wallet can have unboundedly many distinct cached responses (`?direction=debit`, `?direction=credit&cursor=abc`, and so on). Tracking and deleting every combination individually doesn't scale, so the ledger cache is **version-stamped** instead: each cache key embeds a per-wallet version number (`wallet:{id}:ledger:v{n}:{query_string}`). A write doesn't delete anything — it increments the version. Every previously cached response for that wallet, across every filter and page, is instantly unreachable under the new version number and simply expires off its own TTL rather than needing to be found and deleted. One counter increment invalidates an arbitrary number of cached variants.

## Idempotency

Clients supply an `Idempotency-Key` header on transfer requests. On the server:

- A repeated key with the **same** parameters returns the original transaction unchanged — safe for network retries.
- A repeated key with **different** parameters (different amount or recipient) is rejected, via a `request_fingerprint` (SHA-256 of sender, recipient, amount) stored against the original transaction.
- `idempotency_key` has a database-level unique constraint as the real guarantee; an in-code lookup is only a fast path to avoid hitting that constraint under normal retries. The rare race where two identical requests pass the lookup simultaneously is caught as an `IntegrityError` outside the atomic block and resolved by re-reading the now-existing row.

Paystack webhooks reuse this mechanism: the `reference` on each `charge.success` event becomes the idempotency key, so a webhook delivered twice (which Paystack does by design) credits the wallet exactly once. The `FundingIntent` row is additionally locked during webhook processing, so two simultaneous deliveries of the same event serialize instead of racing.

## Paystack integration

- **Funding a wallet** creates a `FundingIntent` (pending) and calls Paystack's `/transaction/initialize`, returning a hosted checkout URL. No card data ever touches this server.
- **Webhooks** (`POST /api/wallets/paystack/webhook/`) are the primary trusted signal that a payment succeeded — a client-side redirect is never treated as proof of payment.
- Every webhook's signature is verified against the raw request body using HMAC-SHA512 and the Paystack secret key, compared with `hmac.compare_digest` to avoid timing attacks. Malformed JSON and unrecognized event types are handled without raising, always returning `200` so Paystack doesn't retry indefinitely against something that will never resolve.
- `charge.success` and `charge.failed` are handled explicitly; every other event type is logged and ignored.

**Three independent layers all converge on the same `complete_funding()` / `fail_funding()` calls, so there is exactly one code path that ever credits a wallet from Paystack:**

1. **Webhook** — the fast path, event-driven, usually resolves a funding intent within seconds.
2. **On-demand verify** (`GET /api/wallets/fund/<reference>/verify/`) — lets a client ask "did my payment go through?" immediately after returning from checkout, without waiting on the webhook. Calls Paystack's verify endpoint live if the intent is still `pending`.
3. **Reconciliation** (`reconcile_pending_fundings`, Celery Beat, every 5 minutes) — a safety net for intents still `pending` after 10 minutes, the case where a webhook was lost entirely (server downtime, delivery failure). Verifies each against Paystack directly and resolves it the same way.

Because all three call the identical service functions, there's no second "credit the wallet" implementation to drift out of sync or carry a different bug.

## Tech stack

- Django + Django REST Framework
- PostgreSQL
- Redis (caching, via `django-redis`) + Celery + Celery Beat (scheduled reconciliation, background work)
- `djangorestframework-simplejwt` for auth, with refresh-token rotation and blacklisting
- `django-filter` for ledger filtering (direction, type, date range, amount range), cursor pagination for ledger history (stable under concurrent inserts, unlike offset-based paging)
- Docker Compose for local orchestration (Postgres, Redis, web, Celery worker)
- Ruff for linting/formatting

## Running locally

```bash
python -m venv venv
venv\Scripts\activate          # Windows
pip install -r requirements.txt

# .env — see .env.example
cp .env.example .env

python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Create the system clearing wallet once:

```python
from ledger.models import Wallet
Wallet.objects.get_or_create(name="paystack_clearing", defaults={"type": Wallet.WalletType.SYSTEM})
```

### Testing webhooks locally

`scripts/fake_webhook.py` signs and sends a fake `charge.success` event to your local server, so Paystack's dashboard and a public URL are not required for development:

```bash
python scripts/fake_webhook.py <reference> <amount_in_kobo>
```

Run it twice against the same reference to confirm duplicate delivery doesn't double-credit the wallet.

### Running background jobs

Celery Beat doesn't support the combined `worker --beat` mode on Windows, so the worker and scheduler run as two separate processes locally:

```bash
# terminal 1 — executes tasks
celery -A config worker --loglevel=info -P solo

# terminal 2 — schedules them (drop -P solo, not needed here)
celery -A config beat --loglevel=info
```

`reconcile_pending_fundings` is scheduled via `CELERY_BEAT_SCHEDULE` in `settings.py`, running every 5 minutes. Restart the beat process after changing the schedule, since it's only read at startup.

## Failure modes handled

| Failure                                             | Handling                                                                                                                                                  |
| --------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Retried transfer request (network drop)             | Idempotency key returns the original result                                                                                                               |
| Idempotency key reused with different parameters    | Rejected via request fingerprint mismatch                                                                                                                 |
| Duplicate Paystack webhook delivery                 | `FundingIntent` status check under row lock; second delivery is a no-op                                                                                   |
| Forged webhook request                              | HMAC-SHA512 signature verification against the raw body                                                                                                   |
| Concurrent transfers from the same wallet           | Row-level locking (`select_for_update`, consistent id ordering) prevents overspend                                                                        |
| Two opposite transfers (A→B and B→A) simultaneously | Consistent lock ordering prevents deadlock                                                                                                                |
| Webhook amount doesn't match the funding intent     | Logged and left uncredited for manual review, never silently accepted                                                                                     |
| Cache read during an uncommitted transaction        | Invalidation deferred to `transaction.on_commit()`                                                                                                        |
| Lost webhook (server downtime, delivery failure)    | Periodic reconciliation task (Celery Beat, every 5 min) verifies stuck intents against Paystack directly                                                  |
| User wants payment status before webhook arrives    | On-demand verify endpoint checks Paystack live and resolves the intent immediately                                                                        |
| A failed payment attempt left `pending` forever     | `charge.failed` webhook (and reconciliation) explicitly marks the `FundingIntent` failed — never conflated with a `Transaction` row, since no money moved |
| Float rounding errors                               | All monetary values stored as integer kobo                                                                                                                |
| Unbounded ledger cache variants (filters × pages)   | Version-stamped cache keys; a write bumps the version, invalidating every variant at once                                                                 |

## Possible extensions

- Withdrawal flow (wallet → Paystack transfer recipient), reusing the same webhook/verify/reconcile pattern for `transfer.success` / `transfer.failed`
- Per-transaction fee handling with an explicit rounding rule
- Admin-facing dispute/reversal flow (posts a reversing transaction rather than mutating history)
- Database-backed Beat schedule (`django_celery_beat`) so intervals are adjustable from the admin without a redeploy
