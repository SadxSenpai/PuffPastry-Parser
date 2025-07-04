import discord
from discord.ext import commands
from discord import app_commands
import aiohttp
import json
import asyncio
from urllib.parse import quote, urlparse, parse_qs
import requests

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

        try:
            rankings_json = report.get("rankings", {})
        except json.JSONDecodeError:
            rankings_json = {}

        encounter_names = {}
        encounter_kills = {}
        encounter_wipes = {}
        parse_map = {}

        for r in rankings_json.get("data", []):
            enc = r.get("encounter", {})
            eid = enc.get("id")
            ename = enc.get("name", f"Encounter {eid}")
            encounter_names[eid] = ename

        for fight in fights:
            eid = fight["encounterID"]
            if eid == 0:
                continue
            if fight["kill"]:
                encounter_kills.setdefault(eid, []).append(fight)
            else:
                encounter_wipes.setdefault(eid, []).append(fight)

        for r in rankings_json.get("data", []):
            eid = r.get("encounter", {}).get("id")
            fid = r.get("fightID")
            if eid is None or fid is None:
                continue

            roles = r.get("roles", {})
            for role_type in ["tanks", "healers", "dps"]:
                characters = roles.get(role_type, {}).get("characters", [])
                for char in characters:
                    # Ignore partner parses by skipping duplicates with name_2
                    if "name_2" in char:
                        continue
                    name = char.get("name")
                    percent = char.get("rankPercent", 0)
                    parse_map.setdefault((eid, fid), []).append({
                        "name": name,
                        "role": role_type,
                        "percent": percent
                    })

        embed = discord.Embed(title=f"FFLogs Report: {report_id}", color=0xB71C1C)
        embed.add_field(
            name="🔗 [View on Website](https://www.fflogs.com/reports/{})".format(report_id),
            value="Click the link to view the full report online.",
            inline=False
        )

        for eid, ename in encounter_names.items():
            if eid not in encounter_kills and eid not in encounter_wipes:
                continue

            summary = ""

            for kill in encounter_kills.get(eid, []):
                fid = kill["id"]
                duration = (kill["endTime"] - kill["startTime"]) // 1000
                summary += f"🔥 **Kill** | Duration: {duration}s\n"

                parses = parse_map.get((eid, fid), [])[:8]  # Limit to 8 players per fight

                if parses:
                    summary += "```\n"
                    for p in parses:
                        icon = {
                            "tanks": "🛡️",
                            "healers": "💖",
                            "dps": "⚔️"
                        }.get(p["role"], "❔")

                        percent = p["percent"]
                        rank_emoji = (
                            "🥇" if percent == 100 else
                            "🏆" if percent >= 95 else
                            "💜" if percent >= 75 else
                            "💙" if percent >= 50 else
                            "💚" if percent >= 25 else
                            "🤌"
                        )
                        summary += f"{rank_emoji} {icon} {p['name']}: {percent:.1f}%\n"
                    summary += "```\n"

            wipes = encounter_wipes.get(eid, [])
            if wipes:
                summary += f"**Wipes**\n"
                for wipe in wipes:
                    duration = (wipe["endTime"] - wipe["startTime"]) // 1000
                    hp = wipe.get("bossPercentage", 100)
                    summary += f"💀 Boss HP: {hp:.1f}% | Duration: {duration}s\n"

            embed.add_field(name=ename, value=summary, inline=False)

        await interaction.followup.send(embed=embed)

    except Exception as e:
        await interaction.followup.send(f"\u274c Error retrieving report: `{str(e)}`")

## === /fflogs Command ===
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

        encoded_name = quote(char["name"])
        profile_url = f"https://www.fflogs.com/character/{region}/{char['server']['name']}/{encoded_name}"

        embed = discord.Embed(
            title=f"FFLogs for {char['name']} @ {char['server']['name']} ({region})",
            description=f"[View on FFLogs]({profile_url})",
            color=discord.Color.dark_purple()
        )


        def parse_emoji(percent):
            if percent is None:
                return "Unkilled"  # default for unknown rank
            return (
                "🥇" if percent == 100 else
                "🏆" if percent >= 95 else
                "💜" if percent >= 75 else
                "💙" if percent >= 50 else
                "💚" if percent >= 25 else
                "🤌"
            )

        for log in rankings[:5]:
            percent = log.get('rankPercent')
            emoji = parse_emoji(percent)
            percent_display = f"{percent:.2f}%" if percent is not None else "N/A"
            encounter = log['encounter']['name']
            kills = log.get('totalKills', 0)
            embed.add_field(
                name=f"{encounter}",
                value=f"{emoji} Rank: **{percent_display}** | 🗡️ Kills: `{kills}`",
                inline=False
            )

        await interaction.followup.send(embed=embed)
    except Exception as e:
        print("\u274c Log fetch error:", e)
        await interaction.followup.send(f"\u274c Failed to retrieve logs:\n`{e}`")

# === /dancepartner Command ===
@tree.command(name="dancepartner", description="Suggest the best Dance Partner based on a FFLogs report.")
@app_commands.describe(link="The FFLogs report link (e.g. https://www.fflogs.com/reports/XXXXX?fight=Y)")
async def dancepartner(interaction: discord.Interaction, link: str):
    await interaction.response.defer()

    # Extract report ID and fight ID from the URL
    try:
        parsed = urlparse(link)
        report_id = parsed.path.split("/")[-1]
        fight_id = int(parse_qs(parsed.query).get("fight", [0])[0])
    except Exception as e:
        await interaction.followup.send(f"❌ Invalid FFLogs link format: `{e}`")
        return

    # Get FFLogs token
    token = await get_fflogs_token()
    headers = {"Authorization": f"Bearer {token}"}

    # Query FFLogs
    query = '''
    query($code: String!, $fight: Int!) {
      reportData {
        report(code: $code) {
          table(dataType: DamageDone, fightIDs: [$fight])
        }
      }
    }'''
    variables = {"code": report_id, "fight": fight_id}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://www.fflogs.com/api/v2/client",
                json={"query": query, "variables": variables},
                headers=headers
            ) as resp:
                raw = await resp.json()
        
        # Check for FFLogs API errors
        if "errors" in raw:
            raise ValueError(raw["errors"][0]["message"])

        table_raw = raw["data"]["reportData"]["report"]["table"]
        if not table_raw:
            raise ValueError("Table data is empty or missing.")

        # Parse the raw JSON string inside the `table` field
        data = table_raw
        entries = data.get("entries", [])
        total_time = data.get("totalTime", 0) / 1000
        if not entries or total_time == 0:
            raise ValueError("No combat entries or invalid duration.")
    except Exception as e:
        print("❌ Dance Partner error:", e)
        await interaction.followup.send(f"❌ Dance Partner error: Unable to parse entries from FFLogs table\n`{e}`")
        return

    # Calculate RDPS from dancer buffs
    buff_names = ["Standard Finish", "Devilment", "Technical Finish"]
    results = []
    for player in entries:
        name = player.get("name")
        job = player.get("type")
        taken = player.get("taken", [])
        buffs = {b["name"]: b["total"] for b in taken if b["name"] in buff_names}
        total = sum(buffs.values())
        rdps = round(total / total_time, 2) if total_time else 0
        results.append({
            "name": name,
            "job": job,
            "standard": buffs.get("Standard Finish", 0),
            "devilment": buffs.get("Devilment", 0),
            "esprit": buffs.get("Technical Finish", 0),
            "total": total,
            "rdps": rdps
        })

    results = sorted(results, key=lambda r: r["rdps"], reverse=True)
    top = results[0]["rdps"] if results else 0

    def fmt(v): return f"{v:,.2f}" if isinstance(v, float) else f"{v:,}"

    lines = [
        f"{'Name':<20} | {'Job':<12} | {'Standard':>10} | {'Devilment':>10} | {'Esprit':>10} | {'Total':>10} | {'RDPS':>8}",
        "-" * 95
    ]
    for row in results:
        hl = "**" if row["rdps"] == top else ""
        lines.append(
            f"{hl}{row['name']:<20} | {row['job']:<12} | {fmt(row['standard']):>10} | {fmt(row['devilment']):>10} | {fmt(row['esprit']):>10} | {fmt(row['total']):>10} | {fmt(row['rdps']):>8}{hl}"
        )

    embed = discord.Embed(
        title="Dance Partner RDPS Gains",
        description="```\n" + "\n".join(lines) + "\n```",
        color=discord.Color.purple()
    )
    embed.set_footer(text="Source: FFLogs (DamageDone table)")
    await interaction.followup.send(embed=embed)

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