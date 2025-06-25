import discord
from discord.ext import commands
from discord import app_commands
import aiohttp
import json
from datetime import datetime
import asyncio

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

# === /logreport Command ===
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

        # Safely parse rankings JSON
        try:
            rankings_json = report.get("rankings", {})
        except json.JSONDecodeError:
            rankings_json = {}

        # Group fights by encounterID
        encounters = {}
        for fight in fights:
            eid = fight["encounterID"]
            if eid == 0:
                continue  # skip trash pulls
            encounters.setdefault(eid, []).append(fight)

        # Map encounterID to name and gather best parses
        encounter_names = {}
        player_best_parses = {}

        for r in rankings_json.get("data", []):
            enc = r.get("encounter", {})
            eid = enc.get("id")
            ename = enc.get("name", f"Encounter {eid}")
            encounter_names[eid] = ename

        for r in rankings_json.get("data", []):
            roles = r.get("roles", {})
            for role_type in ["tanks", "healers", "dps"]:
                characters = roles.get(role_type, {}).get("characters", [])
                for character in characters:
                    name = character.get("name")
                    rank_percent = character.get("rankPercent", 0)
                    if name and (name not in player_best_parses or player_best_parses[name] < rank_percent):
                        player_best_parses[name] = rank_percent

        # Build embed
        embed = discord.Embed(title=f"FFLogs Report: {report_id}", color=0xB71C1C)
        
        embed.add_field(
        name="🔗 [View on Website](https://www.fflogs.com/reports/{})".format(report_id),
        value="Click the link to view the full report online.",
        inline=False
        )
        
        for eid, fights in encounters.items():
            ename = encounter_names.get(eid, f"Encounter {eid}")
            # Separate kills and wipes
            kills = [f for f in fights if f["kill"]]
            wipes = sorted(
                [f for f in fights if not f["kill"]],
                key=lambda f: f.get("bossPercentage", 100)  # sort by HP left ascending
            )

            summary = f"✅ Kills: {len(kills)} | ❌ Wipes: {len(wipes)}\n"

            for f in kills:
                duration = (f["endTime"] - f["startTime"]) // 1000
                summary += f"✅ Kill | Duration: {duration}s\n"

            for f in wipes:
                duration = (f["endTime"] - f["startTime"]) // 1000
                hp = f.get("bossPercentage", 100)
                summary += f"❌ Wipe | Boss HP: {hp:.1f}% | Duration: {duration}s\n"

            embed.add_field(name=ename, value=summary, inline=False)

        if player_best_parses:
            sorted_parses = sorted(player_best_parses.items(), key=lambda x: x[1], reverse=True)
            parse_text = "\n".join(f"{name}: {percent:.1f}%" for name, percent in sorted_parses)
            embed.add_field(name="🏆 Best DPS Parses", value=parse_text, inline=False)

        await interaction.followup.send(embed=embed)    

    except Exception as e:
        await interaction.followup.send(f"❌ Error retrieving report: `{str(e)}`")

# === /fflogs Command ===
@tree.command(name="fflogs",description="Get FFLogs data for a FFXIV character")
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
        await interaction.followup.send("❌ Please format character as `Name Surname@Server`.")
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
            embed.add_field(
                name=log["encounter"]["name"],
                value=f"Rank: {log['rankPercent']}% | Kills: {log['totalKills']}",
                inline=False
            )
        await interaction.followup.send(embed=embed)
    except Exception as e:
        print("❌ Log fetch error:", e)
        await interaction.followup.send(f"❌ Failed to retrieve logs:\n`{e}`")

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