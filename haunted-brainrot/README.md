# Steal a Haunted Brainrot (Roblox)

> Collect goofy haunted brainrot creatures, show them off on your conveyor-belt haunted mansion,
> steal your friends' rarest ghosts — and defend your base when the Midnight Moon rises and the
> Phantom Raid begins.

Spooky-silly, never scary. The target audience is ages 8–16. The game is built phase by phase,
following the master build prompt.

## Phase status

| # | Phase | Status |
|---|---|---|
| 1 | Project structure, config modules, data saving | ✅ done |
| 2 | Plots & mansions (Floor 1), plot assignment, owner signs | ⏳ next |
| 3–13 | Conveyor, roster models, stealing, defenses, day/night + raid, events, upgrades/rebirth, UI, audio, monetization/safety, polish | planned |

## Opening it in Roblox Studio

You need [Rojo](https://rojo.space) (the Studio plugin plus the CLI). Pick one option:

* **Live sync (recommended):** in this folder run `rojo serve`. In Studio, open a new Baseplate,
  delete the Baseplate part, and click **Connect** in the Rojo plugin.
* **Place file:** run `rojo build default.project.json -o build/HauntedBrainrot.rbxlx`, then
  open the `.rbxlx` file in Studio.

To make saves persist while testing in Studio, enable **Game Settings → Security → Enable
Studio Access to API Services**. Without it, the game uses an in-memory store and warns you in
the Output window; you can still play.

## Project layout

```
default.project.json                  Rojo mapping (StreamingEnabled on)
src/
  ReplicatedStorage/Shared/
    Config/                           ALL balancing numbers
      RarityConfig.luau               odds 55/25/12/5/2.5/0.45/0.05, colours, steal hold, carry speed
      BrainrotConfig.luau             15 original brainrots + 5 mutations
      UpgradeConfig.luau              upgrades, floors, rebirths, defenses, gate lock
      EventConfig.luau                12-min day/night, Phantom Raid, rotating server events
      GameConfig.luau                 plots, conveyor, stealing rules, safety limits, data settings
      ConfigValidator.luau            sanity-checks every config at boot and in tests
    Net.luau                          every remote: schema validation + rate limiting + pcall
    Theme.luau                        palette and fonts
    Util/  Format, Signal, RateLimiter
  ServerScriptService/
    Main.server.luau                  boots services in order (Init, then Start)
    Services/  DataService, EconomyService
    Lib/       SessionStore (session-locked DataStore), DataTemplate, DataMigrations
  StarterPlayer/StarterPlayerScripts/
    Main.client.luau                  boots controllers
    Controllers/UIController.luau     currency HUD + toasts (mobile-first)
tests/                                Lune test suite that runs the real src/ code
scripts/check.sh                      lint + tests + build + verify
```

Remotes are created at runtime in `ReplicatedStorage/Remotes` from `Net.Definitions`. That one
table holds each remote's name, direction, argument schema and rate limit.

## Data saving (Phase 1)

* **Session locking:** `Lib/SessionStore.luau` stores the lock as `{jobId, time}` inside
  `UpdateAsync`. When a player hops servers, the new server waits until the old one has saved
  and released. If a crashed server leaves a lock behind, it is taken over once it is older than
  `GameConfig.Data.lockStaleSeconds`.
* **Never overwrites newer data:** if another server has taken the lock, this server's saves
  are refused and the player is told they joined elsewhere.
* **Autosave and shutdown:** data autosaves every 60 s, saves and releases on leave, and saves
  everyone in parallel during `BindToClose`.
* **Retries:** failed DataStore calls are retried with exponential backoff. If loading still
  fails, the player is kicked with a friendly message. They never play on a blank save that
  could overwrite their real one.
* **Versioning:** `DataTemplate.VERSION` plus the `DataMigrations.Migrations[n]` steps.
  Missing keys are reconciled from the template, wrong-typed values are repaired, and saves
  from a newer build are left untouched.

## Testing

Run `./scripts/check.sh`. It requires `selene`, `lune` and `rojo` (`cargo install selene lune rojo`).

* `lune run tests/run` runs the spec files against the real source. `tests/harness` rebuilds the
  `src/` tree as Instances the way Rojo does, and supplies mock Players, DataStoreService,
  RunService and TextService, plus engine shims for events, `Kick`, `WaitForChild` and `PivotTo`.
* `lune run tests/verify_build` checks the structure of the Rojo-built place.
* `selene.toml` uses the bundled `roblox_min.yml`. If you have network access, run
  `selene generate-roblox-std` and switch to `std = "roblox"` for full API checking.

### How to test Phase 1 in Studio

1. Start a Play session. The Output window should show
   `[Main] Steal a Haunted Brainrot server ready` and no `[Config]` warnings.
2. The HUD at the top shows 💚 100 / 🍬 0 / 💎 0. The leaderboard shows Ectoplasm and Rebirths.
3. Give yourself currency from the server Command Bar:
   `require(game.ServerScriptService.Services.EconomyService).Add(game.Players:GetPlayers()[1], "Ectoplasm", 5000)`.
   The 💚 counter ticks up and bounces.
4. With API access enabled, stop and play again. Your balance is still there.
5. Validation: from the client Command Bar, run
   `game.ReplicatedStorage.Remotes.UpdateSetting:FireServer("Ectoplasm", 1e9)`.
   The Output shows `[Net] rejected UpdateSetting`.
