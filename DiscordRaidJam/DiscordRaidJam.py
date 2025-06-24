import discord
from discord.ext import commands
import aiohttp
import json
import base64

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
access_token = None  # Cached FFLogs OAuth token

# === Get OAuth token from FFLogs ===
async def get_fflogs_token():
    global access_token
    url = "https://www.fflogs.com/oauth/token"
    auth = aiohttp.BasicAuth(FFLOGS_CLIENT_ID, FFLOGS_CLIENT_SECRET)
    async with aiohttp.ClientSession() as session:
        async with session.post(
            url,
            data={"grant_type": "client_credentials"},
            auth=auth
        ) as resp:
            if resp.status == 200:
                data = await resp.json()
                access_token = data["access_token"]
                print("✅ FFLogs v2 token acquired.")
            else:
                text = await resp.text()
                raise Exception(f"Token request failed: {resp.status}, {text}")

# === Query FFLogs v2 GraphQL API ===
async def query_fflogs(query, variables):
    global access_token
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(
            "https://www.fflogs.com/api/v2/client",
            json={"query": query, "variables": variables},
            headers=headers
        ) as resp:
            resp_json = await resp.json()
            if "errors" in resp_json:
                raise Exception(resp_json["errors"][0].get("message", resp_json["errors"]))
            if "data" not in resp_json:
                raise Exception(f"Unexpected response structure: {resp_json}")
            return resp_json

# === Slash Command: /hello ===
@tree.command(name="hello", description="Simple test", guild=discord.Object(id=GUILD_ID))
async def hello(interaction: discord.Interaction):
    await interaction.response.send_message("Hello from slash command!")

# === Slash Command: /testtoken ===
@tree.command(
    name="testtoken",
    description="Test if the bot can acquire an FFLogs OAuth token",
    guild=discord.Object(id=GUILD_ID)
)
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

# === Slash Command: /fflogs ===
@tree.command(
    name="fflogs",
    description="Get FFLogs data for a FFXIV character",
    guild=discord.Object(id=GUILD_ID)
)
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
        data = await query_fflogs(query, variables)
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

# === Sync commands on ready ===
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

# === Run bot ===
bot.run(DISCORD_TOKEN)