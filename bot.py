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
import aiohttp
import random
import string
from datetime import datetime, timezone
from database import Database

from keep_alive import keep_alive
keep_alive()

# ══════════════════════════════════════════════════════════
#  CONFIGURACIÓN
# ══════════════════════════════════════════════════════════
TOKEN    = os.getenv("DISCORD_TOKEN")
GUILD_ID = int(os.getenv("GUILD_ID", "0"))

CHANNEL_DASHBOARD  = int(os.getenv("CHANNEL_DASHBOARD",  "0"))
CHANNEL_VENTAS     = int(os.getenv("CHANNEL_VENTAS",     "0"))
CHANNEL_STOCK      = int(os.getenv("CHANNEL_STOCK",      "0"))
CHANNEL_GASTOS     = int(os.getenv("CHANNEL_GASTOS",     "0"))
CHANNEL_DEPOSITOS  = int(os.getenv("CHANNEL_DEPOSITOS",  "0"))
CHANNEL_HISTORIAL  = int(os.getenv("CHANNEL_HISTORIAL",  "0"))

# URL pública de Render para el auto-ping (se obtiene automáticamente)
RENDER_URL = os.getenv("RENDER_EXTERNAL_URL", "")

ADMIN_ROLES = ["Admin", "admin", "Dueño", "dueño"]

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
    return "#PUR26D"


def ahora() -> str:
    return datetime.now(timezone.utc).isoformat()


def es_admin(member: discord.Member) -> bool:
    return any(r.name in ADMIN_ROLES for r in member.roles)


# ══════════════════════════════════════════════════════════
#  HELPER — log al historial como texto simple (sin embed)
# ══════════════════════════════════════════════════════════
async def log_historial(guild: discord.Guild, texto: str):
    ch = guild.get_channel(CHANNEL_HISTORIAL)
    if ch:
        try:
            await ch.send(texto)
        except Exception:
            pass


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
#  AUTO-PING — evita que Render duerma el servicio
# ══════════════════════════════════════════════════════════
@tasks.loop(minutes=4)
async def loop_self_ping():
    """Se pingea a sí mismo cada 4 minutos para no dormir en Render free."""
    if not RENDER_URL:
        return
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{RENDER_URL}/ping", timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    print(f"🏓 Self-ping OK ({datetime.now(timezone.utc).strftime('%H:%M')})", flush=True)
    except Exception as e:
        print(f"⚠️ Self-ping falló: {e}", flush=True)

@loop_self_ping.before_loop
async def before_self_ping():
    await bot.wait_until_ready()


# ══════════════════════════════════════════════════════════
#  DASHBOARD
# ══════════════════════════════════════════════════════════
async def build_dashboard_embed() -> discord.Embed:
    balance         = await db.get_balance()
    productos       = await db.get_productos()
    ventas_por_user = await db.get_ventas_por_usuario()
    ventas_por_prod = await db.get_ventas_por_producto()

    ventas_sin_dep = await db._rows(
        "SELECT usuario, SUM(total) as subtotal FROM ventas WHERE depositado=0 GROUP BY usuario_id"
    )
    total_sin_dep = sum(int(v["subtotal"]) for v in ventas_sin_dep)
    neto = balance["neto"]

    embed = discord.Embed(
        title="\U0001f3ea  ALM\u00c1C\u00c9N  \u2014  PANEL DE CONTROL",
        description=f"\U0001f4b5  **CAJA ACTUAL**\n# {fmt_monto(neto)}",
        color=COLOR_MORADO
    )

    # Gif como imagen principal del embed (abajo, pero integrado)
    embed.set_image(url="https://i.imgur.com/5Wo4zHG.gif")


    # ── DEPÓSITOS ───────────────────────────────────
    if ventas_sin_dep:
        dep_lines = "\n".join(
            f"\u23f3 **{v['usuario'].split('#')[0]}** \u2014 {fmt_monto(int(v['subtotal']))}"
            for v in ventas_sin_dep
        )
        dep_value = f"\u26a0\ufe0f **{fmt_monto(total_sin_dep)}** sin cerrar\n{dep_lines}"
    else:
        dep_value = "\u2705 Todo cerrado"

    embed.add_field(name="\U0001f3e6  DEP\u00d3SITOS", value=dep_value, inline=True)

    # ── VENTAS POR SOCIO ──────────────────────────
    medals = ["\U0001f947", "\U0001f948", "\U0001f949", "4\ufe0f\u20e3", "5\ufe0f\u20e3"]
    if ventas_por_user:
        v_lines = []
        for i, v in enumerate(ventas_por_user[:5]):
            med    = medals[i] if i < len(medals) else "\u25b8"
            nombre = v["usuario"].split("#")[0] if v["usuario"] else "?"
            v_lines.append(f"{med} **{nombre}** \u2014 {fmt_monto(v['total'])} `{v['cant']}v`")
        embed.add_field(name="\U0001f465  VENTAS", value="\n".join(v_lines), inline=True)

    embed.add_field(name="", value=SEP, inline=False)

    # ── TOP PRODUCTOS ────────────────────────────────
    if ventas_por_prod:
        p_lines = []
        for v in ventas_por_prod[:5]:
            p_lines.append(f"\u25b8 **{v['producto'].capitalize()}** \u2014 {v['unidades']}u \u00b7 {fmt_monto(v['total'])}")
        embed.add_field(name="\U0001f4ca  TOP PRODUCTOS", value="\n".join(p_lines), inline=True)

    # ── STOCK ───────────────────────────────────────
    if productos:
        col_a, col_b = [], []
        for i, p in enumerate(productos):
            stk   = int(p["stock"])
            icono = "\U0001f534" if stk == 0 else ("\U0001f7e1" if stk <= 10 else "\U0001f7e2")
            linea = f"{icono} {p['emoji']} {p['nombre'].capitalize()} `{stk}`"
            (col_a if i % 2 == 0 else col_b).append(linea)
        embed.add_field(name="\U0001f4e6  STOCK", value="\n".join(col_a), inline=True)
        embed.add_field(name="\u200b", value="\n".join(col_b) if col_b else "\u200b", inline=True)

    embed.set_footer(text="\U0001f7e2 OK  \U0001f7e1 Bajo (\u226410)  \U0001f534 Sin stock")
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
        print(f"\u26a0\ufe0f Error dashboard: {e}", flush=True)


@tasks.loop(seconds=10)
async def loop_dashboard():
    if _db_ready:
        await refrescar_dashboard()

@loop_dashboard.before_loop
async def before_dashboard():
    await bot.wait_until_ready()


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

        await interaction.response.send_message(
            f"✅  Venta registrada: **{cant}x {self.producto.capitalize()}** — **{fmt_monto(total)}**\n"
            f"Cuando quieras cerrar el día usá el botón **Cerrar Día / Generar Depósito** en <#{CHANNEL_DEPOSITOS}>.",
            ephemeral=True
        )

        guild = bot.get_guild(GUILD_ID)
        if guild:
            ts = datetime.now(timezone.utc).strftime("%d/%m %H:%M")
            await log_historial(
                guild,
                f"🛒 `{ts}` **{interaction.user.display_name}** — {self.producto.capitalize()} x{cant} — **{fmt_monto(total)}**"
            )

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

        await interaction.response.send_message(
            f"✅  Gasto registrado: *{self.descripcion.value.strip()}* — **{fmt_monto(monto)}**",
            ephemeral=True
        )

        guild = bot.get_guild(GUILD_ID)
        if guild:
            ts = datetime.now(timezone.utc).strftime("%d/%m %H:%M")
            await log_historial(
                guild,
                f"💸 `{ts}` **{interaction.user.display_name}** — {self.descripcion.value.strip()[:40]} — **{fmt_monto(monto)}**"
            )


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

        await interaction.response.send_message(
            f"✅  Stock ingresado: **+{cant}x {self.producto.capitalize()}**",
            ephemeral=True
        )

        guild = bot.get_guild(GUILD_ID)
        if guild:
            ts = datetime.now(timezone.utc).strftime("%d/%m %H:%M")
            notas_str = f" — {self.notas.value.strip()}" if self.notas.value.strip() else ""
            await log_historial(
                guild,
                f"📦 `{ts}` **{interaction.user.display_name}** — +{cant}x {self.producto.capitalize()}{notas_str}"
            )

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


class ModalAjusteStock(discord.ui.Modal, title="🔧 Ajustar Stock"):
    def __init__(self, producto: str, stock_actual: int):
        super().__init__()
        self.producto = producto
        self.cantidad = discord.ui.TextInput(
            label=f"Stock correcto para: {producto} (actual: {stock_actual})",
            placeholder=f"Ej: {stock_actual}",
            default=str(stock_actual),
            max_length=5
        )
        self.motivo = discord.ui.TextInput(
            label="Motivo del ajuste",
            placeholder="Ej: Corrección de error, merma, etc.",
            max_length=200,
            required=False
        )
        self.add_item(self.cantidad)
        self.add_item(self.motivo)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            nuevo_stock = int(self.cantidad.value.strip())
            assert nuevo_stock >= 0
        except:
            return await interaction.response.send_message("❌ Cantidad inválida.", ephemeral=True)

        await db.ajustar_stock(self.producto, nuevo_stock)
        await interaction.response.send_message(
            f"✅  Stock de **{self.producto.capitalize()}** ajustado a **{nuevo_stock}** unidades.",
            ephemeral=True
        )
        guild = bot.get_guild(GUILD_ID)
        if guild:
            ts = datetime.now(timezone.utc).strftime("%d/%m %H:%M")
            motivo_str = f" — {self.motivo.value.strip()}" if self.motivo.value.strip() else ""
            await log_historial(
                guild,
                f"🔧 `{ts}` **{interaction.user.display_name}** — Ajuste stock {self.producto.capitalize()} → {nuevo_stock}{motivo_str}"
            )
        asyncio.create_task(refrescar_panel_stock())


class SelectProductoBorrar(discord.ui.Select):
    def __init__(self, productos):
        self.prods = {p["nombre"]: p for p in productos}
        options = [
            discord.SelectOption(
                label=p["nombre"].capitalize(),
                value=p["nombre"],
                emoji=p["emoji"] or "📦",
                description=f"Stock: {p['stock']} | Precio base: {fmt_monto(p['precio_base'])}"
            ) for p in productos[:25]
        ]
        super().__init__(placeholder="Seleccioná el producto a borrar...", options=options)

    async def callback(self, interaction: discord.Interaction):
        prod = self.prods[self.values[0]]
        view = ConfirmarBorrarProducto(prod["nombre"], prod["emoji"])
        await interaction.response.send_message(
            f"⚠️  ¿Seguro que querés borrar **{prod['emoji']} {prod['nombre'].capitalize()}**?\n"
            f"Esto lo desactiva — el historial de ventas se mantiene.",
            view=view,
            ephemeral=True
        )


class ConfirmarBorrarProducto(discord.ui.View):
    def __init__(self, nombre: str, emoji: str):
        super().__init__(timeout=30)
        self.nombre = nombre
        self.emoji = emoji

    @discord.ui.button(label="Sí, borrar", style=discord.ButtonStyle.danger)
    async def confirmar(self, interaction: discord.Interaction, button: discord.ui.Button):
        await db.desactivar_producto(self.nombre)
        await interaction.response.send_message(
            f"✅  Producto **{self.emoji} {self.nombre.capitalize()}** eliminado.",
            ephemeral=True
        )
        guild = bot.get_guild(GUILD_ID)
        if guild:
            ts = datetime.now(timezone.utc).strftime("%d/%m %H:%M")
            await log_historial(
                guild,
                f"🗑️ `{ts}` **{interaction.user.display_name}** — Producto eliminado: {self.nombre.capitalize()}"
            )
        asyncio.create_task(refrescar_panel_stock())
        self.stop()

    @discord.ui.button(label="Cancelar", style=discord.ButtonStyle.secondary)
    async def cancelar(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("❌ Cancelado.", ephemeral=True)
        self.stop()


class SelectDepositoConfirmar(discord.ui.Select):
    def __init__(self, depositos):
        self.deps = {str(d["id"]): d for d in depositos}
        options = [
            discord.SelectOption(
                label=f"{d['usuario'].split('#')[0]} — {fmt_monto(d['monto'])}",
                value=str(d["id"]),
                description=f"{d['fecha'][:16].replace('T',' ')}  {d['codigo']}"[:100]
            ) for d in depositos[:25]
        ]
        super().__init__(placeholder="Seleccioná el depósito a confirmar...", options=options)

    async def callback(self, interaction: discord.Interaction):
        dep = self.deps[self.values[0]]
        if dep["confirmado"]:
            return await interaction.response.send_message("✅ Ese depósito ya fue confirmado.", ephemeral=True)

        await db.confirmar_deposito_por_id(dep["id"])

        guild = bot.get_guild(GUILD_ID)
        if guild and dep.get("msg_id"):
            ch_dep = guild.get_channel(CHANNEL_DEPOSITOS)
            if ch_dep:
                try:
                    msg = await ch_dep.fetch_message(int(dep["msg_id"]))
                    await msg.delete()
                except Exception:
                    pass

        await interaction.response.send_message(
            f"✅  Depósito de **{dep['usuario'].split('#')[0]}** por **{fmt_monto(dep['monto'])}** confirmado.",
            ephemeral=True
        )
        if guild:
            ts = datetime.now(timezone.utc).strftime("%d/%m %H:%M")
            await log_historial(
                guild,
                f"✅ `{ts}` Depósito confirmado por admin **{interaction.user.display_name}** — {dep['usuario'].split('#')[0]} **{fmt_monto(dep['monto'])}** `{dep['codigo']}`"
            )
        asyncio.create_task(refrescar_panel_depositos())


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
        elif self.accion == "ajustar":
            if not es_admin(interaction.user):
                return await interaction.response.send_message("❌ Solo admins.", ephemeral=True)
            await interaction.response.send_modal(
                ModalAjusteStock(prod["nombre"], int(prod["stock"]))
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

    @discord.ui.button(label="💰 Cerrar Día / Generar Depósito", style=discord.ButtonStyle.success,
                       emoji="📋", custom_id="deposito_cerrar_dia")
    async def btn_cerrar_dia(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not _db_ready:
            return await interaction.response.send_message("⏳ Bot iniciando...", ephemeral=True)

        ventas_pendientes = await db.get_ventas_sin_depositar(interaction.user.id)

        if not ventas_pendientes:
            return await interaction.response.send_message(
                "✅ No tenés ventas pendientes de depositar.", ephemeral=True
            )

        total = sum(v["total"] for v in ventas_pendientes)
        codigo = gen_codigo()

        detalle_lines = []
        for v in ventas_pendientes:
            ts = v["fecha"][:16].replace("T", " ")
            detalle_lines.append(
                f"▸  `{ts}`  {v['producto'].capitalize()}  x{v['cantidad']}  **{fmt_monto(v['total'])}**"
            )

        guild = bot.get_guild(GUILD_ID)
        ch_dep = guild.get_channel(CHANNEL_DEPOSITOS) if guild else None

        if not ch_dep:
            return await interaction.response.send_message("❌ Canal de depósitos no encontrado.", ephemeral=True)

        dep_embed = discord.Embed(
            title="💰  DEPÓSITO PENDIENTE",
            description=f"{SEP}\nResumen de ventas del día — hay que depositar a la organización.\n{SEP}",
            color=COLOR_ORO
        )
        dep_embed.add_field(name="👤  Vendedor", value=interaction.user.mention, inline=True)
        dep_embed.add_field(name="💵  Total a depositar", value=f"**{fmt_monto(total)}**", inline=True)
        dep_embed.add_field(name="🏷️  Código org.", value=f"**`{codigo}`**", inline=True)
        dep_embed.add_field(
            name=f"🛒  Ventas incluidas ({len(ventas_pendientes)})",
            value="\n".join(detalle_lines[:10]) + ("\n*...y más*" if len(detalle_lines) > 10 else ""),
            inline=False
        )
        dep_embed.add_field(
            name="✅  Confirmación",
            value="Reaccioná con ✅ una vez que hayas depositado el dinero.",
            inline=False
        )
        dep_embed.set_footer(text="Sistema Almacén • Depósito de cierre de día")
        dep_embed.timestamp = datetime.now(timezone.utc)

        dep_msg = await ch_dep.send(embed=dep_embed)
        await dep_msg.add_reaction("✅")

        await db.registrar_deposito(
            total, codigo,
            interaction.user.id, str(interaction.user),
            str(dep_msg.id)
        )
        await db.marcar_ventas_depositadas(interaction.user.id, [v["id"] for v in ventas_pendientes])

        await interaction.response.send_message(
            f"✅ Depósito generado por **{fmt_monto(total)}** con código `{codigo}`.\n"
            f"Fijate en <#{CHANNEL_DEPOSITOS}> y reaccioná con ✅ cuando lo hayas hecho.",
            ephemeral=True
        )

        if guild:
            ts = datetime.now(timezone.utc).strftime("%d/%m %H:%M")
            await log_historial(
                guild,
                f"💰 `{ts}` **{interaction.user.display_name}** — Depósito generado **{fmt_monto(total)}** `{codigo}`"
            )

        asyncio.create_task(refrescar_panel_depositos())

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

    @discord.ui.button(label="Confirmar Depósito", style=discord.ButtonStyle.primary,
                       emoji="🔐", custom_id="deposito_confirmar_admin")
    async def btn_confirmar_admin(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not es_admin(interaction.user):
            return await interaction.response.send_message("❌ Solo admins.", ephemeral=True)
        pendientes = await db.get_depositos_pendientes()
        if not pendientes:
            return await interaction.response.send_message(
                "✅ No hay depósitos pendientes.", ephemeral=True
            )
        view = discord.ui.View(timeout=60)
        view.add_item(SelectDepositoConfirmar(pendientes))
        await interaction.response.send_message(
            "Seleccioná el depósito a confirmar:", view=view, ephemeral=True
        )


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

    @discord.ui.button(label="Ajustar Stock", style=discord.ButtonStyle.danger,
                       emoji="🔧", custom_id="stock_ajustar")
    async def btn_ajustar(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not es_admin(interaction.user):
            return await interaction.response.send_message("❌ Solo admins.", ephemeral=True)
        productos = await db.get_productos()
        if not productos:
            return await interaction.response.send_message("❌ Sin productos.", ephemeral=True)
        view = discord.ui.View(timeout=60)
        view.add_item(SelectProductoStock(productos, "ajustar"))
        await interaction.response.send_message(
            "Seleccioná el producto a ajustar:", view=view, ephemeral=True
        )

    @discord.ui.button(label="Borrar Producto", style=discord.ButtonStyle.danger,
                       emoji="🗑️", custom_id="stock_borrar_producto")
    async def btn_borrar(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not es_admin(interaction.user):
            return await interaction.response.send_message("❌ Solo admins.", ephemeral=True)
        productos = await db.get_productos()
        if not productos:
            return await interaction.response.send_message("❌ Sin productos.", ephemeral=True)
        view = discord.ui.View(timeout=60)
        view.add_item(SelectProductoBorrar(productos))
        await interaction.response.send_message(
            "Seleccioná el producto a borrar:", view=view, ephemeral=True
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
            dep = "⏳" if not v.get("depositado") else "✅"
            lines.append(
                f"{dep}  `{ts}`  **{nombre}**  —  {v['producto'].capitalize()}  x{v['cantidad']}  **{fmt_monto(v['total'])}**"
            )
        embed.add_field(name="📋  Últimas ventas  (⏳ sin depositar  ✅ depositado)", value="\n".join(lines), inline=False)
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

    embed = discord.Embed(
        title="💰  PANEL DE DEPÓSITOS",
        description=(
            f"{SEP}\n"
            "Acá se generan los depósitos al **cerrar el día**.\n"
            "Cada vendedor genera el suyo con el total de sus ventas.\n\n"
            "**¿Cómo funciona?**\n"
            "1️⃣  Vendés durante el día normalmente\n"
            "2️⃣  Al terminar, presioná **Cerrar Día / Generar Depósito**\n"
            "3️⃣  Depositás en el juego con el código generado\n"
            "4️⃣  Reaccionás con ✅ al mensaje para confirmar\n"
            f"{SEP}"
        ),
        color=COLOR_ORO
    )

    embed.add_field(
        name="✅  Total en org",
        value=f"**{fmt_monto(total_dep)}**",
        inline=False
    )

    embed.set_footer(text="Sistema Almacén  •  Depósitos de cierre de día")
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
            elif stk <= 10:
                ind = "🟡"
            else:
                ind = "🟢"
            lines.append(f"{ind}  {p['emoji']}  **{p['nombre'].capitalize()}**  —  `{stk}` unidades  ·  base: {fmt_monto(p['precio_base'])}")
        embed.add_field(name="📋  Inventario", value="\n".join(lines), inline=False)
    embed.set_footer(text="🟢 OK  🟡 Bajo (≤10)  🔴 Sin stock  •  Sistema Almacén")
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
            await ch.purge(limit=50)
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
#  CONFIRMACIÓN DE DEPÓSITO POR REACCIÓN ✅
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

    await db.confirmar_deposito(str(payload.message_id))

    confirmador = guild.get_member(payload.user_id)
    nombre_conf = confirmador.display_name if confirmador else "alguien"

    try:
        msg = await channel.fetch_message(payload.message_id)
        await msg.delete()
    except Exception:
        pass

    ts = datetime.now(timezone.utc).strftime("%d/%m %H:%M")
    await log_historial(
        guild,
        f"✅ `{ts}` Depósito confirmado por **{nombre_conf}** — **{fmt_monto(deposito['monto'])}** `{deposito['codigo']}`"
    )

    await refrescar_panel_depositos()


# ══════════════════════════════════════════════════════════
#  SLASH COMMANDS
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
            await ch.purge(limit=50)
        await _refrescar_panel(config_key, canal_id, build_fn, view_cls, purge_on_new=True)

    await db.set_config("dashboard_msg_id", "")
    ch_dash = guild.get_channel(CHANNEL_DASHBOARD)
    if ch_dash:
        await ch_dash.purge(limit=20)
    await refrescar_dashboard()

    await interaction.followup.send("✅ Todos los paneles fueron reseteados.", ephemeral=True)


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


@bot.tree.command(name="resetdb", description="[ADMIN] Borra todos los datos y resetea el bot desde cero")
async def cmd_resetdb(interaction: discord.Interaction):
    if not es_admin(interaction.user):
        return await interaction.response.send_message("❌ Solo admins.", ephemeral=True)

    class ConfirmarReset(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=30)

        @discord.ui.button(label="⚠️ SÍ, BORRAR TODO", style=discord.ButtonStyle.danger)
        async def confirmar(self, inter: discord.Interaction, button: discord.ui.Button):
            await inter.response.defer(ephemeral=True)
            await db._q("DELETE FROM ventas")
            await db._q("DELETE FROM gastos")
            await db._q("DELETE FROM depositos")
            await db._q("DELETE FROM ingresos_stock")
            await db._q("DELETE FROM config")
            await db._q("UPDATE productos SET stock=0")

            guild = inter.guild
            for config_key, canal_id, build_fn, view_cls in [
                ("panel_ventas_id",    CHANNEL_VENTAS,    build_embed_ventas,    PanelVentas),
                ("panel_gastos_id",    CHANNEL_GASTOS,    build_embed_gastos,    PanelGastos),
                ("panel_depositos_id", CHANNEL_DEPOSITOS, build_embed_depositos, PanelDepositos),
                ("panel_stock_id",     CHANNEL_STOCK,     build_embed_stock,     PanelStock),
            ]:
                ch = guild.get_channel(canal_id)
                if ch:
                    await ch.purge(limit=50)
                await _refrescar_panel(config_key, canal_id, build_fn, view_cls, purge_on_new=True)

            ch_dash = guild.get_channel(CHANNEL_DASHBOARD)
            if ch_dash:
                await ch_dash.purge(limit=20)
            await refrescar_dashboard()

            ch_hist = guild.get_channel(CHANNEL_HISTORIAL)
            if ch_hist:
                await ch_hist.purge(limit=100)
                ts = datetime.now(timezone.utc).strftime("%d/%m %H:%M")
                await ch_hist.send(f"🔄 `{ts}` **Reset completo** — Bot iniciado desde cero.")

            await inter.followup.send("✅ Todo reseteado. El bot arranca desde cero.", ephemeral=True)
            self.stop()

        @discord.ui.button(label="Cancelar", style=discord.ButtonStyle.secondary)
        async def cancelar(self, inter: discord.Interaction, button: discord.ui.Button):
            await inter.response.send_message("❌ Reset cancelado.", ephemeral=True)
            self.stop()

    await interaction.response.send_message(
        "⚠️  **¿Seguro que querés borrar TODOS los datos?**\n"
        "Esto elimina ventas, gastos, depósitos e historial. No hay vuelta atrás.",
        view=ConfirmarReset(),
        ephemeral=True
    )


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
            await ch.purge(limit=50)
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

    if not loop_self_ping.is_running():
        loop_self_ping.start()
        print(f"✅ Self-ping loop iniciado {'(URL: ' + RENDER_URL + ')' if RENDER_URL else '(sin RENDER_EXTERNAL_URL)'}", flush=True)


@bot.event
async def on_ready():
    print(f"✅ Bot conectado: {bot.user}", flush=True)
    bot.add_view(PanelVentas())
    bot.add_view(PanelGastos())
    bot.add_view(PanelDepositos())
    bot.add_view(PanelStock())
    asyncio.create_task(startup())


# ══════════════════════════════════════════════════════════
#  RECONEXIÓN AUTOMÁTICA
# ══════════════════════════════════════════════════════════
@bot.event
async def on_disconnect():
    print("⚠️ Bot desconectado — esperando reconexión automática de discord.py...", flush=True)

@bot.event
async def on_resumed():
    print("✅ Sesión resumida correctamente.", flush=True)


bot.run(TOKEN, reconnect=True)
