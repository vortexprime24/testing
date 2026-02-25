from discord.ext import commands
import discord
import asyncio
import io
import os
import time
import urllib.request

from PIL import Image, ImageDraw, ImageFont

from cogs.ipc import call_backend
from cogs.config import MAIN_GUILD_ID, MOD_ROLE_ID, ADMIN_ROLE_ID, OWNER_ROLE_ID

FOOTER_TEXT = "FlorrMobNotify • Administration Action"
FOOTER_ICON = "https://mobs.ashish.top/logo.png"

# ── Font ─────────────────────────────────────────────────────────────────────
# Ubuntu Sans is requested; falls back to Lato or PIL default at runtime.
_FONT_PATH = "/tmp/UbuntuSans-Regular.ttf"
_FONT_URLS = [
    "https://fonts.gstatic.com/s/ubuntusans/v3/co3WmWZevGxW-FMO1EuSvHt_UdXt4OhQmJE5RFKH4KI7.ttf",
]
_FONT_FALLBACKS = [
    "/usr/share/fonts/truetype/ubuntu/Ubuntu-R.ttf",
    "/usr/share/fonts/truetype/lato/Lato-Regular.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]
_FONT_CACHE: dict[int, ImageFont.ImageFont] = {}


def _load_font(size: int) -> ImageFont.ImageFont:
    if size in _FONT_CACHE:
        return _FONT_CACHE[size]
    if not os.path.exists(_FONT_PATH):
        for url in _FONT_URLS:
            try:
                urllib.request.urlretrieve(url, _FONT_PATH)
                break
            except Exception:
                continue
    for path in [_FONT_PATH, *_FONT_FALLBACKS]:
        if os.path.exists(path):
            try:
                font = ImageFont.truetype(path, size)
                _FONT_CACHE[size] = font
                return font
            except Exception:
                continue
    font = ImageFont.load_default()
    _FONT_CACHE[size] = font
    return font


# ── Graph ─────────────────────────────────────────────────────────────────────
def _generate_client_graph(
    bots: int,
    logged_in: int,
    guests: int,
    anonymous: int,
) -> io.BytesIO:
    """Draw a polished single stacked bar-graph and return it as a PNG BytesIO.

    Segments (left → right): Bots (blue) · Logged In (green) · Guests (slate) · Anonymous (red)
    """
    W       = 600
    BAR_H   = 52
    PAD     = 22
    RADIUS  = 11
    LGND_H  = 34   # legend row height

    BG        = (14,  16,  22)   # near-black canvas
    TRACK     = (28,  31,  44)   # bar background

    COL_BOT   = (59,  130, 246)  # vivid blue  – bots
    COL_LOGIN = (34,  197,  94)  # emerald     – logged-in
    COL_GUEST = (100, 116, 139)  # slate       – guests
    COL_ANON  = (239,  68,  68)  # rose red    – anonymous

    SEGMENTS = [
        (bots,      COL_BOT,   "Bots"),
        (logged_in, COL_LOGIN, "Logged In"),
        (guests,    COL_GUEST, "Guests"),
        (anonymous, COL_ANON,  "Anonymous"),
    ]

    _total = max(bots + logged_in + guests + anonymous, 1)
    bar_w  = W - PAD * 2
    H      = PAD + BAR_H + PAD + LGND_H + PAD

    img  = Image.new("RGBA", (W, H), (*BG, 255))
    draw = ImageDraw.Draw(img)

    font_pct  = _load_font(11)
    font_lgnd = _load_font(11)

    y = PAD

    # Background track
    draw.rounded_rectangle(
        [PAD, y, PAD + bar_w, y + BAR_H],
        radius=RADIUS,
        fill=TRACK,
    )

    # Build segment list
    seg_rects: list[tuple[float, float, int, tuple[int, int, int], str]] = []
    x = float(PAD)
    for count, col, label in SEGMENTS:
        seg_w = count / _total * bar_w
        if seg_w >= 1:
            seg_rects.append((x, seg_w, count, col, label))
        x += seg_w

    # Composite all segments through a shared rounded-rect mask so edges stay crisp
    mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [PAD, y, PAD + bar_w, y + BAR_H], radius=RADIUS, fill=255
    )
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ov_draw = ImageDraw.Draw(overlay)
    for sx, sw, _, col, _ in seg_rects:
        ov_draw.rectangle([sx, y, sx + sw, y + BAR_H], fill=(*col, 255))
    bar_layer = Image.composite(overlay, Image.new("RGBA", (W, H), (0, 0, 0, 0)), mask)
    img.paste(bar_layer, mask=bar_layer)

    # Thin separator lines between segments (drawn after paste, inside bar area)
    sep_draw = ImageDraw.Draw(img)
    for sx, sw, _, _, _ in seg_rects[1:]:
        sep_draw.rectangle(
            [int(sx) - 1, y, int(sx) + 1, y + BAR_H],
            fill=(*BG, 160),
        )

    # Percentage labels – rendered with a subtle dark pill inside each segment
    for sx, sw, count, col, label in seg_rects:
        if sw < 38:
            continue
        pct  = count / _total * 100
        txt  = f"{pct:.0f}%"
        bbox = draw.textbbox((0, 0), txt, font=font_pct)
        tw   = bbox[2] - bbox[0]
        th   = bbox[3] - bbox[1]
        tx   = sx + (sw - tw) / 2
        ty   = y  + (BAR_H - th) / 2
        p    = 3
        draw.rounded_rectangle(
            [tx - p, ty - p, tx + tw + p, ty + th + p],
            radius=3,
            fill=(0, 0, 0, 110),
        )
        draw.text((tx, ty), txt, font=font_pct, fill=(255, 255, 255, 228))

    # Legend row
    ly  = PAD + BAR_H + PAD
    lx  = float(PAD)
    dot = 9
    for _, _, count, col, label in seg_rects:
        pct  = count / _total * 100
        item = f"{label}  {pct:.1f}%"
        bbox = draw.textbbox((0, 0), item, font=font_lgnd)
        iw   = bbox[2] - bbox[0]
        draw.ellipse(
            [lx, ly + 3, lx + dot, ly + 3 + dot],
            fill=(*col, 255),
        )
        draw.text((lx + dot + 5, ly), item, font=font_lgnd, fill=(168, 178, 204))
        lx  += dot + 6 + iw + 20

    buf = io.BytesIO()
    img.save(buf, "PNG")
    buf.seek(0)
    return buf


class ClientsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    clients = discord.app_commands.Group(
        name="clients",
        description="Manage connected clients",
        guild_ids=[MAIN_GUILD_ID],
        guild_only=True,
    )

    # ── helpers ───────────────────────────────────────────────────────────────

    def _embed_service_unavailable(self) -> discord.Embed:
        e = discord.Embed(
            title="Service Unavailable",
            description="Could not reach the backend. Please try again in a moment.",
            color=0x8B0000,
            timestamp=discord.utils.utcnow(),
        )
        e.set_footer(text=FOOTER_TEXT, icon_url=FOOTER_ICON)
        return e

    # ───────────────────────── CLIENTS LIST ──────────────────────────────────

    @clients.command(
        name="list",
        description="List all currently connected clients",
    )
    @discord.app_commands.describe(
        page="Page number (1 = first page, 0 = last page)",
    )
    async def clients_list(
        self,
        interaction: discord.Interaction,
        page: int = 1,
    ):
        items = 10
        await interaction.response.defer(ephemeral=True)

        if not any(
            role.id in (ADMIN_ROLE_ID, OWNER_ROLE_ID)
            for role in interaction.user.roles
        ):
            e = discord.Embed(
                title="Permission Denied",
                description="You do not have permission to use this command.",
                color=0x8B0000,
                timestamp=discord.utils.utcnow(),
            )
            e.set_footer(text="FlorrMobNotify • Moderation Action", icon_url=FOOTER_ICON)
            await interaction.followup.send(embed=e, ephemeral=True)
            return

        try:
            result = await asyncio.wait_for(
                call_backend({"type": "list_clients"}),
                timeout=10,
            )
        except Exception:
            await interaction.followup.send(
                embed=self._embed_service_unavailable(), ephemeral=True
            )
            return

        if not result.get("ok"):
            await interaction.followup.send(
                embed=self._embed_service_unavailable(), ephemeral=True
            )
            return

        clients_data = result.get("clients", [])
        clients_data = sorted(
            clients_data,
            key=lambda c: (
                c.get("secret_type") != 1,       # users first
                -int(c.get("last_seen", 0)),      # newest activity first
            ),
        )

        now   = int(time.time())
        total = len(clients_data)

        if total == 0:
            e = discord.Embed(
                title="Connected Clients",
                description="No clients are currently connected.",
                color=0xB09C3E,
                timestamp=discord.utils.utcnow(),
            )
            e.set_footer(text=FOOTER_TEXT, icon_url=FOOTER_ICON)
            await interaction.followup.send(embed=e, ephemeral=True)
            return

        # Pagination
        items = max(1, min(items, 25))
        pages = (total + items - 1) // items

        requested_page = page
        if page == 0:
            page = pages
        elif page < 0:
            page = pages + page

        if page < 1 or page > pages:
            e = discord.Embed(
                title="Page Does Not Exist",
                description=(
                    f"Requested page **{requested_page}** is out of range.\n\n"
                    f"• Total clients: **{total}**\n"
                    f"• Items per page: **{items}**\n"
                    f"• Total pages: **{pages}**"
                ),
                color=0x8B0000,
                timestamp=discord.utils.utcnow(),
            )
            e.set_footer(text=FOOTER_TEXT, icon_url=FOOTER_ICON)
            await interaction.followup.send(embed=e, ephemeral=True)
            return

        page_index  = page - 1
        start       = page_index * items
        end         = min(start + items, total)
        page_clients = clients_data[start:end]

        user_roles = (
            [role.id for role in interaction.user.roles]
            if hasattr(interaction.user, "roles")
            else []
        )

        lines = []
        for c in page_clients:
            ip              = c.get("ip", "unknown")
            ua              = c.get("user_agent", "unknown")
            connected_at    = c.get("connected_at")
            last_seen       = c.get("last_seen")
            last_heartbeat  = c.get("last_heartbeat")
            secret_raw      = c.get("secret_type")
            secret_type     = (
                "Bot" if secret_raw == 0
                else "User" if secret_raw == 1
                else "Unknown"
            )
            logged_in = c.get("logged_in", False)

            display_ua = ua
            display_ip = ip
            if OWNER_ROLE_ID not in user_roles:
                display_ua = "(hidden)"
                display_ip = "(hidden)"

            base = [
                f"**`{display_ip}`**",
                f"• Agent: `{display_ua}`",
                f"• Secret: `{secret_type}`",
                f"• Logged In: `{logged_in}`",
            ]

            if connected_at:
                base.append(f"• Connected: <t:{connected_at}:R>")
            if last_seen:
                base.append(f"• Last Seen: <t:{last_seen}:R>")
            if last_heartbeat:
                base.append(f"• Heartbeat: <t:{last_heartbeat}:R>")

            lines.append("\n".join(base))

        description = "\n\n".join(lines)
        if len(description) > 4000:
            description = description[:3990] + "\n…"

        e = discord.Embed(
            title=f"Connected Clients — Page {page}/{pages}",
            description=description,
            color=0x2563EB,
            timestamp=discord.utils.utcnow(),
        )
        e.set_footer(
            text=f"{FOOTER_TEXT} • Showing {start+1}–{end} of {total}",
            icon_url=FOOTER_ICON,
        )
        await interaction.followup.send(embed=e, ephemeral=True)

    # ───────────────────────── CLIENTS COUNT ─────────────────────────────────

    @clients.command(
        name="count",
        description="Show a breakdown of connected clients with a status graph",
    )
    async def clients_count(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        if not any(
            role.id in (ADMIN_ROLE_ID, OWNER_ROLE_ID)
            for role in interaction.user.roles
        ):
            e = discord.Embed(
                title="Permission Denied",
                description="You do not have permission to use this command.",
                color=0x8B0000,
                timestamp=discord.utils.utcnow(),
            )
            e.set_footer(text="FlorrMobNotify • Moderation Action", icon_url=FOOTER_ICON)
            await interaction.followup.send(embed=e, ephemeral=True)
            return

        try:
            result = await asyncio.wait_for(
                call_backend({"type": "list_clients"}),
                timeout=10,
            )
        except Exception:
            await interaction.followup.send(
                embed=self._embed_service_unavailable(), ephemeral=True
            )
            return

        if not result.get("ok"):
            await interaction.followup.send(
                embed=self._embed_service_unavailable(), ephemeral=True
            )
            return

        clients_data = result.get("clients", [])
        total        = len(clients_data)

        # Tally counts
        bots = logged_in = guests = anonymous = 0
        for c in clients_data:
            st = c.get("secret_type")
            if st == 0:
                bots += 1
            elif st == 1:
                if c.get("logged_in"):
                    logged_in += 1
                else:
                    guests += 1
            else:
                anonymous += 1

        # Build graph
        graph_buf  = await asyncio.get_event_loop().run_in_executor(
            None,
            _generate_client_graph,
            bots, logged_in, guests, anonymous,
        )
        graph_file = discord.File(graph_buf, filename="client_graph.png")

        _t = max(total, 1)

        def _pct(n: int) -> str:
            return f"{n / _t * 100:.1f}%"

        # Redesigned embed — no emojis, clean modern layout
        e = discord.Embed(
            title="Client Overview",
            description=(
                f"**{total}** connection{'s' if total != 1 else ''} active across all client types."
            ),
            color=0x2563EB,
            timestamp=discord.utils.utcnow(),
        )

        e.add_field(
            name="Logged In",
            value=f"`{logged_in}` — {_pct(logged_in)}",
            inline=True,
        )
        e.add_field(
            name="Bots",
            value=f"`{bots}` — {_pct(bots)}",
            inline=True,
        )
        e.add_field(
            name="Guests",
            value=f"`{guests}` — {_pct(guests)}",
            inline=True,
        )
        e.add_field(
            name="Anonymous",
            value=f"`{anonymous}` — {_pct(anonymous)}",
            inline=True,
        )
        e.add_field(name="\u200b", value="\u200b", inline=True)
        e.add_field(
            name="Total",
            value=f"`{total}`",
            inline=True,
        )

        e.set_image(url="attachment://client_graph.png")
        e.set_footer(text=FOOTER_TEXT, icon_url=FOOTER_ICON)

        await interaction.followup.send(embed=e, file=graph_file, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(ClientsCog(bot))
