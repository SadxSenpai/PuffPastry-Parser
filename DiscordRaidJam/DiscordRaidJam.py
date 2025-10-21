import discord
from discord.ext import commands
from discord import app_commands
import aiohttp
import json
import asyncio
from urllib.parse import quote, urlparse, parse_qs
import requests
import os
from dataclasses import dataclass, asdict
from typing import List, Dict, Optional

# === Load config ===
# config.json       = Live
# config_test.json  = Testing environment
with open("config.json") as f:
    config = json.load(f)

DISCORD_TOKEN = config["discord_token"]
FFLOGS_CLIENT_ID = config["fflogs_client_id"]
FFLOGS_CLIENT_SECRET = config["fflogs_client_secret"]
GUILD_ID = 693821560028528680

# === Bot setup (enable members intent for role toggling) ===
intents = discord.Intents.default()
intents.members = True  # needed for role assignment
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree
access_token = None

# =========================
# FFLOGS
# =========================
async def get_fflogs_token():
    # Guard if credentials are commented out
    if 'FFLOGS_CLIENT_ID' not in globals() or 'FFLOGS_CLIENT_SECRET' not in globals():
        raise RuntimeError("FFLogs credentials not configured.")
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

async def fetch_fflogs_v2(query, variables, headers):
    url = "https://www.fflogs.com/api/v2/client"
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json={"query": query, "variables": variables}, headers=headers) as resp:
            return await resp.json()

# === Add the paginator for embeds ===
class EncounterPaginator(discord.ui.View):
    def __init__(self, embeds, encounter_names):
        super().__init__(timeout=300)
        self.embeds = embeds
        self.encounter_ids = list(encounter_names.keys())
        self.encounter_names = encounter_names
        self.index = 0

        for i, eid in enumerate(self.encounter_ids[:25]):  # Discord limit
            label = encounter_names[eid][:20]  # Truncate for button space
            self.add_item(self.EncounterButton(i, label, self))

    async def update(self, interaction: discord.Interaction):
        embed = self.embeds[self.index]
        embed.set_footer(text=f"Page {self.index + 1} / {len(self.embeds)}")
        await interaction.response.edit_message(embed=embed, view=self)

    class EncounterButton(discord.ui.Button):
        def __init__(self, index, label, parent_view):
            super().__init__(label=label, style=discord.ButtonStyle.secondary)
            self.index = index
            self.parent_view = parent_view

        async def callback(self, interaction: discord.Interaction):
            self.parent_view.index = self.index
            await self.parent_view.update(interaction)

# =========================
# Reaction Role Panels
# =========================
DATA_FILE = "rr_panels.json"

@dataclass
class PanelConfig:
    guild_id: int
    channel_id: int
    message_id: int
    title: str
    role_ids: List[int]
    custom_id: str
    body: str = ""  # editable message text shown on the panel

def load_all_panels() -> Dict[str, PanelConfig]:
    if not os.path.exists(DATA_FILE):
        return {}
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        raw = json.load(f)
    panels: Dict[str, PanelConfig] = {}
    for k, v in raw.items():
        panels[k] = PanelConfig(**v)
    return panels

def save_all_panels(panels: Dict[str, PanelConfig]) -> None:
    raw = {k: asdict(v) for k, v in panels.items()}
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(raw, f, indent=2)

PANELS: Dict[str, PanelConfig] = {}

class RoleToggleSelect(discord.ui.Select):
    def __init__(self, panel: PanelConfig, guild: discord.Guild):
        self.panel = panel
        self.guild = guild
        options = []
        for rid in panel.role_ids:
            role = guild.get_role(rid)
            if role:
                options.append(discord.SelectOption(label=role.name, value=str(role.id), description=f"Toggle {role.name}"))
        if not options:
            options = [discord.SelectOption(label="No roles configured", value="none", description="Ask an admin to reconfigure")]
        super().__init__(
            placeholder="Pick roles to toggle…",
            min_values=0,
            max_values=min(len(options), 25) if options and options[0].value != "none" else 1,
            options=options,
            custom_id=panel.custom_id,
        )

    async def callback(self, interaction: discord.Interaction):
        if not self.panel.role_ids:
            return await interaction.response.send_message("This panel has no roles configured.", ephemeral=True)
        member = interaction.user if isinstance(interaction.user, discord.Member) else interaction.guild.get_member(interaction.user.id)
        if not isinstance(member, discord.Member):
            return await interaction.response.send_message("Could not resolve your member object.", ephemeral=True)

        selected_ids = set(int(v) for v in self.values) if self.values else set()
        available_ids = set(self.panel.role_ids)

        to_add, to_remove = [], []
        for rid in available_ids:
            role = interaction.guild.get_role(rid)
            if not role:
                continue
            if rid in selected_ids:
                if role not in member.roles:
                    to_add.append(role)
            else:
                if role in member.roles:
                    to_remove.append(role)

        added_names, removed_names = [], []
        reason = f"Reaction roles panel {self.panel.message_id}"

        if to_add:
            try:
                await member.add_roles(*to_add, reason=reason)
                added_names = [r.name for r in to_add]
            except discord.Forbidden:
                pass
        if to_remove:
            try:
                await member.remove_roles(*to_remove, reason=reason)
                removed_names = [r.name for r in to_remove]
            except discord.Forbidden:
                pass

        msg_bits = []
        if added_names:
            msg_bits.append(f"Added: {', '.join(added_names)}")
        if removed_names:
            msg_bits.append(f"Removed: {', '.join(removed_names)}")
        await interaction.response.send_message(" • ".join(msg_bits) if msg_bits else "No changes.", ephemeral=True)

class RolePanelView(discord.ui.View):
    def __init__(self, panel: PanelConfig, guild: discord.Guild):
        super().__init__(timeout=None)
        self.add_item(RoleToggleSelect(panel, guild))

# ---------- Setup (create) flow with editable message ----------
class AdminRolePicker(discord.ui.View):
    def __init__(self, panel_id: str, channel: discord.TextChannel, title: str):
        super().__init__(timeout=300)
        self.panel_id = panel_id
        self.channel = channel
        self.title = title
        self.add_item(_AdminRoleSelect(self))

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="❎ Setup canceled.", view=None)

class PanelSetupMessageModal(discord.ui.Modal):
    def __init__(self, parent: "AdminRolePicker", role_ids: List[int]):
        super().__init__(title="Reaction Roles: Panel Message")
        self.parent = parent
        self.role_ids = role_ids
        # Default helper text; admin can change
        default_text = "Use the dropdown below to add/remove the selected roles."
        self.body_input = discord.ui.TextInput(
            label="Panel message",
            style=discord.TextStyle.paragraph,
            default=default_text,
            max_length=4000,
            required=False,
            placeholder="Describe what these roles mean, rules, etc."
        )
        self.add_item(self.body_input)

    async def on_submit(self, interaction: discord.Interaction):
        body_text = (self.body_input.value or "").strip()
        custom_id = f"rr_panel:{interaction.guild_id}:{self.parent.panel_id}"

        # 1) Send the panel message first to obtain its message_id
        embed = discord.Embed(
            title=self.parent.title,
            description=body_text,
            color=discord.Color.blurple()
        )
        msg = await self.parent.channel.send(embed=embed)

        # 2) Save config
        panel = PanelConfig(
            guild_id=interaction.guild_id,
            channel_id=self.parent.channel.id,
            message_id=msg.id,
            title=self.parent.title,
            role_ids=list(self.role_ids),
            custom_id=custom_id,
            body=body_text
        )
        PANELS[self.parent.panel_id] = panel
        save_all_panels(PANELS)

        # 3) Attach the interactive view
        await msg.edit(view=RolePanelView(panel, interaction.guild))

        await interaction.response.send_message(
            content=f"✅ Panel created in {self.parent.channel.mention}.",
            ephemeral=True
        )

class _AdminRoleSelect(discord.ui.RoleSelect):
    def __init__(self, parent: AdminRolePicker):
        super().__init__(
            placeholder="Select up to 25 roles to include…",
            min_values=1,
            max_values=25
        )
        self.parent = parent

    async def callback(self, interaction: discord.Interaction):
        roles = [r for r in self.values if isinstance(r, discord.Role)]
        role_ids = [r.id for r in roles]
        # Open modal to collect editable message before creating the panel
        await interaction.response.send_modal(PanelSetupMessageModal(self.parent, role_ids))

# ---------- Edit flow (roles and message) ----------
class EditRolePicker(discord.ui.View):
    def __init__(self, panel: PanelConfig, guild: discord.Guild, channel: discord.TextChannel):
        super().__init__(timeout=300)
        self.panel = panel
        self.guild = guild
        self.channel = channel
        self.add_item(_EditRoleSelect(self))

    @discord.ui.button(label="Edit Message", style=discord.ButtonStyle.primary)
    async def edit_message(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(PanelEditMessageModal(self))

    @discord.ui.button(label="Close", style=discord.ButtonStyle.secondary)
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="✅ Editor closed.", view=None)

class _EditRoleSelect(discord.ui.RoleSelect):
    def __init__(self, parent: EditRolePicker):
        super().__init__(
            placeholder="Update roles in this panel…",
            min_values=1,
            max_values=25
        )
        self.parent = parent

    async def callback(self, interaction: discord.Interaction):
        roles = [r for r in self.values if isinstance(r, discord.Role)]
        self.parent.panel.role_ids = [r.id for r in roles]
        save_all_panels(PANELS)

        # Update the existing message's view
        channel = self.parent.guild.get_channel(self.parent.panel.channel_id) or await self.parent.guild.fetch_channel(self.parent.panel.channel_id)
        try:
            msg = await channel.fetch_message(self.parent.panel.message_id)
            await msg.edit(view=RolePanelView(self.parent.panel, self.parent.guild))
        except Exception:
            pass

        await interaction.response.send_message(content="✅ Roles updated for panel.", ephemeral=True)

class PanelEditMessageModal(discord.ui.Modal):
    def __init__(self, parent: EditRolePicker):
        super().__init__(title="Edit Panel Message")
        self.parent = parent
        self.body_input = discord.ui.TextInput(
            label="Panel message",
            style=discord.TextStyle.paragraph,
            default=parent.panel.body or "",
            max_length=4000,
            required=False
        )
        self.add_item(self.body_input)

    async def on_submit(self, interaction: discord.Interaction):
        new_body = (self.body_input.value or "").strip()
        self.parent.panel.body = new_body
        save_all_panels(PANELS)

        # Fetch and edit the original message's embed
        channel = self.parent.guild.get_channel(self.parent.panel.channel_id) or await self.parent.guild.fetch_channel(self.parent.panel.channel_id)
        try:
            msg = await channel.fetch_message(self.parent.panel.message_id)
            # Preserve title; update description
            new_embed = discord.Embed(
                title=self.parent.panel.title,
                description=new_body,
                color=discord.Color.blurple()
            )
            await msg.edit(embed=new_embed)
        except Exception:
            pass

        await interaction.response.send_message(content="✅ Panel message updated.", ephemeral=True)

@tree.command(name="rr_setup", description="Create a reaction-roles dropdown panel (admin only).")
@app_commands.default_permissions(manage_guild=True)
@app_commands.describe(channel="Channel to post the panel in", title="Panel title")
async def rr_setup(interaction: discord.Interaction, channel: discord.TextChannel, title: str):
    if not interaction.user.guild_permissions.manage_guild:
        return await interaction.response.send_message("You need Manage Server permission.", ephemeral=True)
    panel_id = f"{interaction.guild_id}-{os.urandom(4).hex()}"
    view = AdminRolePicker(panel_id, channel, title)
    await interaction.response.send_message("Pick the roles to include in this panel:", view=view, ephemeral=True)

@tree.command(name="rr_edit", description="Edit roles of an existing reaction-roles panel (admin only).")
@app_commands.default_permissions(manage_guild=True)
@app_commands.describe(message_id="Message ID of the panel message")
async def rr_edit(interaction: discord.Interaction, message_id: str):
    if not interaction.user.guild_permissions.manage_guild:
        return await interaction.response.send_message("You need Manage Server permission.", ephemeral=True)
    target: Optional[PanelConfig] = None
    for p in PANELS.values():
        if str(p.message_id) == message_id and p.guild_id == interaction.guild_id:
            target = p
            break
    if not target:
        return await interaction.response.send_message("Panel not found for this guild.", ephemeral=True)

    ch = interaction.guild.get_channel(target.channel_id) or await interaction.guild.fetch_channel(target.channel_id)
    view = EditRolePicker(target, interaction.guild, ch)
    await interaction.response.send_message("Use the controls below to edit this panel (roles or message):", view=view, ephemeral=True)

@tree.command(name="rr_delete", description="Delete a reaction-roles panel (admin only).")
@app_commands.default_permissions(manage_guild=True)
@app_commands.describe(message_id="Message ID of the panel message")
async def rr_delete(interaction: discord.Interaction, message_id: str):
    if not interaction.user.guild_permissions.manage_guild:
        return await interaction.response.send_message("You need Manage Server permission.", ephemeral=True)
    panel_key = None
    for k, p in PANELS.items():
        if str(p.message_id) == message_id and p.guild_id == interaction.guild_id:
            panel_key = k
            break
    if not panel_key:
        return await interaction.response.send_message("Panel not found for this guild.", ephemeral=True)
    panel = PANELS.pop(panel_key)
    save_all_panels(PANELS)
    try:
        ch = interaction.guild.get_channel(panel.channel_id) or await interaction.guild.fetch_channel(panel.channel_id)
        m = await ch.fetch_message(panel.message_id)
        await m.edit(view=None, content="(Reaction-roles panel removed by an admin.)")
    except Exception:
        pass
    await interaction.response.send_message("🗑️ Panel deleted.", ephemeral=True)

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
            if eid not in encounter_names:
                encounter_names[eid] = f"Encounter {eid}"
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
                    if "name_2" in char:
                        continue
                    name = char.get("name")
                    percent = char.get("rankPercent", 0)
                    parse_map.setdefault((eid, fid), []).append({
                        "name": name,
                        "role": role_type,
                        "percent": percent
                    })
        boss_embeds = []
        for eid, ename in encounter_names.items():
            if eid not in encounter_kills and eid not in encounter_wipes:
                continue
            summary = ""
            for kill in encounter_kills.get(eid, []):
                fid = kill["id"]
                duration = (kill["endTime"] - kill["startTime"]) // 1000
                summary += f"🔥 **Kill** | Duration: {duration}s\n"
                parses = parse_map.get((eid, fid), [])[:8]
                if parses:
                    summary += "```\n"
                    for p in parses:
                        icon = {"tanks": "🛡️", "healers": "💖", "dps": "⚔️"}.get(p["role"], "❔")
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
            embed = discord.Embed(
                title=f"{ename} – FFLogs Report: {report_id}",
                description=summary[:4000],
                color=0xB71C1C
            )
            embed.add_field(
                name="🔗 View on Website",
                value=f"[Open full report](https://www.fflogs.com/reports/{report_id})",
                inline=False
            )
            boss_embeds.append(embed)
        await interaction.followup.send(
            embed=boss_embeds[0],
            view=EncounterPaginator(boss_embeds, encounter_names)
        )
    except Exception as e:
        await interaction.followup.send(f"❌ Error retrieving report: `{str(e)}`")

# === /fflogs Command ===
@tree.command(name="fflogs", description="Get FFLogs data for a FFXIV character")
async def fflogs(
    interaction: discord.Interaction,
    character: str,
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
    try:
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
                return "Unkilled"
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
                name=encounter,
                value=f"{emoji} Rank: **{percent_display}** | 🗡️ Kills: `{kills}`",
                inline=False
            )
        await interaction.followup.send(embed=embed)
    except Exception as e:
        print("❌ Log fetch error:", e)
        await interaction.followup.send(f"❌ Failed to retrieve logs:\n`{e}`")

# === /dancepartner Command ===
@tree.command(name="dancepartner", description="Suggest the best Dance Partner based on a FFLogs report.", guild=discord.Object(id=GUILD_ID))
@app_commands.describe(link="The FFLogs report link (e.g. https://www.fflogs.com/reports/XXXXX?fight=Y)")
async def dancepartner(interaction: discord.Interaction, link: str):
    await interaction.response.defer()
    try:
        parsed = urlparse(link)
        report_id = parsed.path.split("/")[-1]
        fight_id = int(parse_qs(parsed.query).get("fight", [0])[0])
    except Exception as e:
        await interaction.followup.send(f"❌ Invalid FFLogs link format: `{e}`")
        return
    try:
        token = await get_fflogs_token()
        headers = {"Authorization": f"Bearer {token}"}
        query = '''
        query($code: String!, $fight: Int!) {
          reportData {
            report(code: $code) {
              table(dataType: DamageDone, fightIDs: [$fight])
            }
          }
        }'''
        variables = {"code": report_id, "fight": fight_id}
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://www.fflogs.com/api/v2/client",
                json={"query": query, "variables": variables},
                headers=headers
            ) as resp:
                raw = await resp.json()
        if "errors" in raw:
            raise ValueError(raw["errors"][0]["message"])
        table_raw = raw["data"]["reportData"]["report"]["table"]
        if not table_raw:
            raise ValueError("Table data is empty or missing.")
        data = table_raw
        entries = data.get("entries", [])
        total_time = data.get("totalTime", 0) / 1000
        if not entries or total_time == 0:
            raise ValueError("No combat entries or invalid duration.")
    except Exception as e:
        print("❌ Dance Partner error:", e)
        await interaction.followup.send(f"❌ Dance Partner error: Unable to parse entries from FFLogs table\n`{e}`")
        return
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

# === Sync & Restore on ready ===
@bot.event
async def on_ready():
    global PANELS
    # Load & attach persistent reaction-role views
    PANELS = load_all_panels()
    restored = 0
    for panel_id, panel in PANELS.items():
        guild = bot.get_guild(panel.guild_id)
        if guild:
            bot.add_view(RolePanelView(panel, guild))
            restored += 1

    print(f"✅ Logged in as {bot.user} (Restored {restored} reaction-role panels)")
    guild = discord.Object(id=GUILD_ID)
    guild_synced = await tree.sync(guild=guild)
    print(f"🔁 Synced {len(guild_synced)} guild command(s):")
    for cmd in guild_synced:
        print(f"   - /{cmd.name} ({cmd.description})")
    global_synced = await tree.sync()
    print(f"🌍 Synced {len(global_synced)} global command(s):")
    for cmd in global_synced:
        print(f"   - /{cmd.name} ({cmd.description})")

bot.run(DISCORD_TOKEN)