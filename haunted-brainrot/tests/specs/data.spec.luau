--!nocheck
local Context = require("../harness/Context")
local Mocks = require("../harness/Mocks")

return function(T)
	local describe, it, expect = T.describe, T.it, T.expect

	local ctx = Context.new()
	local DataTemplate = ctx.get("ServerScriptService/Lib/DataTemplate")
	local DataMigrations = ctx.get("ServerScriptService/Lib/DataMigrations")
	local SessionStore = ctx.get("ServerScriptService/Lib/SessionStore")

	-- A fake clock + wait so lock timing can be tested instantly.
	local function makeServer(cloud, jobId, clockRef)
		local service = Mocks.DataStoreService(cloud)
		local logs = {}
		return SessionStore.new({
			store = service:GetDataStore("PlayerData", "v1"),
			jobId = jobId,
			clock = function()
				return clockRef.now
			end,
			wait = function(s)
				clockRef.now += s
			end,
			prepare = DataMigrations.Prepare,
			lockStaleSeconds = 600,
			retries = 3,
			retryBaseDelay = 1,
			lockedRetryDelay = 4,
			maxLockedAttempts = 3,
			log = function(m)
				table.insert(logs, m)
			end,
		}),
			logs
	end

	describe("DataTemplate / DataMigrations", function()
		it("creates a fresh save with starting currency", function()
			local d = DataMigrations.Prepare(nil, 1000)
			expect(d.version).toBe(DataTemplate.VERSION)
			expect(d.currencies.Ectoplasm).toBe(100)
			expect(d.settings.peacefulBase).toBe(false)
			expect(d.upgrades.WalkSpeed).toBe(0)
			expect(d.firstJoin).toBe(1000)
		end)
		it("migrates a v0 save", function()
			local d = DataMigrations.Prepare({ Ectoplasm = 5000, Brainrots = { { id = "BooFfin" }, { id = "Batbrella", mutation = "Golden" } } }, 1)
			expect(d.version).toBe(1)
			expect(d.currencies.Ectoplasm).toBe(5000)
			expect(d.brainrots["1"].id).toBe("BooFfin")
			expect(d.brainrots["2"].mutation).toBe("Golden")
			expect(d.nextBrainrotUid).toBe(3)
		end)
		it("fills keys missing from an older v1 save without touching existing values", function()
			local partial = { version = 1, currencies = { Ectoplasm = 42 }, brainrots = { a = { id = "BooFfin", acquiredAt = 1 } } }
			local d = DataMigrations.Prepare(partial, 1)
			expect(d.currencies.Ectoplasm).toBe(42)
			expect(d.currencies.Candy).toBe(0)
			expect(d.settings.musicVolume).toBe(0.6)
			expect(d.brainrots.a.id).toBe("BooFfin")
		end)
		it("repairs wrong-typed values", function()
			local d = DataMigrations.Prepare({ version = 1, currencies = "corrupt", settings = { sfxVolume = "loud" } }, 1)
			expect(d.currencies.Ectoplasm).toBe(100)
			expect(d.settings.sfxVolume).toBe(0.8)
		end)
		it("leaves saves from a newer build untouched", function()
			local future = { version = 99, newThing = true }
			expect(DataMigrations.Prepare(future, 1)).toBe(future)
		end)
	end)

	describe("SessionStore", function()
		it("creates, saves and reloads data", function()
			local cloud = Mocks.DataStoreCloud()
			local clock = { now = 1000 }
			local server = makeServer(cloud, "A", clock)
			local s = server:Load("Player_1")
			expect(s ~= nil).toBe(true)
			s.Data.currencies.Ectoplasm = 777
			expect(s:Release()).toBe(true)
			local again = server:Load("Player_1")
			expect(again.Data.currencies.Ectoplasm).toBe(777)
			again:Release()
		end)

		it("blocks a second server while the lock is fresh, then lets it in after release", function()
			local cloud = Mocks.DataStoreCloud()
			local clock = { now = 1000 }
			local a = makeServer(cloud, "A", clock)
			local b = makeServer(cloud, "B", clock)
			local sa = a:Load("Player_2")
			sa.Data.currencies.Candy = 5
			local sb, reason = b:Load("Player_2")
			expect(sb).toBe(nil)
			expect(reason).toBe("locked")
			sa:Release()
			local sb2 = b:Load("Player_2")
			expect(sb2.Data.currencies.Candy).toBe(5)
		end)

		it("takes over a stale lock left by a crashed server", function()
			local cloud = Mocks.DataStoreCloud()
			local clock = { now = 1000 }
			local a = makeServer(cloud, "A", clock)
			local sa = a:Load("Player_3")
			sa.Data.currencies.Ectoplasm = 123
			sa:Save()
			-- Server A crashes (never releases). 11 minutes later server B loads.
			clock.now += 660
			local b = makeServer(cloud, "B", clock)
			local sb = b:Load("Player_3")
			expect(sb ~= nil).toBe(true)
			expect(sb.Data.currencies.Ectoplasm).toBe(123)
		end)

		it("never overwrites data after losing the lock, and reports it", function()
			local cloud = Mocks.DataStoreCloud()
			local clock = { now = 1000 }
			local a = makeServer(cloud, "A", clock)
			local sa = a:Load("Player_4")
			local lostReason
			sa.OnLost = function(r)
				lostReason = r
			end
			clock.now += 700
			local b = makeServer(cloud, "B", clock)
			local sb = b:Load("Player_4")
			sb.Data.currencies.Ectoplasm = 9999
			sb:Save()
			sa.Data.currencies.Ectoplasm = 1 -- stale server tries to write old data
			expect(sa:Save()).toBe(false)
			expect(sa.Active).toBe(false)
			local raw = cloud:Store("PlayerData", "v1")["Player_4"]
			expect(raw.data.currencies.Ectoplasm).toBe(9999)
			require("@lune/task").wait()
			expect(lostReason).toBe("lock lost")
		end)

		it("retries transient DataStore errors with backoff", function()
			local cloud = Mocks.DataStoreCloud()
			local clock = { now = 0 }
			local a, logs = makeServer(cloud, "A", clock)
			cloud.failNext = 2
			local s = a:Load("Player_5")
			expect(s ~= nil).toBe(true)
			expect(#logs).toBe(2)
			expect(clock.now).toBe(3) -- waited 1s + 2s
		end)

		it("gives up when the DataStore stays down", function()
			local cloud = Mocks.DataStoreCloud()
			local clock = { now = 0 }
			local a = makeServer(cloud, "A", clock)
			cloud.failNext = 10
			local s, reason = a:Load("Player_6")
			expect(s).toBe(nil)
			expect(reason).toContain("unavailable")
		end)

		it("heartbeats the lock on every save", function()
			local cloud = Mocks.DataStoreCloud()
			local clock = { now = 1000 }
			local a = makeServer(cloud, "A", clock)
			local s = a:Load("Player_7")
			clock.now = 1500
			s:Save()
			local raw = cloud:Store("PlayerData", "v1")["Player_7"]
			expect(raw.meta.lock.time).toBe(1500)
			expect(raw.meta.lock.jobId).toBe("A")
			-- 400s after the heartbeat the lock is still fresh for other servers.
			clock.now = 1900
			local b = makeServer(cloud, "B", clock)
			expect(b:Load("Player_7")).toBe(nil)
		end)

		it("saves and releases every session on shutdown", function()
			local cloud = Mocks.DataStoreCloud()
			local clock = { now = 1 }
			local a = makeServer(cloud, "A", clock)
			for i = 1, 4 do
				local s = a:Load(`P{i}`)
				s.Data.currencies.Candy = i
			end
			local saved = a:SaveAll(true, 5)
			expect(saved).toBe(4)
			expect(#a:Sessions()).toBe(0)
			local raw = cloud:Store("PlayerData", "v1")
			expect(raw.P3.data.currencies.Candy).toBe(3)
			expect(raw.P3.meta.lock).toBe(nil)
		end)
	end)
end
