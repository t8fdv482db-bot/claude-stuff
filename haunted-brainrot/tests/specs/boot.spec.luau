--!nocheck
local Context = require("../harness/Context")
local task = require("@lune/task")

return function(T)
	local describe, it, expect = T.describe, T.it, T.expect

	describe("Main.server.luau", function()
		it("boots every service, creates remotes and serves a joining player", function()
			local ctx = Context.new()
			ctx.runScript(ctx.instance("ServerScriptService/Main"))
			local remotes = ctx.game:GetService("ReplicatedStorage"):FindFirstChild("Remotes")
			expect(remotes ~= nil).toBe(true)
			local Net = ctx.get("ReplicatedStorage/Shared/Net")
			for name, def in Net.Definitions do
				local r = remotes:FindFirstChild(name)
				expect(r ~= nil).toBe(true)
				expect(r.ClassName).toBe(if def.kind == "Event" then "RemoteEvent" else "RemoteFunction")
			end
			local p = ctx.players:Join(100, "Booter")
			for _ = 1, 5 do
				task.wait()
			end
			expect(p:GetAttribute("DataLoaded")).toBe(true)
			-- No config problems were reported at boot.
			for _, w in ctx.warnings do
				expect(string.find(w, "[Config]", 1, true)).toBe(nil)
			end
		end)
	end)
end
