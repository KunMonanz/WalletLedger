from django.core.cache import cache


def wallet_cache(wallet_id):
    return f"wallet:{wallet_id}"


def _ledger_version(wallet_id):
    key = f"wallet:{wallet_id}:ledger:version"
    version = cache.get(key)
    if version is None:
        cache.set(key, 1, timeout=None)
        return 1
    return version


def bump_ledger_version(wallet_id):
    key = f"wallet:{wallet_id}:ledger:version"
    try:
        cache.incr(key)
    except ValueError:
        cache.set(key, 1, timeout=None)


def ledgers_cache_key(wallet_id, query_string=""):
    version = _ledger_version(wallet_id)
    return f"wallet:{wallet_id}:ledger:v{version}:{query_string}"
