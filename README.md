# DiscordRaidJam - FFLogs Discord Bot

DiscordRaidJam is a Discord bot designed for Final Fantasy XIV (FFXIV) players who want to analyze raid performance using FFLogs data. With two powerful slash commands, this bot fetches player rankings and parses, organizes wipe and kill data from encounter logs, and presents them in a readable, emoji-enhanced format within Discord.

## Features

- 🔍 **`/fflogs`** — Retrieves a player’s top 5 encounter parses from FFLogs, with kill counts and rank color-coded by performance.
- 📊 **`/logreport`** — Analyzes a full FFLogs encounter link:
  - Displays each boss individually
  - Groups pulls by kills or wipes
  - Shows parse percentages by role (tank, healer, DPS)
  - Adds parse emojis to highlight performance
  - Supports stacked parse grids per kill (up to 8 players shown)

## Setup

### Requirements

- Python 3.8+
- Discord bot token
- FFLogs v2 API credentials

### Installation

```bash
pip install -r requirements.txt
```

### Configuration

Create a `config.json` file in the root directory with the following structure:

```json
{
  "discord_token": "YOUR_DISCORD_BOT_TOKEN",
  "fflogs_client_id": "YOUR_FFLOGS_CLIENT_ID",
  "fflogs_client_secret": "YOUR_FFLOGS_CLIENT_SECRET"
}
```

### Running the Bot

```bash
python DiscordRaidJam.py
```

## Slash Commands

### `/fflogs`

> Usage: `/fflogs "First Last@Server" [region]`

Returns top 5 encounters with rank percent and kill count.

**Example Output:**

```
Asphodelos: The First Circle
🏆 Rank: 95.4% | 🗡️ Kills: 8
```

---

### `/logreport`

> Usage: `/logreport <FFLogs Report Link>`

- Kills and wipes are grouped by boss
- Displays parse performance with emoji and role icons
- Caps visible players per pull to 8
- Ignores partner parses (tank/healer split)

**Example Output:**

```
🔥 Kill | Duration: 142s
🥇 🛡️ Tank Name: 100.0%
💜 💖 Healer Name: 80.5%
🤌 ⚔️ DPS Name: 23.9%

💀 Boss HP: 12.3% | Duration: 155s
```

## FFLogs Parse Emojis

| Percent Range | Emoji |
|---------------|-------|
| 100%          | 🥇    |
| 95–99%        | 🏆    |
| 75–94%        | 💜    |
| 50–74%        | 💙    |
| 25–49%        | 💚    |
| 0–24%         | 🤌    |

## Recent Updates (July 3, 2025)

- 🎯 **Improved Parse Layout** — Parses now stack cleanly and are color-coded per fight
- 🧩 **Partner Parse Filtering** — Tank/healer partner parses ignored to avoid duplicates
- 📎 **FFLogs Profile Link** — Embedded in the `/fflogs` response
- 🔗 **Refactored API Token Handling** — Robust token reuse logic
- ❌ **Portrait Embedding Dropped** — XIVAPI access failed due to private profiles and legal ToS concerns

## Code Snippets

### FFLogs GraphQL Token Fetch

```python
async def get_fflogs_token():
    ...
    url = "https://www.fflogs.com/oauth/token"
    ...
```

### Discord Embed Building

```python
embed = discord.Embed(
    title=f"FFLogs for {char['name']} @ {char['server']['name']} ({region})",
    description=f"[View on FFLogs]({profile_url})",
    color=discord.Color.dark_purple()
)
```

### XIVAPI Portrait Fetch (Deprecated)

```python
# This method was deprecated due to character privacy and FF TOS concerns
async def get_character_portrait(...):
    ...
    return char_data['Character']['Portrait']
```

## License

This project is provided as-is for educational and personal use. Please respect FFLogs and Square Enix terms of service when using the bot in public communities.