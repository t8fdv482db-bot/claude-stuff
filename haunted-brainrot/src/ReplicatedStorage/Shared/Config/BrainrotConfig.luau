--!strict
--[[
	BrainrotConfig
	The full original roster plus mutations. All income/price balancing lives here.

	incomePerSecond : base Ectoplasm/sec before mutation, rebirth and pass multipliers
	price           : conveyor purchase price in Ectoplasm
	soundKey        : key into SoundConfig (added in the audio phase) for the idle "voice" sound
	particleKey     : key into the EffectsController particle presets
	modelName       : model in ServerStorage/Models/Brainrots
]]

local RarityConfig = require(script.Parent.RarityConfig)

export type BrainrotDef = {
	id: string,
	displayName: string,
	rarity: RarityConfig.RarityName,
	incomePerSecond: number,
	price: number,
	description: string,
	voiceLine: string,
	soundKey: string,
	particleKey: string,
	modelName: string,
}

export type MutationName = "GlowInTheDark" | "CandyCorn" | "Spectral" | "Golden" | "RainbowEctoplasm"

export type MutationDef = {
	id: MutationName,
	displayName: string,
	chance: number, -- percent chance per conveyor spawn (rolled once; mutations are exclusive)
	incomeMultiplier: number,
	material: Enum.Material?, -- overrides body material
	tint: Color3?, -- recolours the body (nil keeps original colours)
	transparency: number?, -- body transparency (Spectral)
	particleKey: string,
	color: Color3, -- label colour in UI
}

local BrainrotConfig = {}

local function def(
	id: string,
	displayName: string,
	rarity: RarityConfig.RarityName,
	incomePerSecond: number,
	price: number,
	description: string,
	voiceLine: string,
	particleKey: string
): BrainrotDef
	return {
		id = id,
		displayName = displayName,
		rarity = rarity,
		incomePerSecond = incomePerSecond,
		price = price,
		description = description,
		voiceLine = voiceLine,
		soundKey = id,
		particleKey = particleKey,
		modelName = id,
	}
end

-- stylua: ignore
BrainrotConfig.Roster = {
	-- Common
	def("SpookaroniNoodle", "Spookaroni Noodle", "Common", 2, 25,
		"A wiggly pasta ghost who can't stop doing the noodle dance.",
		"Wooo... pass the parmesan!", "NoodleSteam"),
	def("BooFfin", "Boo-ffin", "Common", 3, 40,
		"A blueberry muffin wearing a bedsheet. Fooling absolutely nobody.",
		"Boo! ...did that work?", "Crumbs"),
	def("SkellySock", "Skelly Sock", "Common", 4, 60,
		"A lonely sock with a skeleton print, still looking for its pair.",
		"Has anyone seen my left foot?", "SockFuzz"),
	-- Uncommon
	def("PumpkiniPanini", "Pumpkini Panini", "Uncommon", 9, 220,
		"A toasty sandwich with a jack-o'-lantern grin pressed into the bread.",
		"I'm grilled AND thrilled!", "PumpkinSparks"),
	def("GhostbananaRama", "Ghostbanana Rama", "Uncommon", 12, 320,
		"A banana that peels itself into a little ghostly cape.",
		"Slip into the spooky season!", "BananaPeels"),
	def("CauldronCrab", "Cauldron Crab", "Uncommon", 15, 420,
		"A crab that lives in a bubbling cauldron and pinches the bubbles.",
		"Snip snap, soup's on!", "CauldronBubbles"),
	-- Rare
	def("MummyMangoTango", "Mummy Mango Tango", "Rare", 35, 1800,
		"A mango wrapped in bandages that slowly unravel while it dances the tango.",
		"Wrap it up, I'm dancing!", "BandageRibbons"),
	def("VampirettiSpaghettoni", "Vampiretti Spaghettoni", "Rare", 45, 2600,
		"A spaghetti vampire with meatball eyes and a tomato-sauce cape.",
		"I vant to slurp your noodles!", "SauceDrips"),
	def("Batbrella", "Batbrella", "Rare", 55, 3400,
		"An umbrella with bat wings that flaps when it gets excited.",
		"Forecast: 100% chance of flaps!", "BatFlutter"),
	-- Epic
	def("WailingWaffleWizard", "Wailing Waffle Wizard", "Epic", 140, 12000,
		"A waffle wizard who sings dramatic opera while syrup spells swirl around.",
		"Abra-ca-WAFFLE!", "SyrupSpells"),
	def("Frankenfridge", "Frankenfridge", "Epic", 190, 18000,
		"A bolted-together fridge whose door swings open to reveal a disco ball.",
		"Stay cool... and BOOGIE!", "DiscoSparkles"),
	-- Legendary
	def("CountChompulaCheeseburger", "Count Chompula Cheeseburger", "Legendary", 650, 85000,
		"A noble cheeseburger count with a cape made of lettuce and fancy pickle fangs.",
		"Good evening... would you like fries?", "CheeseDrips"),
	def("TheGrandGhoulash", "The Grand Ghoulash", "Legendary", 900, 125000,
		"A giant soup bowl with a tiny ghost choir singing inside the steam.",
		"La la LAAA... soup's ready!", "ChoirNotes"),
	-- Mythic
	def("PhantomPizzaPharaoh", "Phantom Pizza Pharaoh", "Mythic", 5200, 1250000,
		"A floating pyramid of pizza slices orbiting a golden crown. Rules the snack kingdom.",
		"Bow before the extra cheese!", "PizzaOrbit"),
	-- Secret (Blood-Orange Moon only)
	def("MoonEaterMarshmallow", "The Moon-Eater Marshmallow", "Secret", 30000, 10000000,
		"A giant glowing marshmallow that nibbles moonlight. Mini-marshmallows orbit it like moons.",
		"*munch* ...the moon tastes like vanilla!", "MarshmallowMoons"),
} :: { BrainrotDef }

BrainrotConfig.ById = {} :: { [string]: BrainrotDef }
for _, b in BrainrotConfig.Roster do
	BrainrotConfig.ById[b.id] = b
end

-- Mutations: rolled once per conveyor spawn. Remaining probability = no mutation.
BrainrotConfig.Mutations = {
	{
		id = "GlowInTheDark",
		displayName = "Glow-in-the-Dark",
		chance = 4,
		incomeMultiplier = 1.5,
		material = Enum.Material.Neon,
		tint = Color3.fromRGB(170, 255, 140),
		particleKey = "GlowSpecks",
		color = Color3.fromRGB(170, 255, 140),
	},
	{
		id = "CandyCorn",
		displayName = "Candy Corn",
		chance = 2.5,
		incomeMultiplier = 2,
		material = Enum.Material.SmoothPlastic,
		tint = Color3.fromRGB(255, 160, 40),
		particleKey = "CandyCornBits",
		color = Color3.fromRGB(255, 170, 50),
	},
	{
		id = "Spectral",
		displayName = "Spectral",
		chance = 1.5,
		incomeMultiplier = 2.5,
		material = Enum.Material.Glass,
		transparency = 0.45,
		particleKey = "SpectralShimmer",
		color = Color3.fromRGB(170, 220, 255),
	},
	{
		id = "Golden",
		displayName = "Golden",
		chance = 1,
		incomeMultiplier = 3,
		material = Enum.Material.Metal,
		tint = Color3.fromRGB(255, 205, 60),
		particleKey = "GoldGlints",
		color = Color3.fromRGB(255, 210, 70),
	},
	{
		id = "RainbowEctoplasm",
		displayName = "Rainbow Ectoplasm",
		chance = 0.5,
		incomeMultiplier = 5,
		material = Enum.Material.Neon,
		particleKey = "RainbowGoo",
		color = Color3.fromRGB(255, 120, 255),
	},
} :: { MutationDef }

BrainrotConfig.MutationById = {} :: { [string]: MutationDef }
for _, m in BrainrotConfig.Mutations do
	BrainrotConfig.MutationById[m.id] = m
end

function BrainrotConfig.Get(id: string): BrainrotDef?
	return BrainrotConfig.ById[id]
end

function BrainrotConfig.GetByRarity(rarity: RarityConfig.RarityName): { BrainrotDef }
	local out = {}
	for _, b in BrainrotConfig.Roster do
		if b.rarity == rarity then
			table.insert(out, b)
		end
	end
	return out
end

-- Base income for one brainrot including its mutation (no player multipliers).
function BrainrotConfig.IncomeFor(id: string, mutation: string?): number
	local b = BrainrotConfig.ById[id]
	if not b then
		return 0
	end
	local mult = 1
	if mutation then
		local m = BrainrotConfig.MutationById[mutation]
		if m then
			mult = m.incomeMultiplier
		end
	end
	return b.incomePerSecond * mult
end

-- Sell-back value (used by the "sell" button): 50% of price, scaled by mutation.
BrainrotConfig.SellRatio = 0.5

return BrainrotConfig
