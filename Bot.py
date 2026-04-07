"""
Almacén Bot — Discord
Sistema profesional de gestión para almacén en GTA RP Hub
"""
import sys
sys.stdout.reconfigure(line_buffering=True)

import discord
from discord.ext import commands, tasks
import os
import asyncio
import random
import string
from datetime import datetime, timezone
from database import Database

from keep_alive import keep_alive
keep_alive()

# ══════════════════════════════════════════════════════════
#  CONFIGURACIÓN — completá con tus IDs reales
# ══════════════════════════════════════════════════════════
TOKEN    = os.getenv("DISCORD_TOKEN")
GUILD_ID = int(os.getenv("GUILD_ID", "0"))

# IDs de canales — reemplazá con los tuyos
CHANNEL_DASHBOARD  = int(os.getenv("CHANNEL_DASHBOARD",  "0"))
CHANNEL_VENTAS     = int(os.getenv("CHANNEL_VENTAS",     "0"))
CHANNEL_STOCK      = int(os.getenv("CHANNEL_STOCK",      "0"))
CHANNEL_GASTOS     = int(os.getenv("CHANNEL_GASTOS",     "0"))
CHANNEL_DEPOSITOS  = int(os.getenv("CHANNEL_DEPOSITOS",  "0"))
CHANNEL_HISTORIAL  = int(os.getenv("CHANNEL_HISTORIAL",  "0"))

# Roles con permiso completo (sin esto solo pueden ver)
ADMIN_ROLES = ["Admin", "admin", "Dueño", "dueño"]

# Colores
COLOR_VERDE   = 0x2ECC71
COLOR_ROJO    = 0xE74C3C
COLOR_AZUL    = 0x3498DB
COLOR_ORO     = 0xF1C40F
COLOR_MORADO  = 0x9B59B6
COLOR_GRIS    = 0x95A5A6

SEP = "══════════════════════════════"


def fmt_monto(n: int) -> str:
    return f"${n:,}".replace(",", ".")


def gen_codigo() -> str:
    return "#" + "".join(random.choices(string.ascii_uppercase + string.digits, k=6))


def ahora() -> str:
    return datetime.now(timezone.utc).isoformat()


def es_admin(member: discord.Member) -> bool:
    return any(r.name in ADMIN_ROLES for r in member.roles)


# ══════════════════════════════════════════════════════════
#  BOT
# ══════════════════════════════════════════════════════════
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.reactions = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)
db: Database = None
_db_ready = False


# ══════════════════════════════════════════════════════════
#  DASHBOARD
# ══════════════════════════════════════════════════════════
async def build_dashboard_embed() -> discord.Embed:
    balance = await db.get_balance()
    productos = await db.get_productos()
    ventas_por_user = await db.get_ventas_por_usuario()
    ventas_por_prod = await db.get_ventas_por_producto()

    embed = discord.Embed(
        title="🏪  ALMACÉN — PANEL DE CONTROL",
        description=f"{SEP}\n📡  *Dashboard actualizado en tiempo real*\n{SEP}",
        color=COLOR_MORADO
    )

    # ── Balance general ──
    neto = balance["neto"]
    color_neto = "🟢" if neto >= 0 else "🔴"
    embed.add_field(
        name="💰  BALANCE GENERAL",
        value=(
            f"```\n"
            f"  Ventas totales : {fmt_monto(balance['ventas'])}\n"
            f"  Gastos totales : {fmt_monto(balance['gastos'])}\n"
            f"  Depositado     : {fmt_monto(balance['depositos'])}\n"
            f"{'─'*32}\n"
            f"  Ganancia neta  : {fmt_monto(neto)}\n"
            f"```"
        ),
        inline=False
    )

    # ── Stats por socio ──
    if ventas_por_user:
        lines = []
        medals = ["🥇", "🥈", "🥉"]
        for i, v in enumerate(ventas_por_user[:3]):
            med = medals[i] if i < 3 else "▸"
            nombre = v["usuario"].split("#")[0] if v["usuario"] else "?"
            lines.append(f"{med}  **{nombre}** — {fmt_monto(v['total'])}  `({v['cant']} ventas)`")
        embed.add_field(
            name="👥  VENTAS POR SOCIO",
            value="\n".join(lines) or "Sin datos",
            inline=True
        )

    # ── Top productos ──
    if ventas_por_prod:
        lines = []
        for v in ventas_por_prod[:5]:
            prod = v["producto"].capitalize()
            lines.append(f"▸  **{prod}** — {v['unidades']} und · {fmt_monto(v['total'])}")
        embed.add_field(
            name="📊  TOP PRODUCTOS",
            value="\n".join(lines) or "Sin ventas aún",
            inline=True
        )

    embed.add_field(name="", value=SEP, inline=False)

    # ── Stock actual ──
    stock_lines = []
    for p in productos:
        stk = int(p["stock"])
        if stk == 0:
            icono = "🔴"
        elif stk <= 3:
            icono = "🟡"
        else:
            icono = "🟢"
        stock_lines.append(f"{icono}  {p['emoji']}  `{p['nombre']:<12}`  **{stk}**")

    # Dividir en 2 columnas
    mid = (len(stock_lines) + 1) // 2
    embed.add_field(
        name="📦  STOCK ACTUAL",
        value="\n".join(stock_lines[:mid]) or "Sin productos",
        inline=True
    )
    embed.add_field(
        name="‎",
        value="\n".join(stock_lines[mid:]) or "‎",
        inline=True
    )

    embed.add_field(name="", value=SEP, inline=False)
    embed.set_footer(text="🟢 OK  🟡 Bajo (≤3)  🔴 Sin stock  •  Se actualiza cada 10s")
    embed.timestamp = datetime.now(timezone.utc)
    return embed


async def refrescar_dashboard():
    guild = bot.get_guild(GUILD_ID)
    if not guild:
        return
    ch = guild.get_channel(CHANNEL_DASHBOARD)
    if not ch:
        return
    try:
        embed = await build_dashboard_embed()
        saved_id = await db.get_config("dashboard_msg_id")
        if saved_id:
            try:
                msg = await ch.fetch_message(int(saved_id))
                await msg.edit(embed=embed)
                return
            except discord.NotFound:
                pass
        await ch.purge(limit=20)
        msg = await ch.send(embed=embed)
        await db.set_config("dashboard_msg_id", str(msg.id))
    except Exception as e:
        print(f"⚠️ Error dashboard: {e}", flush=True)


@tasks.loop(seconds=10)
async def loop_dashboard():
    if _db_ready:
        await refrescar_dashboard()


# ══════════════════════════════════════════════════════════
#  MODALES
# ══════════════════════════════════════════════════════════

class ModalVenta(discord.ui.Modal, title="💰 Registrar Venta"):
    def __init__(self, producto: str, precio_base: int, stock_actual: int):
        super().__init__()
        self.producto = producto
        self.stock_actual = stock_actual
        self.cantidad = discord.ui.TextInput(
            label=f"Cantidad (stock disponible: {stock_actual})",
            placeholder="Ej: 5",
            max_length=5
        )
        self.precio = discord.ui.TextInput(
            label=f"Precio por unidad (base: ${precio_base:,})",
            placeholder=f"Ej: {precio_base or 10000}",
            max_length=10
        )
        self.add_item(self.cantidad)
        self.add_item(self.precio)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            cant = int(self.cantidad.value.strip())
            precio = int(self.precio.value.strip().replace(".", "").replace(",", ""))
            assert cant > 0 and precio > 0
        except:
            return await interaction.response.send_message(
                "❌ Cantidad o precio inválido.", ephemeral=True
            )

        if cant > self.stock_actual:
            return await interaction.response.send_message(
                f"❌ Stock insuficiente. Tenés **{self.stock_actual}** unidades de **{self.producto}**.",
                ephemeral=True
            )

        ok = await db.restar_stock(self.producto, cant)
        if not ok:
            return await interaction.response.send_message(
                "❌ No se pudo descontar el stock. Intentá de nuevo.", ephemeral=True
            )

        total = await db.registrar_venta(
            self.producto, cant, precio,
            interaction.user.id, str(interaction.user)
        )

        # ── Aviso de venta en el canal de ventas ──
        embed = discord.Embed(
            title="🛒  VENTA REGISTRADA",
            color=COLOR_VERDE
        )
        embed.add_field(name="▸ Producto",     value=f"**{self.producto.capitalize()}**", inline=True)
        embed.add_field(name="▸ Cantidad",     value=f"**{cant}** unidades",             inline=True)
        embed.add_field(name="▸ Precio/u",     value=fmt_monto(precio),                  inline=True)
        embed.add_field(name="▸ Total cobrado",value=f"**{fmt_monto(total)}**",           inline=True)
        embed.add_field(name="▸ Vendedor",     value=interaction.user.mention,           inline=True)
        embed.add_field(
            name="💰 Depósito",
            value=f"Se generó aviso en <#{CHANNEL_DEPOSITOS}>",
            inline=False
        )
        embed.set_footer(text="Sistema Almacén")
        embed.timestamp = datetime.now(timezone.utc)
        await interaction.response.send_message(embed=embed)

        guild = bot.get_guild(GUILD_ID)
        if not guild:
            asyncio.create_task(refrescar_panel_ventas())
            return

        # ── Aviso de depósito automático ──
        ch_dep = guild.get_channel(CHANNEL_DEPOSITOS)
        if ch_dep:
            codigo = gen_codigo()
            dep_embed = discord.Embed(
                title="💰  DEPÓSITO PENDIENTE",
                description=f"{SEP}\nSe realizó una venta y hay que depositar a la organización.\n{SEP}",
                color=COLOR_ORO
            )
            dep_embed.add_field(name="🛒  Venta",       value=f"{cant}x **{self.producto.capitalize()}**", inline=True)
            dep_embed.add_field(name="💵  Monto",       value=f"**{fmt_monto(total)}**",                   inline=True)
            dep_embed.add_field(name="🏷️  Código org.", value=f"**`{codigo}`**",                           inline=True)
            dep_embed.add_field(name="👤  Vendedor",    value=interaction.user.mention,                    inline=True)
            dep_embed.add_field(
                name="✅  Confirmación",
                value="Reaccioná con ✅ una vez que hayas depositado el dinero.",
                inline=False
            )
            dep_embed.set_footer(text="Sistema Almacén • Depósitos automáticos")
            dep_embed.timestamp = datetime.now(timezone.utc)

            dep_msg = await ch_dep.send(embed=dep_embed)
            await dep_msg.add_reaction("✅")

            await db.registrar_deposito(
                total, codigo,
                interaction.user.id, str(interaction.user),
                str(dep_msg.id)
            )

        # ── Log en historial ──
        ch_hist = guild.get_channel(CHANNEL_HISTORIAL)
        if ch_hist:
            log_embed = discord.Embed(
                description=(
                    f"🛒  **{interaction.user.display_name}** vendió "
                    f"**{cant}x {self.producto.capitalize()}** "
                    f"a {fmt_monto(precio)}/u — Total: **{fmt_monto(total)}** → depósito pendiente ⏳"
                ),
                color=COLOR_VERDE
            )
            log_embed.timestamp = datetime.now(timezone.utc)
            await ch_hist.send(embed=log_embed)

        asyncio.create_task(refrescar_panel_ventas())


class ModalGasto(discord.ui.Modal, title="💸 Registrar Gasto"):
    descripcion = discord.ui.TextInput(
        label="Descripción del gasto",
        placeholder="Ej: Compra de ropa al proveedor",
        max_length=200
    )
    monto = discord.ui.TextInput(
        label="Monto",
        placeholder="Ej: 500000",
        max_length=10
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            monto = int(self.monto.value.strip().replace(".", "").replace(",", ""))
            assert monto > 0
        except:
            return await interaction.response.send_message("❌ Monto inválido.", ephemeral=True)

        await db.registrar_gasto(
            self.descripcion.value.strip(), monto,
            interaction.user.id, str(interaction.user)
        )

        embed = discord.Embed(
            title="💸  GASTO REGISTRADO",
            color=COLOR_ROJO
        )
        embed.add_field(name="▸ Descripción", value=self.descripcion.value, inline=False)
        embed.add_field(name="▸ Monto", value=f"**{fmt_monto(monto)}**", inline=True)
        embed.add_field(name="▸ Registrado por", value=interaction.user.mention, inline=True)
        embed.set_footer(text="Sistema Almacén")
        embed.timestamp = datetime.now(timezone.utc)
        await interaction.response.send_message(embed=embed)

        guild = bot.get_guild(GUILD_ID)
        if guild:
            ch_hist = guild.get_channel(CHANNEL_HISTORIAL)
            if ch_hist:
                log_embed = discord.Embed(
                    description=(
                        f"💸  **{interaction.user.display_name}** registró gasto: "
                        f"*{self.descripcion.value}* — **{fmt_monto(monto)}**"
                    ),
                    color=COLOR_ROJO
                )
                log_embed.timestamp = datetime.now(timezone.utc)
                await ch_hist.send(embed=log_embed)


class ModalIngresoStock(discord.ui.Modal, title="📦 Ingresar Stock"):
    def __init__(self, producto: str):
        super().__init__()
        self.producto = producto
        self.cantidad = discord.ui.TextInput(
            label=f"Cantidad a ingresar de: {producto}",
            placeholder="Ej: 10",
            max_length=5
        )
        self.notas = discord.ui.TextInput(
            label="Notas (opcional)",
            required=False,
            max_length=200,
            placeholder="Ej: Compra al mayorista"
        )
        self.add_item(self.cantidad)
        self.add_item(self.notas)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            cant = int(self.cantidad.value.strip())
            assert cant > 0
        except:
            return await interaction.response.send_message("❌ Cantidad inválida.", ephemeral=True)

        await db.sumar_stock(self.producto, cant)
        await db.registrar_ingreso_stock(
            self.producto, cant,
            interaction.user.id, str(interaction.user),
            self.notas.value.strip() or None
        )

        embed = discord.Embed(
            title="📦  STOCK INGRESADO",
            color=COLOR_AZUL
        )
        embed.add_field(name="▸ Producto", value=f"**{self.producto.capitalize()}**", inline=True)
        embed.add_field(name="▸ Cantidad", value=f"**+{cant}**", inline=True)
        embed.add_field(name="▸ Por", value=interaction.user.mention, inline=True)
        if self.notas.value:
            embed.add_field(name="▸ Notas", value=self.notas.value, inline=False)
        embed.set_footer(text="Sistema Almacén")
        embed.timestamp = datetime.now(timezone.utc)
        await interaction.response.send_message(embed=embed, ephemeral=True)

        guild = bot.get_guild(GUILD_ID)
        if guild:
            ch_hist = guild.get_channel(CHANNEL_HISTORIAL)
            if ch_hist:
                log_embed = discord.Embed(
                    description=(
                        f"📦  **{interaction.user.display_name}** ingresó "
                        f"**{cant}x {self.producto.capitalize()}** al stock"
                    ),
                    color=COLOR_AZUL
                )
                log_embed.timestamp = datetime.now(timezone.utc)
                await ch_hist.send(embed=log_embed)

        asyncio.create_task(refrescar_panel_stock())


class ModalNuevoProducto(discord.ui.Modal, title="➕ Nuevo Producto"):
    nombre = discord.ui.TextInput(
        label="Nombre del producto",
        placeholder="Ej: cemento",
        max_length=30
    )
    emoji = discord.ui.TextInput(
        label="Emoji",
        placeholder="Ej: 🧱",
        max_length=5,
        default="📦"
    )
    precio_base = discord.ui.TextInput(
        label="Precio base (puede cambiarse al vender)",
        placeholder="Ej: 15000",
        max_length=10,
        required=False
    )

    async def on_submit(self, interaction: discord.Interaction):
        if not es_admin(interaction.user):
            return await interaction.response.send_message(
                "❌ Solo admins pueden agregar productos.", ephemeral=True
            )
        nombre = self.nombre.value.strip().lower()
        emoji = self.emoji.value.strip() or "📦"
        try:
            precio = int(self.precio_base.value.strip().replace(".", "").replace(",", "")) if self.precio_base.value.strip() else 0
        except:
            precio = 0

        prod = await db.get_producto(nombre)
        if prod:
            return await interaction.response.send_message(
                f"❌ Ya existe el producto **{nombre}**.", ephemeral=True
            )

        await db.agregar_producto(nombre, emoji, precio)
        await interaction.response.send_message(
            f"✅ Producto **{emoji} {nombre}** agregado con precio base {fmt_monto(precio)}.",
            ephemeral=True
        )
        asyncio.create_task(refrescar_panel_stock())


class ModalEditarPrecio(discord.ui.Modal, title="✏️ Editar Precio Base"):
    def __init__(self, producto: str, precio_actual: int):
        super().__init__()
        self.producto = producto
        self.precio = discord.ui.TextInput(
            label=f"Nuevo precio base para: {producto}",
            placeholder="Ej: 25000",
            default=str(precio_actual),
            max_length=10
        )
        self.add_item(self.precio)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            precio = int(self.precio.value.strip().replace(".", "").replace(",", ""))
            assert precio >= 0
        except:
            return await interaction.response.send_message("❌ Precio inválido.", ephemeral=True)

        await db.actualizar_precio_base(self.producto, precio)
        await interaction.response.send_message(
            f"✅ Precio base de **{self.producto}** actualizado a **{fmt_monto(precio)}**.",
            ephemeral=True
        )
        asyncio.create_task(refrescar_panel_stock())


# ══════════════════════════════════════════════════════════
#  SELECTS
# ══════════════════════════════════════════════════════════

class SelectProductoVenta(discord.ui.Select):
    def __init__(self, productos):
        self.prods = {p["nombre"]: p for p in productos}
        options = []
        for p in productos[:25]:
            stk = int(p["stock"])
            desc = f"Stock: {stk} | Precio base: ${p['precio_base']:,}" if stk > 0 else "SIN STOCK"
            options.append(discord.SelectOption(
                label=p["nombre"].capitalize(),
                value=p["nombre"],
                emoji=p["emoji"] or "📦",
                description=desc[:100],
                default=False
            ))
        super().__init__(placeholder="Seleccioná el producto a vender...", options=options, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        prod = self.prods[self.values[0]]
        stk = int(prod["stock"])
        if stk == 0:
            return await interaction.response.send_message(
                f"❌ Sin stock de **{prod['nombre']}**.", ephemeral=True
            )
        await interaction.response.send_modal(
            ModalVenta(prod["nombre"], int(prod["precio_base"]), stk)
        )


class SelectProductoStock(discord.ui.Select):
    def __init__(self, productos, accion: str):
        self.prods = {p["nombre"]: p for p in productos}
        self.accion = accion
        options = [
            discord.SelectOption(
                label=p["nombre"].capitalize(),
                value=p["nombre"],
                emoji=p["emoji"] or "📦",
                description=f"Stock actual: {p['stock']}"
            ) for p in productos[:25]
        ]
        super().__init__(placeholder="Seleccioná el producto...", options=options)

    async def callback(self, interaction: discord.Interaction):
        prod = self.prods[self.values[0]]
        if self.accion == "ingresar":
            await interaction.response.send_modal(ModalIngresoStock(prod["nombre"]))
        elif self.accion == "precio":
            if not es_admin(interaction.user):
                return await interaction.response.send_message("❌ Solo admins.", ephemeral=True)
            await interaction.response.send_modal(
                ModalEditarPrecio(prod["nombre"], int(prod["precio_base"]))
            )


# ══════════════════════════════════════════════════════════
#  VIEWS / PANELES
# ══════════════════════════════════════════════════════════

class PanelVentas(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Registrar Venta", style=discord.ButtonStyle.success,
                       emoji="🛒", custom_id="venta_registrar")
    async def btn_venta(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not _db_ready:
            return await interaction.response.send_message("⏳ Bot iniciando...", ephemeral=True)
        productos = await db.get_productos()
        disponibles = [p for p in productos if int(p["stock"]) > 0]
        if not disponibles:
            return await interaction.response.send_message(
                "❌ No hay productos con stock disponible.", ephemeral=True
            )
        view = discord.ui.View(timeout=60)
        view.add_item(SelectProductoVenta(disponibles))
        await interaction.response.send_message(
            "Seleccioná el producto que vendiste:", view=view, ephemeral=True
        )


class PanelGastos(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Registrar Gasto", style=discord.ButtonStyle.danger,
                       emoji="💸", custom_id="gasto_registrar")
    async def btn_gasto(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ModalGasto())


class PanelDepositos(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Ver Pendientes", style=discord.ButtonStyle.danger,
                       emoji="⏳", custom_id="deposito_pendientes")
    async def btn_pendientes(self, interaction: discord.Interaction, button: discord.ui.Button):
        depositos = await db.get_depositos(15)
        pendientes = [d for d in depositos if not d["confirmado"]]
        if not pendientes:
            return await interaction.response.send_message(
                "✅ No hay depósitos pendientes. Todo al día.", ephemeral=True
            )
        embed = discord.Embed(title="⏳  DEPÓSITOS PENDIENTES", color=COLOR_ROJO)
        lines = []
        for d in pendientes:
            ts = d["fecha"][:16].replace("T", " ")
            nombre = d["usuario"].split("#")[0]
            lines.append(f"⏳  `{ts}`  **{nombre}**  —  {fmt_monto(d['monto'])}  `{d['codigo']}`")
        embed.description = "\n".join(lines)
        embed.add_field(
            name="Cómo confirmar",
            value="Buscá el mensaje del depósito en este canal y reaccioná con ✅",
            inline=False
        )
        embed.set_footer(text="Sistema Almacén • Depósitos automáticos por venta")
        embed.timestamp = datetime.now(timezone.utc)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="Ver Historial", style=discord.ButtonStyle.secondary,
                       emoji="📋", custom_id="deposito_historial")
    async def btn_hist_dep(self, interaction: discord.Interaction, button: discord.ui.Button):
        depositos = await db.get_depositos(12)
        if not depositos:
            return await interaction.response.send_message("📋 Sin depósitos registrados.", ephemeral=True)
        embed = discord.Embed(title="📋  HISTORIAL DE DEPÓSITOS", color=COLOR_ORO)
        lines = []
        for d in depositos:
            estado = "✅" if d["confirmado"] else "⏳"
            ts = d["fecha"][:16].replace("T", " ")
            nombre = d["usuario"].split("#")[0]
            lines.append(f"{estado}  `{ts}`  **{nombre}**  —  {fmt_monto(d['monto'])}  `{d['codigo']}`")
        embed.description = "\n".join(lines)
        embed.set_footer(text="✅ Confirmado  ⏳ Pendiente")
        embed.timestamp = datetime.now(timezone.utc)
        await interaction.response.send_message(embed=embed, ephemeral=True)


class PanelStock(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Agregar Stock", style=discord.ButtonStyle.primary,
                       emoji="📥", custom_id="stock_agregar")
    async def btn_agregar(self, interaction: discord.Interaction, button: discord.ui.Button):
        productos = await db.get_productos()
        if not productos:
            return await interaction.response.send_message("❌ Sin productos configurados.", ephemeral=True)
        view = discord.ui.View(timeout=60)
        view.add_item(SelectProductoStock(productos, "ingresar"))
        await interaction.response.send_message("Seleccioná el producto:", view=view, ephemeral=True)

    @discord.ui.button(label="Nuevo Producto", style=discord.ButtonStyle.success,
                       emoji="➕", custom_id="stock_nuevo_producto")
    async def btn_nuevo(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not es_admin(interaction.user):
            return await interaction.response.send_message("❌ Solo admins.", ephemeral=True)
        await interaction.response.send_modal(ModalNuevoProducto())

    @discord.ui.button(label="Editar Precio Base", style=discord.ButtonStyle.secondary,
                       emoji="✏️", custom_id="stock_editar_precio")
    async def btn_precio(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not es_admin(interaction.user):
            return await interaction.response.send_message("❌ Solo admins.", ephemeral=True)
        productos = await db.get_productos()
        if not productos:
            return await interaction.response.send_message("❌ Sin productos.", ephemeral=True)
        view = discord.ui.View(timeout=60)
        view.add_item(SelectProductoStock(productos, "precio"))
        await interaction.response.send_message(
            "Seleccioná el producto a editar:", view=view, ephemeral=True
        )


# ══════════════════════════════════════════════════════════
#  BUILDERS DE EMBEDS DE PANEL
# ══════════════════════════════════════════════════════════

async def build_embed_ventas() -> discord.Embed:
    ventas = await db.get_ventas(8)
    embed = discord.Embed(
        title="🛒  PANEL DE VENTAS",
        description=(
            f"{SEP}\n"
            "Registrá cada venta que hacés.\n"
            "El stock se descuenta automáticamente.\n\n"
            "**¿Cómo usar?**\n"
            "1️⃣  Presioná **Registrar Venta**\n"
            "2️⃣  Elegí el producto vendido\n"
            "3️⃣  Ingresá cantidad y precio real de venta\n"
            f"{SEP}"
        ),
        color=COLOR_VERDE
    )
    if ventas:
        lines = []
        for v in ventas:
            ts = v["fecha"][:16].replace("T", " ")
            nombre = v["usuario"].split("#")[0]
            lines.append(
                f"🛒  `{ts}`  **{nombre}**  —  {v['producto'].capitalize()}  x{v['cantidad']}  **{fmt_monto(v['total'])}**"
            )
        embed.add_field(name="📋  Últimas ventas", value="\n".join(lines), inline=False)
    embed.set_footer(text="Sistema Almacén  •  Panel de Ventas")
    embed.timestamp = datetime.now(timezone.utc)
    return embed


async def build_embed_gastos() -> discord.Embed:
    gastos = await db.get_gastos(8)
    embed = discord.Embed(
        title="💸  PANEL DE GASTOS",
        description=(
            f"{SEP}\n"
            "Registrá todo gasto que hagas: compras al proveedor,\n"
            "materiales, costos, etc.\n\n"
            "**¿Cómo usar?**\n"
            "1️⃣  Presioná **Registrar Gasto**\n"
            "2️⃣  Describí qué fue y cuánto gastaste\n"
            f"{SEP}"
        ),
        color=COLOR_ROJO
    )
    if gastos:
        lines = []
        for g in gastos:
            ts = g["fecha"][:16].replace("T", " ")
            nombre = g["usuario"].split("#")[0]
            lines.append(
                f"💸  `{ts}`  **{nombre}**  —  *{g['descripcion'][:30]}*  **{fmt_monto(g['monto'])}**"
            )
        embed.add_field(name="📋  Últimos gastos", value="\n".join(lines), inline=False)
    embed.set_footer(text="Sistema Almacén  •  Panel de Gastos")
    embed.timestamp = datetime.now(timezone.utc)
    return embed


async def build_embed_depositos() -> discord.Embed:
    total_dep = await db.get_total_depositos()
    depositos = await db.get_depositos(15)
    pendientes = [d for d in depositos if not d["confirmado"]]
    total_pendiente = sum(d["monto"] for d in pendientes)

    embed = discord.Embed(
        title="💰  PANEL DE DEPÓSITOS",
        description=(
            f"{SEP}\n"
            "Los depósitos se generan **automáticamente** con cada venta.\n"
            "El monto completo de la venta debe depositarse a la organización.\n\n"
            "**¿Cómo funciona?**\n"
            "1️⃣  Alguien registra una venta → aparece el aviso acá\n"
            "2️⃣  Depositás en el juego usando el código indicado\n"
            "3️⃣  Reaccionás con ✅ al mensaje para confirmar\n"
            f"{SEP}"
        ),
        color=COLOR_ORO
    )
    embed.add_field(
        name="✅  Total depositado",
        value=f"**{fmt_monto(total_dep)}**",
        inline=True
    )
    embed.add_field(
        name="⏳  Pendiente de depósito",
        value=f"**{fmt_monto(total_pendiente)}**" + ("  ⚠️" if total_pendiente > 0 else "  ✔️"),
        inline=True
    )
    if pendientes:
        embed.add_field(
            name=f"⏳  {len(pendientes)} depósito(s) pendiente(s)",
            value="\n".join(
                f"▸ {d['usuario'].split('#')[0]}  —  {fmt_monto(d['monto'])}  `{d['codigo']}`"
                for d in pendientes[:5]
            ),
            inline=False
        )
    embed.set_footer(text="Sistema Almacén  •  Depósitos automáticos por venta")
    embed.timestamp = datetime.now(timezone.utc)
    return embed


async def build_embed_stock() -> discord.Embed:
    productos = await db.get_productos()
    embed = discord.Embed(
        title="📦  PANEL DE STOCK",
        description=(
            f"{SEP}\n"
            "Stock actual del almacén.\n"
            "Usá los botones para ingresar mercadería o agregar productos nuevos.\n"
            f"{SEP}"
        ),
        color=COLOR_AZUL
    )
    if productos:
        lines = []
        for p in productos:
            stk = int(p["stock"])
            if stk == 0:
                ind = "🔴"
            elif stk <= 3:
                ind = "🟡"
            else:
                ind = "🟢"
            lines.append(f"{ind}  {p['emoji']}  **{p['nombre'].capitalize()}**  —  `{stk}` unidades  ·  base: {fmt_monto(p['precio_base'])}")
        embed.add_field(name="📋  Inventario", value="\n".join(lines), inline=False)
    embed.set_footer(text="🟢 OK  🟡 Bajo (≤3)  🔴 Sin stock  •  Sistema Almacén")
    embed.timestamp = datetime.now(timezone.utc)
    return embed


# ══════════════════════════════════════════════════════════
#  REFRESCAR PANELES
# ══════════════════════════════════════════════════════════

async def _refrescar_panel(config_key: str, canal_id: int,
                            build_fn, view_cls, purge_on_new=True):
    guild = bot.get_guild(GUILD_ID)
    if not guild:
        return
    ch = guild.get_channel(canal_id)
    if not ch:
        return
    try:
        embed = await build_fn()
        view = view_cls()
        saved_id = await db.get_config(config_key)
        if saved_id:
            try:
                msg = await ch.fetch_message(int(saved_id))
                await msg.edit(embed=embed, view=view)
                return
            except discord.NotFound:
                pass
        if purge_on_new:
            await ch.purge(limit=20)
        msg = await ch.send(embed=embed, view=view)
        await db.set_config(config_key, str(msg.id))
    except Exception as e:
        print(f"⚠️ Error refrescando panel {config_key}: {e}", flush=True)


async def refrescar_panel_ventas():
    await _refrescar_panel("panel_ventas_id", CHANNEL_VENTAS, build_embed_ventas, PanelVentas)


async def refrescar_panel_gastos():
    await _refrescar_panel("panel_gastos_id", CHANNEL_GASTOS, build_embed_gastos, PanelGastos)


async def refrescar_panel_depositos():
    await _refrescar_panel("panel_depositos_id", CHANNEL_DEPOSITOS, build_embed_depositos, PanelDepositos)


async def refrescar_panel_stock():
    await _refrescar_panel("panel_stock_id", CHANNEL_STOCK, build_embed_stock, PanelStock)


# ══════════════════════════════════════════════════════════
#  CONFIRMACIÓN DE DEPÓSITO POR REACCIÓN
# ══════════════════════════════════════════════════════════

@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    if not _db_ready:
        return
    if str(payload.emoji) != "✅":
        return
    if payload.user_id == bot.user.id:
        return

    guild = bot.get_guild(payload.guild_id)
    if not guild:
        return
    channel = guild.get_channel(payload.channel_id)
    if not channel or channel.id != CHANNEL_DEPOSITOS:
        return

    deposito = await db.get_deposito_por_msg(str(payload.message_id))
    if not deposito:
        return
    if deposito["confirmado"]:
        return

    await db.confirmar_deposito(deposito["id"])

    try:
        msg = await channel.fetch_message(payload.message_id)
        embed = msg.embeds[0] if msg.embeds else discord.Embed()
        embed.color = COLOR_VERDE
        embed.set_footer(text=f"✅ Confirmado por {guild.get_member(payload.user_id).display_name if guild.get_member(payload.user_id) else 'alguien'}")
        await msg.edit(embed=embed)
    except Exception:
        pass

    # Mensaje de confirmación en historial
    ch_hist = guild.get_channel(CHANNEL_HISTORIAL)
    if ch_hist:
        log_embed = discord.Embed(
            description=(
                f"💰  Depósito confirmado: **{fmt_monto(deposito['monto'])}** "
                f"de **{deposito['usuario'].split('#')[0]}**  `{deposito['codigo']}`"
            ),
            color=COLOR_VERDE
        )
        log_embed.timestamp = datetime.now(timezone.utc)
        await ch_hist.send(embed=log_embed)

    asyncio.create_task(refrescar_panel_depositos())


# ══════════════════════════════════════════════════════════
#  SLASH COMMANDS (solo admin)
# ══════════════════════════════════════════════════════════

@bot.tree.command(name="resetpaneles", description="[ADMIN] Resetea todos los paneles")
async def cmd_reset(interaction: discord.Interaction):
    if not es_admin(interaction.user):
        return await interaction.response.send_message("❌ Solo admins.", ephemeral=True)
    await interaction.response.defer(ephemeral=True)
    guild = interaction.guild

    for config_key, canal_id, build_fn, view_cls in [
        ("panel_ventas_id",    CHANNEL_VENTAS,    build_embed_ventas,    PanelVentas),
        ("panel_gastos_id",    CHANNEL_GASTOS,    build_embed_gastos,    PanelGastos),
        ("panel_depositos_id", CHANNEL_DEPOSITOS, build_embed_depositos, PanelDepositos),
        ("panel_stock_id",     CHANNEL_STOCK,     build_embed_stock,     PanelStock),
    ]:
        ch = guild.get_channel(canal_id)
        if ch:
            await db.set_config(config_key, "")
            await ch.purge(limit=30)
        await _refrescar_panel(config_key, canal_id, build_fn, view_cls, purge_on_new=True)

    await db.set_config("dashboard_msg_id", "")
    ch_dash = guild.get_channel(CHANNEL_DASHBOARD)
    if ch_dash:
        await ch_dash.purge(limit=20)
    await refrescar_dashboard()

    await interaction.followup.send("✅ Todos los paneles fueron reseteados.", ephemeral=True)


@bot.tree.command(name="balance", description="Ver el balance general")
async def cmd_balance(interaction: discord.Interaction):
    balance = await db.get_balance()
    ventas_user = await db.get_ventas_por_usuario()
    gastos_user = await db.get_gastos_por_usuario()
    ventas_prod = await db.get_ventas_por_producto()

    embed = discord.Embed(title="📊  BALANCE COMPLETO", color=COLOR_MORADO)
    embed.add_field(
        name="💰 Resumen",
        value=(
            f"Ventas: **{fmt_monto(balance['ventas'])}**\n"
            f"Gastos: **{fmt_monto(balance['gastos'])}**\n"
            f"Depósitos: **{fmt_monto(balance['depositos'])}**\n"
            f"Ganancia neta: **{fmt_monto(balance['neto'])}**"
        ),
        inline=False
    )
    if ventas_user:
        lines = [f"▸ **{v['usuario'].split('#')[0]}**: {fmt_monto(v['total'])} ({v['cant']} ventas)" for v in ventas_user]
        embed.add_field(name="🛒 Ventas por socio", value="\n".join(lines), inline=True)
    if gastos_user:
        lines = [f"▸ **{g['usuario'].split('#')[0]}**: {fmt_monto(g['total'])} ({g['cant']} gastos)" for g in gastos_user]
        embed.add_field(name="💸 Gastos por socio", value="\n".join(lines), inline=True)
    if ventas_prod:
        lines = [f"▸ **{v['producto'].capitalize()}**: {v['unidades']} und · {fmt_monto(v['total'])}" for v in ventas_prod[:8]]
        embed.add_field(name="📦 Por producto", value="\n".join(lines), inline=False)
    embed.timestamp = datetime.now(timezone.utc)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="historial", description="Ver historial de movimientos")
async def cmd_historial(interaction: discord.Interaction):
    movs = await db.get_historial_general(20)
    if not movs:
        return await interaction.response.send_message("📋 Sin movimientos.", ephemeral=True)
    embed = discord.Embed(title="📋  HISTORIAL GENERAL", color=COLOR_GRIS)
    lines = []
    for m in movs:
        ts = m["fecha"][:16].replace("T", " ")
        nombre = m["usuario"].split("#")[0] if m["usuario"] else "?"
        if m["tipo"] == "venta":
            e = "🛒"
            monto_str = f"+{fmt_monto(m['monto'])}"
        elif m["tipo"] == "gasto":
            e = "💸"
            monto_str = f"{fmt_monto(m['monto'])}"
        else:
            e = "💰"
            monto_str = f"+{fmt_monto(m['monto'])}"
        lines.append(f"{e}  `{ts}`  **{nombre}**  —  *{str(m['detalle'])[:25]}*  `{monto_str}`")
    embed.description = "\n".join(lines)
    embed.timestamp = datetime.now(timezone.utc)
    await interaction.response.send_message(embed=embed, ephemeral=True)


# ══════════════════════════════════════════════════════════
#  STARTUP
# ══════════════════════════════════════════════════════════

async def setup_all_panels(guild: discord.Guild):
    for config_key, canal_id, build_fn, view_cls in [
        ("panel_ventas_id",    CHANNEL_VENTAS,    build_embed_ventas,    PanelVentas),
        ("panel_gastos_id",    CHANNEL_GASTOS,    build_embed_gastos,    PanelGastos),
        ("panel_depositos_id", CHANNEL_DEPOSITOS, build_embed_depositos, PanelDepositos),
        ("panel_stock_id",     CHANNEL_STOCK,     build_embed_stock,     PanelStock),
    ]:
        ch = guild.get_channel(canal_id)
        if not ch:
            print(f"⚠️ Canal {canal_id} no encontrado, saltando...", flush=True)
            continue
        saved_id = await db.get_config(config_key)
        panel_ok = False
        if saved_id:
            try:
                await ch.fetch_message(int(saved_id))
                panel_ok = True
                print(f"✅ Panel {config_key} ya existe", flush=True)
            except discord.NotFound:
                panel_ok = False
        if not panel_ok:
            await ch.purge(limit=20)
            await _refrescar_panel(config_key, canal_id, build_fn, view_cls, purge_on_new=False)
            print(f"✅ Panel {config_key} creado", flush=True)


async def startup():
    global db, _db_ready
    print("🔄 Iniciando base de datos...", flush=True)
    try:
        db = Database()
        await db.init()
        _db_ready = True
    except Exception as e:
        print(f"❌ FATAL — DB: {e}", flush=True)
        return

    try:
        guild_obj = discord.Object(id=GUILD_ID)
        bot.tree.copy_global_to(guild=guild_obj)
        await bot.tree.sync(guild=guild_obj)
        print("✅ Slash commands sincronizados", flush=True)
    except Exception as e:
        print(f"⚠️ Error sincronizando slash: {e}", flush=True)

    guild = bot.get_guild(GUILD_ID)
    if guild:
        await setup_all_panels(guild)
    else:
        print(f"⚠️ Guild {GUILD_ID} no encontrado", flush=True)

    await refrescar_dashboard()

    if not loop_dashboard.is_running():
        loop_dashboard.start()
        print("✅ Dashboard loop iniciado", flush=True)


@bot.event
async def on_ready():
    print(f"✅ Bot conectado: {bot.user}", flush=True)
    # Registrar views persistentes
    bot.add_view(PanelVentas())
    bot.add_view(PanelGastos())
    bot.add_view(PanelDepositos())
    bot.add_view(PanelStock())
    asyncio.create_task(startup())


bot.run(TOKEN)
