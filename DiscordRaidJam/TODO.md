# TODO List – FFLogs Discord Bot

This file outlines planned feature enhancements to make the bot more versatile and user-friendly.

---

## 🔄 Recent Logs Watcher
- [ ] Periodically check FFLogs for new public reports tied to registered characters.
- [ ] Alert a channel or user when new logs are detected.
- [ ] Include a cooldown or rate-limit to avoid spamming.

## 👥 Multi-Character Tracking
- [ ] Allow users to register multiple characters.
- [ ] Store character info in a persistent database (e.g., SQLite, PostgreSQL).
- [ ] Add `/characters` and `/addcharacter` commands for management.

## ⚔️ /compare Command
- [ ] Compare two characters side-by-side.
- [ ] Display encounters, best parses, and total kills per boss.
- [ ] Color-code or align results for clarity.

## 🚀 /mylogs Shortcut
- [ ] Allow users to save their main character.
- [ ] Enable `/mylogs` to use that saved character for quicker access.
- [ ] Add fallback if character is not set.

## 🐞 Error Reporting
- [ ] Add button or command for reporting issues (e.g., `/reporterror`).
- [ ] Log error reports to a channel or store in a log file.
- [ ] Include optional user message and system traceback if available.

## 💪 /flexscore Command
- [ ] Score a player’s performance with playful/snarky tone.
- [ ] Base it on their highest and lowest parse.
- [ ] Randomized humorous response pool.

## ☠️ /wipecounter Command
- [ ] Track how many wipes per encounter.
- [ ] Optionally allow user or channel-scoped sessions.
- [ ] Display formatted embed of kill/wipe ratios.

## 🩰 /dancepartner Command
- [ ] Implement `/dancepartner` slash command
- [ ] Parse and validate FFLogs report link
- [ ] Fetch player job and rDPS data via FFLogs GraphQL
- [ ] Translate Dance Partner scoring logic into Python
- [ ] Rank and sort players by synergy score
- [ ] Display top candidates in a formatted embed
- [ ] Add emoji for top candidate (e.g. 💃)
- [ ] Handle logs with no valid DPS candidates gracefully
 
## Description
## Suggests the optimal Dance Partner based on a provided FFLogs encounter link.
## Evaluates players based on job synergy and rDPS performance, using adapted logic from:
## [hintxiv/ts-partnercalc](https://github.com/hintxiv/ts-partnercalc).
