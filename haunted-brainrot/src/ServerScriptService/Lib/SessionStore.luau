--!strict
--[[
	SessionStore
	Session-locked player data on top of a DataStore (same idea as ProfileStore):

	* Load(key) takes a lock { jobId, time } inside UpdateAsync. If another live server holds the
	  lock (heartbeat younger than lockStaleSeconds) we wait and retry, so a player hopping servers
	  never has two servers writing their data at once. A dead server's stale lock is taken over.
	* Every Save() refreshes the lock (heartbeat). If we discover the lock now belongs to someone
	  else, we never overwrite their data: the session is marked lost and OnLost fires.
	* Release saves one last time and clears the lock.
	* All DataStore calls retry with exponential backoff.

	Dependencies are injected so this module is fully unit-testable.
]]

export type DataStoreLike = {
	UpdateAsync: (self: any, key: string, transform: (any, any) -> any) -> (any, any),
}

export type Options = {
	store: DataStoreLike,
	jobId: string,
	clock: () -> number, -- unix seconds (os.time)
	wait: (seconds: number) -> (),
	prepare: (raw: any, now: number) -> any, -- migrate/reconcile loaded data
	lockStaleSeconds: number,
	retries: number,
	retryBaseDelay: number,
	lockedRetryDelay: number,
	maxLockedAttempts: number,
	log: ((string) -> ())?,
}

export type Session = {
	Key: string,
	Data: any,
	Active: boolean,
	LastSaved: number,
	Save: (self: Session) -> boolean,
	Release: (self: Session) -> boolean,
	OnLost: ((reason: string) -> ())?,
}

local SessionStore = {}
SessionStore.__index = SessionStore

local SessionMeta = {}
SessionMeta.__index = SessionMeta

function SessionStore.new(opts: Options)
	local self = setmetatable({ _opts = opts, _sessions = {} :: { [string]: any } }, SessionStore)
	return self
end

function SessionStore:_log(msg: string)
	if self._opts.log then
		self._opts.log(msg)
	end
end

-- Runs UpdateAsync with retries. Returns ok, error.
function SessionStore:_update(key: string, transform: (any) -> any): (boolean, string?)
	local opts = self._opts
	local lastErr = "unknown"
	for attempt = 1, opts.retries do
		local ok, err = pcall(function()
			opts.store:UpdateAsync(key, function(old)
				return transform(old)
			end)
		end)
		if ok then
			return true
		end
		lastErr = tostring(err)
		self:_log(`UpdateAsync {key} failed (attempt {attempt}/{opts.retries}): {lastErr}`)
		if attempt < opts.retries then
			opts.wait(opts.retryBaseDelay * 2 ^ (attempt - 1))
		end
	end
	return false, lastErr
end

-- Loads and locks `key`. Returns the session, or nil + reason ("locked" | "unavailable").
function SessionStore:Load(key: string): (Session?, string?)
	local opts = self._opts
	assert(not self._sessions[key], `Session {key} already loaded on this server`)
	for attempt = 1, opts.maxLockedAttempts do
		local status = "pending"
		local loaded: any = nil
		local now = opts.clock()
		local ok, err = self:_update(key, function(old)
			local record = if type(old) == "table" then old else { meta = {} }
			record.meta = if type(record.meta) == "table" then record.meta else {}
			local lock = record.meta.lock
			if lock and lock.jobId ~= opts.jobId and now - (lock.time or 0) < opts.lockStaleSeconds then
				status = "locked"
				return nil -- cancel the write; someone else is actively using this data
			end
			if lock and lock.jobId ~= opts.jobId then
				record.meta.lastTakeover = now
			end
			record.meta.lock = { jobId = opts.jobId, time = now }
			record.meta.loads = (record.meta.loads or 0) + 1
			status = "ok"
			loaded = record
			return record
		end)
		if not ok then
			return nil, `unavailable: {err}`
		end
		if status == "ok" then
			local session = setmetatable({
				Key = key,
				Data = opts.prepare(loaded.data, now),
				Active = true,
				LastSaved = now,
				OnLost = nil,
				_store = self,
			}, SessionMeta)
			self._sessions[key] = session
			return (session :: any) :: Session, nil
		end
		self:_log(`{key} is locked by another server (attempt {attempt}/{opts.maxLockedAttempts})`)
		if attempt < opts.maxLockedAttempts then
			opts.wait(opts.lockedRetryDelay)
		end
	end
	return nil, "locked"
end

function SessionStore:_write(session: any, release: boolean): boolean
	if not session.Active then
		return false
	end
	local opts = self._opts
	local now = opts.clock()
	local lost = false
	local ok = self:_update(session.Key, function(old)
		local record = if type(old) == "table" then old else { meta = {} }
		record.meta = if type(record.meta) == "table" then record.meta else {}
		local lock = record.meta.lock
		if lock and lock.jobId ~= opts.jobId then
			lost = true
			return nil -- another server owns this data now; never overwrite it
		end
		record.data = session.Data
		record.meta.lock = if release then nil else { jobId = opts.jobId, time = now }
		record.meta.savedAt = now
		record.meta.saves = (record.meta.saves or 0) + 1
		return record
	end)
	if lost then
		session.Active = false
		self._sessions[session.Key] = nil
		self:_log(`{session.Key}: session lock lost to another server`)
		if session.OnLost then
			task.spawn(session.OnLost, "lock lost")
		end
		return false
	end
	if ok then
		session.LastSaved = now
	end
	if release then
		-- Even if the final save failed, stop using the session on this server.
		session.Active = false
		self._sessions[session.Key] = nil
	end
	return ok
end

function SessionMeta:Save(): boolean
	return self._store:_write(self, false)
end

function SessionMeta:Release(): boolean
	return self._store:_write(self, true)
end

function SessionStore:Get(key: string): Session?
	return self._sessions[key]
end

function SessionStore:Sessions(): { Session }
	local out = {}
	for _, s in self._sessions do
		table.insert(out, s)
	end
	return out
end

-- Saves (and optionally releases) every active session in parallel; waits up to `timeout` seconds.
function SessionStore:SaveAll(release: boolean, timeout: number): number
	local sessions = self:Sessions()
	local pending = #sessions
	local saved = 0
	for _, s in sessions do
		task.spawn(function()
			local ok = if release then s:Release() else s:Save()
			if ok then
				saved += 1
			end
			pending -= 1
		end)
	end
	local waited = 0
	while pending > 0 and waited < timeout do
		self._opts.wait(0.1)
		waited += 0.1
	end
	return saved
end

return SessionStore
