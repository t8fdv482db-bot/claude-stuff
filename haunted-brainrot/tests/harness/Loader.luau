--!nocheck
--[[
	Loader: runs the game's real Luau source under Lune.

	The src/ tree is materialised as real Lune Instances inside a DataModel, following Rojo's rules:
	  Foo.luau          -> ModuleScript "Foo"
	  Foo.server.luau   -> Script "Foo"
	  Foo.client.luau   -> LocalScript "Foo"
	  Foo/              -> Folder "Foo" (or ModuleScript if it has init.luau)
	Each script records its file path in the "__path" attribute; `require(moduleScript)` loads that
	file with `script` set to the instance, so `require(script.Parent.Config.X)` works unchanged.

	`game:GetService(name)` returns mocks (Players, DataStoreService, ...) when supplied, otherwise
	the real Lune service instance.
]]

local fs = require("@lune/fs")
local luau = require("@lune/luau")
local roblox = require("@lune/roblox")
local task = require("@lune/task")

local Loader = {}

local function classFor(entry)
	if entry:match("%.server%.luau$") then
		return "Script", (entry:gsub("%.server%.luau$", ""))
	elseif entry:match("%.client%.luau$") then
		return "LocalScript", (entry:gsub("%.client%.luau$", ""))
	elseif entry:match("%.luau$") then
		return "ModuleScript", (entry:gsub("%.luau$", ""))
	end
	return nil
end

local function build(dir, parent)
	for _, entry in fs.readDir(dir) do
		local path = `{dir}/{entry}`
		if fs.isDir(path) then
			local isModule = fs.isFile(`{path}/init.luau`)
			local inst = roblox.Instance.new(if isModule then "ModuleScript" else "Folder")
			inst.Name = entry
			if isModule then
				inst:SetAttribute("__path", `{path}/init.luau`)
			end
			build(path, inst)
			inst.Parent = parent
		elseif entry ~= "init.luau" then
			local className, name = classFor(entry)
			if className then
				local inst = roblox.Instance.new(className)
				inst.Name = name
				inst:SetAttribute("__path", path)
				inst.Parent = parent
			end
		end
	end
end

function Loader.new(opts)
	--[[
		opts.root      : project root (contains src/)
		opts.services  : { [ServiceName]: "src/..." }  directories mapped like default.project.json
		opts.mocks     : { [ServiceName]: any }          mock services
		opts.globals   : extra / overriding globals
	]]
	local self = { cache = {}, opts = opts, warnings = {}, closeCallbacks = {} }
	local dataModel = roblox.Instance.new("DataModel")
	for serviceName, dir in opts.services or {} do
		build(`{opts.root}/{dir}`, dataModel:GetService(serviceName))
	end

	local closeCallbacks = self.closeCallbacks
	local game = {}
	function game:GetService(name)
		if opts.mocks and opts.mocks[name] then
			return opts.mocks[name]
		end
		return dataModel:GetService(name)
	end
	function game:BindToClose(fn)
		table.insert(closeCallbacks, fn)
	end
	game.Workspace = dataModel:GetService("Workspace")
	game.JobId = opts.jobId or "test-job"
	game.PlaceId = 0
	self.game = game
	self.dataModel = dataModel

	local base = getfenv(0)
	local globals = {
		game = game,
		workspace = game.Workspace,
		task = task,
		Instance = roblox.Instance,
		Vector3 = roblox.Vector3,
		Vector2 = roblox.Vector2,
		CFrame = roblox.CFrame,
		Color3 = roblox.Color3,
		Enum = roblox.Enum,
		UDim = roblox.UDim,
		UDim2 = roblox.UDim2,
		NumberSequence = roblox.NumberSequence,
		NumberSequenceKeypoint = roblox.NumberSequenceKeypoint,
		ColorSequence = roblox.ColorSequence,
		ColorSequenceKeypoint = roblox.ColorSequenceKeypoint,
		NumberRange = roblox.NumberRange,
		Font = roblox.Font,
		Rect = roblox.Rect,
		PhysicalProperties = roblox.PhysicalProperties,
		warn = function(...)
			local parts = table.pack(...)
			for i = 1, parts.n do
				parts[i] = tostring(parts[i])
			end
			table.insert(self.warnings, table.concat(parts, " ", 1, parts.n))
			if opts.quiet == false then
				print("WARN", ...)
			end
		end,
		print = function(...)
			if opts.quiet == false then
				print(...)
			end
		end,
		typeof = typeof,
		time = os.clock,
	}
	for k, v in opts.globals or {} do
		globals[k] = v
	end
	self.globals = globals

	local function makeEnv(inst, requireFn)
		-- Plain table (no __index): Luau resolves global imports when the chunk loads.
		local env = {}
		for k, v in base do
			env[k] = v
		end
		for k, v in globals do
			env[k] = v
		end
		env.script = inst
		env.require = requireFn
		return env
	end

	local function requireModule(inst)
		assert(typeof(inst) == "Instance" and inst:IsA("ModuleScript"), `require expects a ModuleScript, got {inst}`)
		local file = inst:GetAttribute("__path")
		assert(file, `{inst.Name} has no source file`)
		if self.cache[file] ~= nil then
			return self.cache[file]
		end
		local fn = luau.load(fs.readFile(file), { debugName = file, environment = makeEnv(inst, requireModule) })
		local result = fn()
		self.cache[file] = result
		return result
	end
	self.require = requireModule

	-- Instance for "Service/Path/To/Thing".
	function self.instance(path)
		local parts = string.split(path, "/")
		local node = dataModel:GetService(parts[1])
		for i = 2, #parts do
			node = node:FindFirstChild(parts[i]) or error(`missing {parts[i]} in {path}`)
		end
		return node
	end

	-- Convenience: require by "Service/Path/To/Module".
	function self.get(path)
		return requireModule(self.instance(path))
	end

	-- Runs a Script / LocalScript instance's source (e.g. Main.server.luau).
	function self.runScript(inst)
		local file = inst:GetAttribute("__path")
		return luau.load(fs.readFile(file), { debugName = file, environment = makeEnv(inst, requireModule) })()
	end

	return self
end

return Loader
