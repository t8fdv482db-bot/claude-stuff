--!nocheck
local Context = require("../harness/Context")
local Mocks = require("../harness/Mocks")
local Shim = require("../harness/Shim")
local task = require("@lune/task")

-- Boots the server services the same way Main.server.luau does.
local function boot(opts)
	local ctx = Context.new(opts)
	local Net = ctx.get("ReplicatedStorage/Shared/Net")
	Net.Server.Init()
	local services = {}
	for _, name in opts and opts.services or { "DataService", "EconomyService" } do
		local s = ctx.get(`ServerScriptService/Services/{name}`)
		s.Init()
		services[name] = s
	end
	for _, s in services do
		s.Start()
	end
	ctx.services = services
	ctx.Net = Net
	ctx.remotes = ctx.game:GetService("ReplicatedStorage"):FindFirstChild("Remotes")
	return ctx
end

local function settle()
	for _ = 1, 5 do
		task.wait()
	end
end

return function(T)
	local describe, it, expect = T.describe, T.it, T.expect

	describe("DataService", function()
		it("loads data on join and exposes it via attributes + leaderstats", function()
			local ctx = boot()
			local p = ctx.players:Join(1, "Casper")
			settle()
			local DataService = ctx.services.DataService
			local data = DataService.Get(p)
			expect(data ~= nil).toBe(true)
			expect(p:GetAttribute("DataLoaded")).toBe(true)
			expect(p:GetAttribute("Ectoplasm")).toBe(100)
			expect(p.leaderstats.Ectoplasm.Value).toBe("100")
			expect(p.leaderstats.Rebirths.Value).toBe(0)
		end)

		it("saves and releases on leave so the next server can load it", function()
			local cloud = Mocks.DataStoreCloud()
			local ctx = boot({ cloud = cloud, jobId = "server-A" })
			local p = ctx.players:Join(2, "Boo")
			settle()
			ctx.services.EconomyService.Add(p, "Candy", 30, "test")
			ctx.players:Leave(p)
			settle()
			local raw = cloud:Store("HauntedBrainrot_PlayerData", "v1")["Player_2"]
			expect(raw.data.currencies.Candy).toBe(30)
			expect(raw.meta.lock).toBe(nil)

			local ctx2 = boot({ cloud = cloud, jobId = "server-B" })
			local p2 = ctx2.players:Join(2, "Boo")
			settle()
			expect(ctx2.services.DataService.Get(p2).currencies.Candy).toBe(30)
		end)

		it("kicks with a friendly message when another server holds the save", function()
			local cloud = Mocks.DataStoreCloud()
			local a = boot({ cloud = cloud, jobId = "server-A" })
			a.players:Join(3, "Wisp")
			settle()
			-- Shrink lock retries so the test doesn't wait for real seconds.
			local b = Context.new({ cloud = cloud, jobId = "server-B" })
			local GameConfig = b.get("ReplicatedStorage/Shared/Config/GameConfig")
			GameConfig.Data.maxLockedAttempts = 1
			b.get("ReplicatedStorage/Shared/Net").Server.Init()
			local DS = b.get("ServerScriptService/Services/DataService")
			DS.Init()
			DS.Start()
			local p = b.players:Join(3, "Wisp")
			settle()
			expect(DS.Get(p)).toBe(nil)
			expect(Shim.kicked(p)).toContain("another server")
		end)

		it("kicks instead of playing on a blank save when DataStores are down", function()
			local cloud = Mocks.DataStoreCloud()
			local ctx = Context.new({ cloud = cloud })
			local GameConfig = ctx.get("ReplicatedStorage/Shared/Config/GameConfig")
			GameConfig.Data.loadRetries = 1
			ctx.get("ReplicatedStorage/Shared/Net").Server.Init()
			local DS = ctx.get("ServerScriptService/Services/DataService")
			DS.Init()
			DS.Start()
			cloud.failNext = 5
			local p = ctx.players:Join(4, "Glitch")
			settle()
			expect(DS.Get(p)).toBe(nil)
			expect(Shim.kicked(p)).toContain("couldn't load")
		end)

		it("falls back to an in-memory store in Studio without API access", function()
			local ctx = Context.new({
				studio = true,
				mocks = {
					DataStoreService = {
						GetDataStore = function()
							return {
								UpdateAsync = function()
									error("Studio access to API services is not enabled")
								end,
							}
						end,
					},
				},
			})
			ctx.get("ReplicatedStorage/Shared/Net").Server.Init()
			local DS = ctx.get("ServerScriptService/Services/DataService")
			DS.Init()
			DS.Start()
			local p = ctx.players:Join(5, "Studio")
			settle()
			expect(DS.UsingMemoryStore).toBe(true)
			expect(DS.Get(p) ~= nil).toBe(true)
		end)

		it("saves and releases everyone on shutdown (BindToClose)", function()
			local cloud = Mocks.DataStoreCloud()
			local ctx = boot({ cloud = cloud })
			local a = ctx.players:Join(6, "A")
			local b = ctx.players:Join(7, "B")
			settle()
			ctx.services.EconomyService.Add(a, "Ectoplasm", 50)
			ctx.services.EconomyService.Add(b, "SoulGems", 2)
			expect(#ctx.closeCallbacks).toBe(1)
			ctx.closeCallbacks[1]()
			local store = cloud:Store("HauntedBrainrot_PlayerData", "v1")
			expect(store.Player_6.data.currencies.Ectoplasm).toBe(150)
			expect(store.Player_7.data.currencies.SoulGems).toBe(2)
			expect(store.Player_6.meta.lock).toBe(nil)
		end)

		it("validates settings sent from the client", function()
			local ctx = boot()
			local p = ctx.players:Join(8, "Settings")
			settle()
			local remote = ctx.remotes:FindFirstChild("UpdateSetting")
			Shim.clientFire(remote, p, "musicVolume", 0.25)
			Shim.clientFire(remote, p, "reducedMotion", true)
			Shim.clientFire(remote, p, "musicVolume", 5) -- out of range
			Shim.clientFire(remote, p, "sfxVolume", "loud") -- wrong type
			Shim.clientFire(remote, p, "Ectoplasm", 1e9) -- not a setting
			settle()
			local s = ctx.services.DataService.Get(p).settings
			expect(s.musicVolume).toBe(0.25)
			expect(s.reducedMotion).toBe(true)
			expect(s.sfxVolume).toBe(0.8)
			expect(ctx.services.DataService.Get(p).currencies.Ectoplasm).toBe(100)
			expect(p:GetAttribute("Setting_musicVolume")).toBe(0.25)
		end)

		it("rate-limits spammy remotes", function()
			local ctx = boot()
			local p = ctx.players:Join(9, "Spammer")
			settle()
			local remote = ctx.remotes:FindFirstChild("UpdateSetting")
			for i = 1, 20 do
				Shim.clientFire(remote, p, "musicVolume", i / 100)
			end
			settle()
			-- burst of 4 allowed, the rest dropped
			expect(ctx.services.DataService.Get(p).settings.musicVolume).toBe(0.04)
		end)

		it("returns a client snapshot without private fields", function()
			local ctx = boot()
			local p = ctx.players:Join(10, "Snap")
			settle()
			local snap = Shim.clientInvoke(ctx.remotes:FindFirstChild("GetPlayerData"), p)
			expect(snap.settings.musicVolume).toBe(0.6)
			expect(snap.receipts).toBe(nil)
			expect(snap.currencies).toBe(nil)
		end)
	end)

	describe("EconomyService", function()
		it("adds and spends currency, tracking lifetime Ectoplasm", function()
			local ctx = boot()
			local E = ctx.services.EconomyService
			local p = ctx.players:Join(20, "Rich")
			settle()
			expect(E.Add(p, "Ectoplasm", 1500, "test")).toBe(true)
			expect(E.Get(p, "Ectoplasm")).toBe(1600)
			expect(p:GetAttribute("Ectoplasm")).toBe(1600)
			expect(p.leaderstats.Ectoplasm.Value).toBe("1.6K")
			expect(E.TrySpend(p, "Ectoplasm", 2000)).toBe(false)
			expect(E.Get(p, "Ectoplasm")).toBe(1600)
			expect(E.TrySpend(p, "Ectoplasm", 600)).toBe(true)
			expect(E.Get(p, "Ectoplasm")).toBe(1000)
			expect(ctx.services.DataService.Get(p).stats.totalEctoplasm).toBe(1500)
		end)

		it("rejects invalid amounts and currencies", function()
			local ctx = boot()
			local E = ctx.services.EconomyService
			local p = ctx.players:Join(21, "Hacker")
			settle()
			expect(E.Add(p, "Ectoplasm", -50)).toBe(false)
			expect(E.Add(p, "Ectoplasm", 0 / 0)).toBe(false)
			expect(E.Add(p, "Ectoplasm", math.huge)).toBe(false)
			expect(E.Add(p, "Robux", 10)).toBe(false)
			expect(E.TrySpend(p, "Ectoplasm", -10)).toBe(false)
			expect(E.Get(p, "Ectoplasm")).toBe(100)
		end)

		it("does nothing for players whose data hasn't loaded", function()
			local ctx = boot()
			local E = ctx.services.EconomyService
			local roblox = require("@lune/roblox")
			local ghost = roblox.Instance.new("Player")
			expect(E.Add(ghost, "Ectoplasm", 10)).toBe(false)
			expect(E.Get(ghost, "Ectoplasm")).toBe(0)
		end)

		it("composes income multipliers (rebirth x peaceful base x others)", function()
			local ctx = boot()
			local E = ctx.services.EconomyService
			local DS = ctx.services.DataService
			local p = ctx.players:Join(22, "Multi")
			settle()
			expect(E.GetIncomeMultiplier(p)).toBe(1)
			DS.Get(p).stats.rebirths = 1
			expect(E.GetIncomeMultiplier(p)).toBe(1.5)
			DS.ApplySetting(p, "peacefulBase", true)
			expect(E.GetIncomeMultiplier(p)).toBeNear(1.2)
			expect(p:GetAttribute("IncomeMultiplier")).toBeNear(1.2)
			E.RegisterMultiplier("TestPass", function()
				return 2
			end)
			expect(E.GetIncomeMultiplier(p)).toBeNear(2.4)
			E.RegisterMultiplier("Broken", function()
				error("boom")
			end)
			expect(E.GetIncomeMultiplier(p)).toBeNear(2.4)
		end)
	end)
end
