# Clip Studio

**Paste a stream link → get finished, captioned vertical Shorts of the most hype moments.**

Clip Studio runs on your own computer (Windows or Mac). You paste a YouTube, Twitch or Kick link
(a finished video/VOD *or* a channel that's live right now). It finds the best 20–60 second
moments using chat, audio and what the streamer says, then turns each one into a 1080×1920
Short with word-by-word captions, a title and a hook. You check every clip in your browser, nudge
the cut if needed, approve it, and then either schedule it on YouTube or download it for TikTok,
Reels, X and paid clipping campaigns (Whop / Content Rewards).

Nothing is ever posted unless you approved it.

---

## Contents

1. [Install](#1-install)
2. [First run](#2-first-run)
3. [Add Lacy and Marlon](#3-add-lacy-and-marlon)
4. [The facecam picker](#4-the-facecam-picker-split-layout)
5. [Make clips from a VOD](#5-make-clips-from-a-vod-or-video)
6. [Live streams (GTA 6 launch day)](#6-live-streams-gta-6-launch-day)
7. [Review clips](#7-review-clips)
8. [AI titles and filtering (optional)](#8-ai-titles-and-filtering-optional)
9. [YouTube scheduling](#9-youtube-scheduling)
10. [Campaigns (Whop / Content Rewards)](#10-campaigns-whop--content-rewards)
11. [Export for TikTok, Reels and X](#11-export-for-tiktok-reels-and-x)
12. [Settings explained](#12-settings-explained)
13. [Speed tips](#13-speed-tips)
14. [Troubleshooting](#14-troubleshooting)
15. [Where your files are](#15-where-your-files-are)
16. [For developers](#16-for-developers)

---

## 1. Install

You need two free things: **Python** (3.11 or newer) and **ffmpeg** (the video engine).

### Windows

1. Open **PowerShell** (press Start, type *PowerShell*, press Enter) and paste these two lines:
   ```
   winget install Python.Python.3.12
   winget install Gyan.FFmpeg
   ```
2. **Close** PowerShell (so Windows notices the new programs).
3. Download Clip Studio (green **Code** button on GitHub → *Download ZIP*) and unzip it somewhere
   like `Documents\ClipStudio`.
4. Double-click **`run.bat`**.

### Mac

1. Install Homebrew if you don't have it (instructions at <https://brew.sh>), then in **Terminal**:
   ```
   brew install python@3.12 ffmpeg
   ```
2. Download and unzip Clip Studio (e.g. into your Documents folder).
3. In Terminal, drag the `run.sh` file into the window and press Enter
   (or `cd` into the folder and run `./run.sh`).

The **first start takes a few minutes** – it creates a private Python environment (`.venv`) and
installs everything. After that it starts in seconds and updates the downloader (`yt-dlp`)
automatically, so YouTube/Twitch/Kick changes don't break it.

> Already comfortable with Python? `pip install -r requirements.txt` then `python -m clipstudio`
> does the same thing. Add `--port 9000` for another port or `--no-browser` to not open a tab.

## 2. First run

Clip Studio opens in your browser at **http://127.0.0.1:8765**. It only listens on your own
computer – nobody on your network or the internet can reach it.

Keep the black window (the "server") open while you use it. Closing it stops Clip Studio.
If you close it in the middle of a job, just start it again: unfinished jobs continue where they
left off (downloads, transcripts, loudness and chat are all saved as they go).

The first time you make clips, the speech-to-text model (Whisper) downloads once (~500 MB for the
default model).

## 3. Add Lacy and Marlon

**Lacy** and **Marlon** are already there under **Streamers**. For each one:

1. Click their name.
2. Pick a **layout**:
   - **Split** – facecam on top, gameplay below (best for streamers; needs the facecam box, see next section).
   - **Blur** – the whole frame in the middle over a blurred copy (works for anything).
   - **Center crop** – just the middle of the screen.
3. **Hype words** (one per line): things they say when something big happens – e.g. `let's go`,
   `no shot`, `chat look`, their catchphrases. These boost the score when they're said.
4. **Default tags**: hashtags added to every description, e.g. `#lacy, #gta6`.
5. Press **Save**.

To add someone else: **Streamers → Add streamer**, or pick **+ New…** in the streamer dropdown on
the home page.

## 4. The facecam picker (split layout)

1. On the streamer's page, paste a link to one of their videos, VODs or their live channel, type a
   time where the facecam is visible (e.g. `1:23:45`) and press **Grab frame**.
   You can also **Upload screenshot** instead.
2. **Drag a rectangle** over the facecam. Drag inside the box to move it; hold Shift to draw a new one.
3. Watch the **9:16 preview** on the right – that's exactly how the Short will be laid out
   (facecam on top ≈38% of the height, gameplay below, both filled by cropping – never black bars).
4. Press **Save facecam**.

If a split-layout streamer has no facecam box yet, their clips use the blur layout until you add one.

## 5. Make clips from a VOD or video

1. On the **Jobs** page, paste one or more links (one per line). Each line becomes its own job.
   A badge shows what was detected, e.g. **Twitch · VOD** or **Kick · LIVE**.
   You can also paste the path of a video file on your computer.
2. Choose the **streamer**, how many **clips**, min/max **length**, **layout**, **campaign** and
   whether to use **AI review**.
3. Press **Find clips**.

Each job shows its progress live: *queued → downloading → chat → transcribing → scoring → rendering → done*,
with a percentage, the elapsed time, a **Log** drawer and **Cancel**.

What happens under the hood:

- Only the **audio** is downloaded first (small and fast), and Twitch/YouTube **chat replay**
  downloads at the same time. Kick has no chat replay, so Kick VODs are scored on audio + speech
  (the log says so).
- Speech is transcribed with word timings. On long VODs (over 90 minutes) Clip Studio only
  transcribes around the most promising moments, which is much faster.
- Moments are scored (see below), then **only the needed pieces of the video** are downloaded
  (max 1080p) – not the whole 8-hour VOD.
- Each clip is rendered: 1080×1920, 30 fps, captions burned in, loudness normalised to −14 LUFS,
  plus a thumbnail and a 3-second preview.

Videos longer than 12 hours are refused (change this in Settings → Storage).

**How "hype" is found.** Every second gets a score from:

- **Chat speed** – messages per second, extra weight for `LUL`, `KEKW`, `OMEGALUL`, `LMAO`, 💀, 😂,
  `W`, `L`, `???`, `!!!`, "no way", "clip it", "clip that", "bro", "nah" (chat is shifted back
  ~5 s because people react late).
- **Audio** – loudness compared with the last few minutes, sudden jumps, and short spiky bursts
  (yelling, laughing, screaming).
- **What they say** – hype phrases, exclamations and their personal hype words.
- **Viewer clips** (Twitch) – moments viewers clipped count as a strong signal.

Each signal is compared with the previous ~5 minutes, so a loud streamer isn't "always hype".
The best peaks (at least 90 s apart) become clips: ~18 s of setup before the peak and ~8 s of
reaction after, snapped to sentence boundaries so clips never start or end mid-word.
You can change the weights in **Settings → Scoring**.

## 6. Live streams (GTA 6 launch day)

Paste a **channel link** – `https://www.twitch.tv/<name>`, `https://kick.com/<name>` or a YouTube
live link – while they're live. The job then does two things at once:

**A. Highlights so far (catch-up).**
- **Twitch:** finds the VOD of the current broadcast and clips the last 3 hours of it
  (if the channel has VODs turned off, this part is skipped and the log says so).
- **YouTube:** downloads the stream from the start (last 3 hours).
- **Kick:** skipped if Kick doesn't offer the stream as a VOD yet (watch mode still works).

**B. Watch mode (until you press *Stop watching* or the stream ends).**
- Records the stream in 5-minute pieces (keeps the last 2 hours, deletes older pieces).
- Reads live chat (Twitch and YouTube; Kick on a best-effort basis).
- Every minute it transcribes the newest audio and updates the score.
- When a moment beats the threshold (and is 90 s away from the last clip), it waits for the
  reaction to finish, cuts it and renders it **immediately** – typically 1–3 minutes after it happened.
- You get a **sound + pop-up** in Clip Studio (on any page) and, if you set one up, a
  **Discord message** with the title and a link to review it.
- The job page shows a **live chart** of the hype score with markers where clips were made.

Launch-day tips:

- Start the job a few minutes *after* they go live. One job per streamer.
- Use a GPU or the `base.en` Whisper model if your computer struggles to keep up (Settings → Transcription).
- Too many clips? Raise **Settings → Live mode → Clip threshold** (default 2.2). Too few? Lower it.
- Turn on the Discord webhook so your phone buzzes for every clip.

## 7. Review clips

The **Review** page shows every clip as a card with a vertical player, streamer, length, score,
the AI's reason (if used), an editable title, description and hook.

- Tabs: **Pending / Approved / Rejected / Posted / All**, plus filters by streamer and job.
- **Trim:** start −1s / +1s, end −1s / +1s and **Extend 5s**. The clip re-renders in the background
  (the card shows a spinner).
- **Hook:** type 2–6 words and press **Apply** – shown in a white box for the first 3 seconds.
- **✨ New title** asks the AI for a fresh title (needs an API key).
- **Keyboard:** `A` approve, `R` reject, `J`/`K` next/previous, `Space` play/pause.

## 8. AI titles and filtering (optional)

With AI review on, every candidate moment (the detector picks twice as many as you asked for) is
sent to Claude with the transcript around it and a summary of the chat burst. Claude scores it
1–10 (does it stand on its own, is there a payoff?), can tighten the cut, writes a title (under
70 characters, includes the streamer's name, no lies, no hashtags) and a 2–6 word hook.
Clips scoring below 6 are dropped. Bad suggestions (e.g. a cut that's too long) are ignored and the
detector's cut is kept.

To turn it on:

1. Create an API key at <https://console.anthropic.com> (Settings → API keys). You need some credit.
2. In Clip Studio go to **Settings → AI review**, paste the key, tick **Use AI review by default**, Save.
   (Or set the `ANTHROPIC_API_KEY` environment variable.)

The key is stored only on your computer and is never written to logs. Each job shows its token
use and estimated cost. With the default model (`claude-sonnet-5-5`) it's roughly half a cent per
candidate clip.

## 9. YouTube scheduling

One-time setup (about 10 minutes):

1. Go to <https://console.cloud.google.com>, create a project (any name).
2. **APIs & Services → Library**: search **YouTube Data API v3** → **Enable**.
3. **APIs & Services → OAuth consent screen**: choose **External**, fill in the app name and your
   email. Under **Test users** add the Google account that owns your YouTube channel.
4. **APIs & Services → Credentials → Create credentials → OAuth client ID**, type **Desktop app**.
   Download the JSON file.
5. In Clip Studio: **Settings → YouTube → Upload client_secret.json**, then **Connect YouTube account**
   and sign in with your channel's Google account.
6. Set your **upload slots** (e.g. `11:00, 15:00, 19:00, 22:00`) and your **timezone**, Save.

Then on the Review page approve clips and press **📅 Schedule approved on YouTube**. Each approved
clip is uploaded as **private** with a scheduled publish time in your next free slot, with `#shorts`
added. The **Schedule** page shows the week as a calendar.

> **Important:** Google only lets *unverified* API projects upload **private** videos. Until your
> project passes Google's audit (request it in the Cloud Console under the YouTube API quotas page),
> scheduled clips stay private and won't go public by themselves – publish them by hand in YouTube
> Studio or get the project verified.

YouTube allows a limited number of uploads per day through the API. When the limit is hit you'll
see *"YouTube daily quota reached, the rest will retry tomorrow"* – the remaining clips are retried
automatically after the quota resets.

## 10. Campaigns (Whop / Content Rewards)

Under **Campaigns**, create one profile per paid campaign with its rules:

- name and payout notes
- allowed platforms (YouTube / TikTok / Instagram / X)
- min/max length
- required **disclosure** text (burned into the top corner for the first few seconds *and* put as
  the first line of the description)
- required hashtags or @mentions
- footage must come from a specific channel (optional)
- **submit window** in minutes (e.g. 30) and the link to the campaign's **submission page**

Pick the campaign on the home page when you start a job. Clips are kept within the campaign's
length limits, and the Review page **warns** you if a clip breaks a rule (wrong length, missing
disclosure, missing tags, wrong source, platform not allowed).

After you post a clip, press **Mark posted…**, pick the platform and paste the post's link. A
countdown starts – *"Submit within 30:00"* – with a button to the submission page. When you've
submitted, press **Submitted ✔**. The **Submissions** page lists every post with its countdown.

## 11. Export for TikTok, Reels and X

- Each clip card has **⬇ MP4** and **⬇ Caption** (a .txt with the disclosure, title, description
  and hashtags ready to paste).
- **⬇ Export all approved (.zip)** on the Review page downloads every approved clip with its caption file.

## 12. Settings explained

| Section | What it does |
|---|---|
| Clips | Default number of clips, min/max length, default layout. |
| Scoring | How much chat, audio, speech and viewer clips count; the chat hype words. |
| Transcription | Whisper model (`tiny.en` fastest … `large-v3` best), CPU/GPU, smart vs full transcription. |
| AI review | On/off, API key, model, minimum AI score. |
| Captions | Font, size, colours, words per caption line (2–3 looks best). |
| YouTube | client_secret.json, connect account, upload slots, timezone. |
| Live mode | Clip threshold, reaction tail, how much footage to keep, catch-up hours. |
| Notifications | Discord webhook (create one in Discord: channel → Edit → Integrations → Webhooks). |
| Storage | Where files go, max disk use (oldest *source* files are deleted automatically when over), keep source files, max video length, jobs at once. |

## 13. Speed tips

- **NVIDIA GPU?** Clip Studio uses it automatically for transcription (much faster). If the GPU
  can't be used it falls back to the CPU on its own.
- On a slower computer pick **`base.en`** in Settings → Transcription.
- Keep **Transcribe: Smart** – on long VODs it only transcribes around likely moments.
- Renders run in parallel (half your CPU cores), so the page never freezes.

## 14. Troubleshooting

| Message | Fix |
|---|---|
| *ffmpeg not found* | Windows: `winget install Gyan.FFmpeg`, Mac: `brew install ffmpeg`, then restart Clip Studio. |
| *This Kick VOD isn't reachable* / *isn't reachable* | The video was deleted, is region-locked, or the site blocked the request. Try again later or check the link in your browser. |
| *… isn't live right now* | You pasted a channel link while they're offline. Paste a VOD link instead. |
| *private or subscriber-only* | Clip Studio can only download public videos. |
| Downloads suddenly fail for every link | Restart Clip Studio with run.bat / run.sh – it updates the downloader on start. |
| A clip says *Render failed* | Press **Retry** on the card; the job **Log** shows details. |
| Captions look like a different font | The font in Settings must be installed on your computer (Arial is safe). |
| YouTube: *quota reached* | Normal – the rest upload automatically tomorrow. |

## 15. Where your files are

Everything lives in a **ClipStudio** folder in your home folder (`C:\Users\<you>\ClipStudio` or
`~/ClipStudio`): the database, YouTube login, and a `media` folder with jobs, caches and the
rendered clips (`media/clips/<number>/clip.mp4`). You can move the media folder in Settings → Storage.
To start completely fresh, close Clip Studio and delete that folder.

---

## 16. For developers

```
clipstudio/
  app.py          FastAPI routes + Server-Sent Events
  worker.py       job queue (thread pool), cancellation, progress events, render limiter
  pipeline.py     VOD pipeline + clip rendering orchestration, disk housekeeping
  live.py         watch mode: segment recorder, rolling analysis, catch-up
  sources/        detection + youtube.py, twitch.py, kick.py, chat.py, common.py (yt-dlp)
  transcribe.py   faster-whisper, chunked + cached
  scoring.py      per-second signals, rolling z-scores, peak picking, windows
  ai.py           Claude review (structured JSON output) + title regeneration
  render.py       layouts, ASS captions, thumbnails/GIF
  publish.py      YouTube OAuth/upload/scheduler + export
  campaigns.py    campaign rule checker
  db.py           SQLite (plain sqlite3)
  templates/ static/   server-rendered HTML, vanilla JS, one CSS file — no build step
tests/
```

Run the tests (needs ffmpeg): `pip install pytest && python -m pytest tests`.
The synthetic end-to-end tests generate a 6-minute `testsrc2` video with loud spikes, a fake chat
file and a fake transcript, and check the scorer finds the planted moments (±5 s) and renders
1080×1920 clips with audio, both for VODs and for live watch mode.

Design notes: the server binds to 127.0.0.1 only; every external command is an argument list
(no shell strings); ffmpeg renders run with the clip folder as working directory and a relative
`captions.ass` (avoids Windows drive-letter escaping); every long step caches to disk so restarts
resume; API keys and OAuth tokens are never logged.
