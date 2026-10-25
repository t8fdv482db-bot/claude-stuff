--!strict
-- Token-bucket rate limiter keyed by any value (usually a Player).
-- Each key may make `perSecond` calls per second with a burst of `burst`.

export type RateLimiter = {
	Allow: (self: RateLimiter, key: any, now: number?) -> boolean,
	Forget: (self: RateLimiter, key: any) -> (),
}

local RateLimiter = {}
RateLimiter.__index = RateLimiter

function RateLimiter.new(perSecond: number, burst: number?, clock: (() -> number)?): RateLimiter
	local self = setmetatable({
		_rate = perSecond,
		_burst = burst or perSecond,
		_clock = clock or os.clock,
		_buckets = {} :: { [any]: { tokens: number, last: number } },
	}, RateLimiter)
	return (self :: any) :: RateLimiter
end

function RateLimiter:Allow(key: any, now: number?): boolean
	local t = now or self._clock()
	local bucket = self._buckets[key]
	if not bucket then
		bucket = { tokens = self._burst, last = t }
		self._buckets[key] = bucket
	end
	bucket.tokens = math.min(self._burst, bucket.tokens + (t - bucket.last) * self._rate)
	bucket.last = t
	if bucket.tokens >= 1 then
		bucket.tokens -= 1
		return true
	end
	return false
end

function RateLimiter:Forget(key: any)
	self._buckets[key] = nil
end

return RateLimiter
