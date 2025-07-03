import discord
from discord.ext import commands
from discord import app_commands
import aiohttp
import json
from datetime import datetime
import asyncio

# === Parse Color Helper ===
def get_parse_color(percent):
    if percent == 100:
        return 0xe5cc80  # Gold
    elif percent >= 95:
        return 0xff8000  # Orange
    elif percent >= 75:
        return 0xa335ee  # Purple
    elif percent >= 50:
        return 0x0070dd  # Blue
    elif percent >= 25:
        return 0x1eff00  # Green
    else:
        return 0x9d9d9d  # Gray

# === Load config ===
with open("config.json") as f:
    config = json.load(f)

DISCORD_TOKEN = config["discord_token"]
FFLOGS_CLIENT_ID = config["fflogs_client_id"]
FFLOGS_CLIENT_SECRET = config["fflogs_client_secret"]
GUILD_ID = 693821560028528680

# === Bot setup ===
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree
access_token = None

# === Get OAuth token from FFLogs ===
async def get_fflogs_token():
    global access_token
    url = "https://www.fflogs.com/oauth/token"
    async with aiohttp.ClientSession() as session:
        async with session.post(
            url,
            data={
                "grant_type": "client_credentials",
                "client_id": FFLOGS_CLIENT_ID,
                "client_secret": FFLOGS_CLIENT_SECRET
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        ) as resp:
            data = await resp.json()
            access_token = data.get("access_token")
            print("✅ FFLogs v2 token acquired.")
    return access_token

# === Fetch FFLogs GraphQL ===
async def fetch_fflogs_v2(query, variables, headers):
    url = "https://www.fflogs.com/api/v2/client"
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json={"query": query, "variables": variables}, headers=headers) as resp:
            return await resp.json()

@tree.command(name="logreport", description="Analyze a FFLogs report link")
@app_commands.describe(link="The FFLogs report link (e.g. https://www.fflogs.com/reports/XXXXX)")
async def logreport(interaction: discord.Interaction, link: str):
    await interaction.response.defer()
    report_id = link.split("/")[-1].split("#")[0]

    try:
        token = await get_fflogs_token()
        headers = {"Authorization": f"Bearer {token}"}

        query = '''
        query($code: String!) {
          reportData {
            report(code: $code) {
              fights {
                id
                startTime
                endTime
                kill
                bossPercentage
                encounterID
              }
              rankings
            }
          }
        }
        '''
        variables = {"code": report_id}
        response = await fetch_fflogs_v2(query, variables, headers)
        report = response["data"]["reportData"]["report"]

        fights = report["fights"]
        rankings = report.get("rankings", {}).get("data", [])

        encounter_map = {}
        kill_map = {}
        wipe_map = {}

        for fight in fights:
            eid = fight["encounterID"]
            if eid == 0:
                continue
            encounter_map.setdefault(eid, {"kills": [], "wipes": []})
            if fight["kill"]:
                encounter_map[eid]["kills"].append(fight)
            else:
                encounter_map[eid]["wipes"].append(fight)

        # Map parses by (encounterID, fightID)
        parse_map = {}
        encounter_names = {}
        for r in rankings:
            enc = r.get("encounter", {})
            eid = enc.get("id")
            ename = enc.get("name", f"Encounter {eid}")
            encounter_names[eid] = ename
            for role in r.get("roles", {}).values():
                for char in role.get("characters", []):
                    fid = char.get("fightID")
                    if fid is None:
                        continue
                    key = (eid, fid)
                    parse_map.setdefault(key, []).append({
                        "name": char["name"],
                        "spec": char.get("spec", "?"),
                        "percent": char.get("rankPercent", 0.0)
                    })

        embed = discord.Embed(
            title=f"FFLogs Report: {report_id}",
            color=0xB71C1C,
            description=f"[🔗 View on Website](https://www.fflogs.com/reports/{report_id})\nClick the link to view the full report online."
        )

        for eid, data in encounter_map.items():
            ename = encounter_names.get(eid, f"Encounter {eid}")
            summary = f"__**{ename}**__\n\n"

            for fight in data["kills"]:
                fid = fight["id"]
                duration = (fight["endTime"] - fight["startTime"]) // 1000
                summary += f"🔥 **Kill** | Duration: {duration}s\n"

                parses = parse_map.get((eid, fid), [])
                if parses:
                    lines = {}
                    for p in parses:
                        key = f"{p['name']} ({p['spec']})"
                        lines.setdefault(key, []).append(p["percent"])
                    summary += "```\n"
                    for player, percents in lines.items():
                        percents_str = ", ".join(f"{x:.1f}%" for x in percents)
                        summary += f"{player}: {percents_str}\n"
                    summary += "```\n"

            if data["wipes"]:
                summary += "**Wipes**\n"
                for wipe in data["wipes"]:
                    hp = wipe.get("bossPercentage", 100)
                    duration = (wipe["endTime"] - wipe["startTime"]) // 1000
                    summary += f"💀 Boss HP: {hp:.1f}% | Duration: {duration}s\n"

            embed.add_field(name=ename, value=summary, inline=False)

        await interaction.followup.send(embed=embed)

    except Exception as e:
        await interaction.followup.send(f"❌ Error: `{str(e)}`")


# === /fflogs Command ===
@tree.command(name="fflogs", description="Get FFLogs data for a FFXIV character")
async def fflogs(
    interaction: discord.Interaction,
    character: str,  # expects "Name Surname@Server"
    region: str = "EU"
):
    await interaction.response.defer()
    try:
        full_name, server = character.split("@")
        first_name, last_name = full_name.strip().split(" ", 1)
        name = f"{first_name} {last_name}"
    except ValueError:
        await interaction.followup.send("\u274c Please format character as `Name Surname@Server`.")
        return

    await get_fflogs_token()

    query = """
    query($name: String!, $server: String!, $region: String!) {
      characterData {
        character(name: $name, serverSlug: $server, serverRegion: $region) {
          name
          server { name }
          zoneRankings
        }
      }
    }
    """

    variables = {"name": name, "server": server, "region": region}
    try:
        headers = {"Authorization": f"Bearer {access_token}"}
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://www.fflogs.com/api/v2/client",
                json={"query": query, "variables": variables},
                headers=headers
            ) as resp:
                data = await resp.json()

        char = data["data"]["characterData"]["character"]
        rankings = char["zoneRankings"]["rankings"]

        embed = discord.Embed(
            title=f"FFLogs for {char['name']} @ {char['server']['name']} ({region})",
            color=discord.Color.dark_purple()
        )
        for log in rankings[:5]:
            color_hex = get_parse_color(log['rankPercent'])
            emoji = "\U0001f947" if log['rankPercent'] == 100 else ""
            embed.add_field(
                name=f"{emoji} {log['encounter']['name']}",
                value=f"Rank: `{log['rankPercent']}%` | Kills: `{log['totalKills']}`",
                inline=False
            )

        await interaction.followup.send(embed=embed)
    except Exception as e:
        print("\u274c Log fetch error:", e)
        await interaction.followup.send(f"\u274c Failed to retrieve logs:\n`{e}`")

# === Sync commands on bot ready ===
@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")

    guild = discord.Object(id=GUILD_ID)

    # Sync guild and global commands
    guild_synced = await tree.sync(guild=guild)
    print(f"🔁 Synced {len(guild_synced)} guild command(s):")
    for cmd in guild_synced:
        print(f"   - /{cmd.name} ({cmd.description})")

    global_synced = await tree.sync()
    print(f"🌍 Synced {len(global_synced)} global command(s):")
    for cmd in global_synced:
        print(f"   - /{cmd.name} ({cmd.description})")

bot.run(DISCORD_TOKEN)