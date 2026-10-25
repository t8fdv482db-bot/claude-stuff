--!nocheck
local Context = require("../harness/Context")
local task = require("@lune/task")

return function(T)
	local describe, it, expect = T.describe, T.it, T.expect
	local ctx = Context.new()
	local Format = ctx.get("ReplicatedStorage/Shared/Util/Format")
	local RateLimiter = ctx.get("ReplicatedStorage/Shared/Util/RateLimiter")
	local Signal = ctx.get("ReplicatedStorage/Shared/Util/Signal")
	local Net = ctx.get("ReplicatedStorage/Shared/Net")

	describe("Format.Abbreviate", function()
		it("formats small and large numbers", function()
			expect(Format.Abbreviate(0)).toBe("0")
			expect(Format.Abbreviate(950)).toBe("950")
			expect(Format.Abbreviate(12.5)).toBe("12.5")
			expect(Format.Abbreviate(1200)).toBe("1.2K")
			expect(Format.Abbreviate(1234)).toBe("1.23K")
			expect(Format.Abbreviate(15300)).toBe("15.3K")
			expect(Format.Abbreviate(999999)).toBe("1M")
			expect(Format.Abbreviate(2.5e6)).toBe("2.5M")
			expect(Format.Abbreviate(1e10)).toBe("10B")
			expect(Format.Abbreviate(-4200)).toBe("-4.2K")
			expect(Format.Abbreviate(0 / 0)).toBe("0")
		end)
		it("formats time and commas", function()
			expect(Format.Time(65)).toBe("1:05")
			expect(Format.Time(3725)).toBe("1:02:05")
			expect(Format.Commas(1234567)).toBe("1,234,567")
			expect(Format.Commas(-1000)).toBe("-1,000")
			expect(Format.Commas(12)).toBe("12")
		end)
	end)

	describe("RateLimiter", function()
		it("allows a burst then refills over time", function()
			local rl = RateLimiter.new(2, 2)
			expect(rl:Allow("p", 0)).toBe(true)
			expect(rl:Allow("p", 0)).toBe(true)
			expect(rl:Allow("p", 0)).toBe(false)
			expect(rl:Allow("other", 0)).toBe(true)
			expect(rl:Allow("p", 0.5)).toBe(true) -- +1 token after 0.5s at 2/s
			expect(rl:Allow("p", 0.5)).toBe(false)
		end)
	end)

	describe("Signal", function()
		it("fires, disconnects and supports Once", function()
			local s = Signal.new()
			local got = {}
			local c = s:Connect(function(v)
				table.insert(got, v)
			end)
			s:Once(function(v)
				table.insert(got, "once" .. v)
			end)
			s:Fire(1)
			c:Disconnect()
			s:Fire(2)
			task.wait()
			expect(got).toEqual({ 1, "once1" })
		end)
	end)

	describe("Net.Validate", function()
		local def = Net.Definitions.UpdateSetting
		it("accepts valid arguments", function()
			expect(Net.Validate(def, { "musicVolume", 0.5 }, 2)).toBe(true)
		end)
		it("rejects unknown enum values, wrong types and extra args", function()
			expect(Net.Validate(def, { "walkSpeed", 100 }, 2)).toBe(false)
			expect(Net.Validate(def, { 5, true }, 2)).toBe(false)
			expect(Net.Validate(def, { "musicVolume", 1, "extra" }, 3)).toBe(false)
		end)
		it("rejects NaN, infinity and non-integers", function()
			local numDef = { kind = "Event", direction = "ClientToServer", args = { "number", "integer" } }
			expect(Net.Validate(numDef, { 1, 2 }, 2)).toBe(true)
			expect(Net.Validate(numDef, { 0 / 0, 2 }, 2)).toBe(false)
			expect(Net.Validate(numDef, { math.huge, 2 }, 2)).toBe(false)
			expect(Net.Validate(numDef, { 1, 2.5 }, 2)).toBe(false)
		end)
		it("enforces ranges, lengths and optionals", function()
			local d = {
				kind = "Event",
				direction = "ClientToServer",
				args = { { type = "number", min = 0, max = 10 }, { type = "string", maxLength = 5 }, "boolean?" },
			}
			expect(Net.Validate(d, { 5, "abc" }, 2)).toBe(true)
			expect(Net.Validate(d, { 11, "abc" }, 2)).toBe(false)
			expect(Net.Validate(d, { 5, "abcdefg" }, 2)).toBe(false)
			expect(Net.Validate(d, { 5, "a", "yes" }, 3)).toBe(false)
			expect(Net.Validate(d, { 5 }, 1)).toBe(false)
		end)
		it("defines every remote with a known kind and direction", function()
			for name, d in Net.Definitions do
				expect(d.kind == "Event" or d.kind == "Function").toBe(true)
				expect(d.direction == "ClientToServer" or d.direction == "ServerToClient").toBe(true)
				if d.direction == "ClientToServer" then
					expect(d.args ~= nil).toBe(true) -- every client input has a schema
				end
			end
		end)
	end)
end
