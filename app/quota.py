"""Request quotas of the API keys.

Two interchangeable stores:

  DatabaseQuota   counts the rows of `api_usage` (default; fine for one server, nothing else to install).
  RedisQuota      counts in Redis (used when REDIS_URL is set): atomic, shared by every worker and server,
                  and it does not run a COUNT query on a growing table for each request.

`reserve()` checks AND counts in one step, so that two workers cannot both take the last request of a quota.
When the request is then refused for another reason (invalid file), `release()` gives the request back.
The `api_usage` table is still written for every accepted request: it is the audit log, and it re-seeds the
monthly counter if Redis loses its data.
"""
import logging
import uuid
from datetime import timedelta, timezone

from .models.api_token import ApiUsage

logger = logging.getLogger(__name__)

HOUR = 3600
MONTH_KEY_TTL = 35 * 24 * HOUR      # a monthly counter is useless once the month is over


def _hourly_message(token):
    return f'Quota horaire dépassé ({token.quota_hourly} requêtes par heure)'


def _monthly_message(token):
    return f'Quota mensuel dépassé ({token.quota_monthly} requêtes par mois)'


def _month_start(now):
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _db_count(token, since):
    return ApiUsage.query.filter(ApiUsage.token_id == token.id, ApiUsage.created_at >= since).count()


class DatabaseQuota:
    """Counts the request log. Nothing is reserved: the caller writes the log row once the request is accepted."""

    def reserve(self, token, now):
        """Returns (error message or None, reservation to pass to release())."""
        if token.quota_hourly is not None and _db_count(token, now - timedelta(hours=1)) >= token.quota_hourly:
            return _hourly_message(token), None
        if token.quota_monthly is not None and _db_count(token, _month_start(now)) >= token.quota_monthly:
            return _monthly_message(token), None
        return None, None

    def release(self, reservation):
        pass


class RedisQuota:
    """Quota counters in Redis.

    hourly   sorted set `ecode:quota:h:<token id>`: one member per request, scored with its time.
             Members older than one hour are removed, the cardinality is the count: an exact rolling window.
    monthly  counter `ecode:quota:m:<token id>:<YYYYMM>`; created from the request log when missing.

    Each step is "count me first, then check": a request over the quota removes itself again. Two workers
    can therefore never both be admitted on the last slot (at worst both are refused for a moment).
    If Redis is unreachable the database counters take over, so the service stays available.
    """

    def __init__(self, client, fallback=None):
        self.redis = client
        self.fallback = fallback or DatabaseQuota()

    def reserve(self, token, now):
        if token.quota_hourly is None and token.quota_monthly is None:
            return None, None                                  # unlimited: no round trip at all
        if token.quota_hourly == 0:
            return _hourly_message(token), None                # 0 = nothing allowed
        if token.quota_monthly == 0:
            return _monthly_message(token), None
        try:
            return self._reserve(token, now)
        except Exception as exc:                               # redis.RedisError, timeouts, ...
            logger.warning('Redis quota store unavailable (%s): using the database counters', exc)
            return self.fallback.reserve(token, now)

    def release(self, reservation):
        if not reservation:
            return
        try:
            self._undo(reservation)
        except Exception as exc:
            logger.warning('Could not give a quota slot back to Redis: %s', exc)

    # -- internals -------------------------------------------------------------------------------------------

    def _reserve(self, token, now):
        reservation = {}
        at = now.replace(tzinfo=timezone.utc).timestamp()

        if token.quota_hourly is not None:
            key = f'ecode:quota:h:{token.id}'
            member = f'{at:.6f}:{uuid.uuid4().hex[:8]}'
            pipe = self.redis.pipeline(transaction=True)       # MULTI/EXEC: one atomic round trip
            pipe.zremrangebyscore(key, 0, at - HOUR)
            pipe.zadd(key, {member: at})
            pipe.zcard(key)
            pipe.expire(key, HOUR + 60)
            count = pipe.execute()[2]
            reservation['hourly'] = (key, member)
            if count > token.quota_hourly:
                self._undo(reservation)
                return _hourly_message(token), None

        if token.quota_monthly is not None:
            key = f'ecode:quota:m:{token.id}:{now:%Y%m}'
            pipe = self.redis.pipeline(transaction=True)
            pipe.incr(key)
            pipe.expire(key, MONTH_KEY_TTL)
            count = pipe.execute()[0]
            if count == 1:
                # First request of the month on this Redis (or Redis lost its data): start from the request log
                already = _db_count(token, _month_start(now))
                if already:
                    count = self.redis.incrby(key, already)
            reservation['monthly'] = key
            if count > token.quota_monthly:
                self._undo(reservation)
                return _monthly_message(token), None

        return None, reservation

    def _undo(self, reservation):
        pipe = self.redis.pipeline(transaction=True)
        if 'hourly' in reservation:
            key, member = reservation['hourly']
            pipe.zrem(key, member)
        if 'monthly' in reservation:
            pipe.decr(reservation['monthly'])
        pipe.execute()


def make_quota(config):
    """Redis counters when REDIS_URL is set, the database otherwise."""
    url = config.get('REDIS_URL')
    if not url:
        return DatabaseQuota()
    import redis
    client = redis.Redis.from_url(url, socket_timeout=0.25, socket_connect_timeout=0.25)
    logger.info('API quotas are counted in Redis')
    return RedisQuota(client)
