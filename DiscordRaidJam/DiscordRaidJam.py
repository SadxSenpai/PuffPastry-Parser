import discord
from discord.ext import commands
from discord import app_commands
import aiohttp
import json
import re
from datetime import datetime

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
              rankings {
                data {
                  fightID
                  encounter {
                    id
                    name
                  }
                  roles {
                    dps {
                      characters {
                        name
                        rankPercent
                      }
                    }
                  }
                }
              }
            }
          }
        }
        '''
        variables = {"code": report_id}
        response = await fetch_fflogs_v2(query, variables, headers)

        if "data" not in response or "reportData" not in response["data"]:
            raise Exception("'data' not in response")

        report = response["data"]["reportData"]["report"]
        fights = report["fights"]
        rankings_data = report.get("rankings", {}).get("data", [])

        encounter_names = {
            r["fightID"]: r["encounter"]["name"]
            for r in rankings_data if "encounter" in r and "name" in r["encounter"]
        }

        player_best_parses = {}
        for r in rankings_data:
            for dps in r.get("roles", {}).get("dps", {}).get("characters", []):
                name = dps["name"]
                rank_percent = dps.get("rankPercent", 0)
                if name not in player_best_parses or player_best_parses[name] < rank_percent:
                    player_best_parses[name] = rank_percent

        # Group fights by encounterID
        encounters = {}
        for fight in fights:
            eid = fight["encounterID"]
            if eid == 0:
                continue  # skip trash pulls
            encounters.setdefault(eid, []).append(fight)

        embed = discord.Embed(title=f"FFLogs Report: {report_id}", color=0xB71C1C)
        for eid, fight_list in encounters.items():
            fight_name = next((r["encounter"]["name"] for r in rankings_data if r["encounter"]["id"] == eid), f"Encounter {eid}")
            kills = sum(1 for f in fight_list if f["kill"])
            wipes = len(fight_list) - kills
            summary = f"✅ Kills: {kills} | ❌ Wipes: {wipes}\n"

            for f in fight_list:
                duration = (f["endTime"] - f["startTime"]) // 1000
                if f["kill"]:
                    status = f"✅ Kill | Duration: {duration}s"
                else:
                    hp = f.get("bossPercentage", 0.0)
                    status = f"❌ Wipe | Boss HP: {hp:.1f}% | Duration: {duration}s"
                summary += f"{status}\n"

            embed.add_field(name=fight_name, value=summary, inline=False)

        if player_best_parses:
            top_parsers = sorted(player_best_parses.items(), key=lambda x: x[1], reverse=True)
            parse_summary = "\n".join([f"{name}: {percent:.2f}%" for name, percent in top_parsers])
            embed.add_field(name="🏆 Best Player Parses", value=parse_summary, inline=False)

        await interaction.followup.send(embed=embed)

    except Exception as e:
        await interaction.followup.send(f"❌ Error retrieving report: `{str(e)}`")

# === Hello/testtoken commands unchanged ===
@tree.command(name="hello", description="Simple test", guild=discord.Object(id=GUILD_ID))
async def hello(interaction: discord.Interaction):
    await interaction.response.send_message("Hello from slash command!")

@tree.command(name="testtoken", description="Test if the bot can acquire an FFLogs OAuth token", guild=discord.Object(id=GUILD_ID))
async def testtoken(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True)
    try:
        await get_fflogs_token()
        if access_token:
            await interaction.followup.send("✅ Token successfully acquired and stored.")
        else:
            await interaction.followup.send("⚠️ No token was returned.")
    except Exception as e:
        await interaction.followup.send(f"❌ Failed to get token:\n`{str(e)}`")

# === Sync commands on bot ready ===
@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")
    guild = discord.Object(id=GUILD_ID)
    commands = await tree.fetch_commands(guild=guild)
    for command in commands:
        tree.remove_command(command.name, type=discord.AppCommandType.chat_input, guild=guild)
    print("🧹 Old slash commands removed.")
    synced = await tree.sync(guild=guild)
    print(f"🔁 Synced {len(synced)} command(s) to guild {GUILD_ID}")

bot.run(DISCORD_TOKEN)