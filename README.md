# AdGen — AI video ad generator

Give it a product brief and it produces finished 15/20/30-second video ads with a
photorealistic, **fully synthetic** AI presenter speaking with a natural voice:

* 3 script variants for A/B tests (Claude). Each has a 2–3 s hook, then problem → solution → CTA, timed at about 2.5 words/sec.
* A reusable presenter library ("brand faces"). Each presenter has a generated portrait and a matching designed voice.
* A natural voice-over with emotion tags and real word timings (ElevenLabs v3).
* Lip-synced talking-head shots (Kling Avatar v2 / OmniHuman 1.5 via fal.ai).
* Product B-roll with camera motion between the talking shots.
* Word-by-word TikTok-style burned-in captions.
* Ducked background music (ElevenLabs Music, or your own library).
* A logo + CTA end card.
* A small **"AI-generated"** disclosure label, on by default.
* Loudness normalised to −14 LUFS and exported as H.264 MP4 in **9:16, 1:1 and 16:9**.
* A cost estimate before every paid step, and a cost log after.

There is a CLI first and a simple local web UI on top. Every step can also run in a free
**offline mock mode**, so you can try the whole pipeline without keys.

## Quick start

Requires Python 3.11+ and ffmpeg (with libass) on your `PATH`.

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"

# 1. Free offline end-to-end run on the bundled fictional product:
adgen demo                      # -> output/pocket-brew/<timestamp>/variant_A/ad_9x16.mp4 ...

# 2. Real renders: add keys
cp .env.example .env            # fill ANTHROPIC_API_KEY, ELEVENLABS_API_KEY, FAL_KEY
```

### CLI workflow

```bash
# Scripts: 3 variants, compliance-checked, saved under output/<product>/scripts/
adgen script examples/sample_product/brief.json

# Presenter: generate once, reuse forever
adgen avatar create "Maya" --age "late 20s" --gender woman --ethnicity "Latina" \
  --setting "sunny kitchen with plants" --outfit "cream knit sweater" --accent American
adgen avatar list

# Optional: audition the voice-over for one variant
adgen voice examples/sample_product/brief.json --avatar maya --variant B

# See the cost first, then render (prompts for confirmation; -y to skip)
adgen estimate examples/sample_product/brief.json
adgen render examples/sample_product/brief.json --avatar maya --variants A,C
adgen render ... --lipsync omnihuman_v15 --no-music --ratios 9:16,1:1

adgen costs                     # everything you've spent, from output/cost_log.jsonl
adgen web                       # web UI at http://127.0.0.1:8000
```

Add `--offline` to any command to use the mock providers.

### Brief format

See `examples/sample_product/brief.json`:

| field | meaning |
|---|---|
| `name`, `description`, `target_audience` | the product and who it's for |
| `selling_points` | the **only** claims scripts may make |
| `approved_claims` | optional extra facts you can substantiate (offers, prices, stats) |
| `image_paths`, `logo_path`, `product_url` | used for B-roll and the end card (paths relative to the brief or the working dir) |
| `cta` | call to action, also shown on the end card |
| `tone` | free text, e.g. "casual UGC", "polished", "funny" |
| `length` | 15, 20 or 30 |
| `aspect_ratios` | any of "9:16", "1:1", "16:9" |
| `language` | ISO code; scripts are written in it and the TTS is told which language it is |

## Output

```
output/
  cost_log.jsonl                         # every paid call: scripts, avatars, renders
  pocket-brew/
    scripts/20261024-101500.json         # all 3 variants + their cost
    20261024-101812/                     # one render job
      job.json                           # summary + total spend
      music.mp3                          # shared bed for the job
      variant_A/
        ad_9x16.mp4  ad_1x1.mp4  ad_16x9.mp4
        thumbnail.jpg  thumbnail_1x1.jpg  thumbnail_16x9.jpg
        script.json  script.txt          # what was said, shot by shot
        settings.json                    # brief, avatar, providers, options, warnings
        cost.json                        # this variant's actual spend
        work/                            # intermediates (voice.wav, words.json, captions.ass, shots)
avatars/<id>/avatar.json, portrait.png, voice_preview.mp3
```

## Architecture

Each pipeline stage is its own module behind a small interface, so you can swap a provider by
changing one env var (`ADGEN_*_PROVIDER`) or adding one class.

```
brief.json
  └─ script/      ScriptWriter      claude (structured JSON + compliance audit) | mock
  └─ avatar/      PortraitProvider  flux2pro (fal.ai) | mock     + AvatarLibrary (portrait + voice id)
  └─ voice/       VoiceProvider     elevenlabs (Voice Design + v3 TTS w/ timestamps) | mock
                  fit_to_length     atempo ≤1.15x if long; rescales word timings
  └─ lipsync/     LipSyncProvider   kling_avatar_v2_pro | kling_avatar_v2_standard | omnihuman_v15 | mock
  └─ broll/       stills -> framed product over blurred fill -> zoompan motion
  └─ music/       MusicProvider     elevenlabs | library (your files) | none | mock
  └─ assembly/    captions (ASS, word-by-word), end card, 16:9 stage, ffmpeg compose:
                  concat shots -> burn captions + AI label -> sidechain-ducked mix
                  -> two-pass loudnorm (-14 LUFS, -1.5 dBTP) -> H.264/AAC MP4 + thumbnails
  pipeline.py     orchestrates, writes outputs, appends the cost log
  cost.py + pricing.yaml   estimates and actuals (edit prices to match your invoices)
  safety.py       synthetic-only presenter checks; claims/testimonial lint
```

How a render works:

1. **Voice**: the whole script is spoken in one take, so the prosody stays natural. Each
   segment's text is prefixed with a v3 emotion tag such as `[excited]`. The character-level
   timestamps become word timings, which then drive the cuts and the captions.
2. **Lip-sync only where the presenter is on screen**: consecutive on-camera segments are
   merged into "spans". Each span's audio window is sent to the lip-sync model. Windows
   shorter than 2 s are widened with neighbouring audio, which the cut hides. Results are
   cached by portrait and audio hash, so re-renders don't pay twice.
3. **Aspect ratios**: lip-sync is rendered once, in 9:16, and reframed for each ratio:
   * 9:16: full frame.
   * 1:1: a crop of the upper part of the frame.
   * 16:9: the presenter in a column on the left, the product framed on the right over a blurred fill.

   Because of this, extra ratios cost nothing.
4. **Timing**: the voice gets up to `length − 1.8 s`, and the end card fills the rest (1.5–3.5 s).
   If a script runs long, the voice is sped up by at most 15%; past that, the render warns you.

## Provider choices (researched Oct 2026)

| Need | Default | Alternatives wired in | Approx. price |
|---|---|---|---|
| Script | Claude `claude-opus-5-5` (adaptive thinking, structured output, server-side refusal fallback) | set `ADGEN_CLAUDE_MODEL` (e.g. `claude-sonnet-5-5`) | ~$0.10–0.20 per set of 3 incl. audit |
| Presenter portrait | FLUX.2 [pro] on fal.ai | — | ~$0.05 / image (one-off per avatar) |
| Voice | ElevenLabs Eleven v3 + Voice Design | `ADGEN_TTS_MODEL=eleven_multilingual_v2` | ~$0.08 / 1K chars (~$0.03 per 30 s ad) |
| Talking head | Kling AI Avatar v2 Pro (fal.ai) | OmniHuman 1.5 (premium, $0.16/s), Kling Avatar v2 Standard (budget, $0.056/s) | $0.115 / output second |
| Music | ElevenLabs Music (instrumental) | local licensed library, none | ~$0.15 / min |

Why this stack: fal.ai hosts several of the top image+audio→video avatar models behind one
API, so moving to a better model is a config change. ElevenLabs v3 has the most natural
emotion and breathing, covers 70+ languages, returns the timestamps the captions need, and
makes new synthetic voices from a text description. HeyGen and Synthesia were considered.
They are closed platforms with their own avatars, they charge more per minute for the
newest avatar models, and they're harder to compose with your own B-roll and editing.
Hedra Character-3 is a cheap alternative that would make a good additional adapter.

**Typical cost per finished ad**: about $1.50–$3.50 for a 20–30 s variant with Kling v2 Pro.
Most of that is lip-sync, about $0.115 per on-camera second; extra aspect ratios are free.
Every render shows a line-by-line estimate first and records actual spend in `cost.json`
and `output/cost_log.jsonl`. Prices live in `adgen/pricing.yaml`. Verify them against your
invoices, because provider pricing changes often.

## Compliance rules built in

* **Synthetic presenters only.** Presenters are generated from attribute descriptions
  (age, gender, ethnicity, setting, outfit). The app has no face upload and no voice cloning.
  Specs that reference real people are rejected ("looks like…", "sounds like…", celebrity
  terms, proper names), and the portrait prompt asks for an original, non-famous person.
* **Claims come only from your brief.** The Claude prompt forbids invented stats,
  testimonials, reviews and results, and forbids the presenter claiming to be a customer.
  Every draft then goes through three checks:
  1. a deterministic lint, which rejects numbers not in the brief and testimonial phrasing
     like "I've been using…", "customers say…", "#1", "clinically";
  2. a separate Claude compliance audit;
  3. up to two automatic revision rounds.

  If a draft still fails, nothing is rendered.
* **Disclosure.** The "AI-generated" label is on by default (`--no-ai-label` to turn it off),
  to help meet Meta, TikTok and YouTube AI-content disclosure rules. You still need to set
  each platform's own AI-content toggle when you upload.

## Development

```bash
pip install -e ".[dev]"
pytest -q        # 25 tests, including a full offline render; no keys or network needed
```

The real provider adapters (`script/claude.py`, `voice/elevenlabs.py`, `avatar/flux.py`,
`lipsync/fal.py`, `music/ElevenLabsMusic`) follow the providers' current API docs and SDKs,
and their request shapes are unit-tested with fakes. Before relying on a model, run one
short real render (`--variants A --ratios 9:16`) to confirm your account and keys work.
