"""
Database — Almacén Bot
Turso (libSQL) con libsql-client async
"""
import os
import libsql_client
from datetime import datetime, timezone

TURSO_URL   = os.getenv("TURSO_URL")    # libsql://tu-db.turso.io
TURSO_TOKEN = os.getenv("TURSO_TOKEN")  # token de autenticación


class Database:
    def __init__(self):
        self.client = None

    async def init(self):
        self.client = libsql_client.create_client(
            url=TURSO_URL,
            auth_token=TURSO_TOKEN,
        )
        await self._create_tables()
        await self._seed_productos()
        print("✅ Base de datos Turso lista", flush=True)

    async def _q(self, sql: str, args: tuple = ()):
        """Ejecuta una query y devuelve el ResultSet."""
        return await self.client.execute(libsql_client.Statement(sql, list(args)))

    async def _rows(self, sql: str, args: tuple = ()):
        """Devuelve las filas como lista de dicts."""
        rs = await self._q(sql, args)
        cols = rs.columns
        return [dict(zip(cols, row)) for row in rs.rows]

    async def _row(self, sql: str, args: tuple = ()):
        """Devuelve una sola fila como dict, o None."""
        rows = await self._rows(sql, args)
        return rows[0] if rows else None

    async def _create_tables(self):
        stmts = [
            libsql_client.Statement("""
                CREATE TABLE IF NOT EXISTS config (
                    key   TEXT PRIMARY KEY,
                    value TEXT
                )
            """),
            libsql_client.Statement("""
                CREATE TABLE IF NOT EXISTS productos (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    nombre      TEXT UNIQUE NOT NULL,
                    emoji       TEXT DEFAULT '📦',
                    precio_base INTEGER DEFAULT 0,
                    stock       INTEGER DEFAULT 0,
                    activo      INTEGER DEFAULT 1
                )
            """),
            libsql_client.Statement("""
                CREATE TABLE IF NOT EXISTS ventas (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    producto    TEXT NOT NULL,
                    cantidad    INTEGER NOT NULL,
                    precio_unit INTEGER NOT NULL,
                    total       INTEGER NOT NULL,
                    usuario_id  INTEGER NOT NULL,
                    usuario     TEXT NOT NULL,
                    fecha       TEXT NOT NULL
                )
            """),
            libsql_client.Statement("""
                CREATE TABLE IF NOT EXISTS gastos (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    descripcion TEXT NOT NULL,
                    monto       INTEGER NOT NULL,
                    usuario_id  INTEGER NOT NULL,
                    usuario     TEXT NOT NULL,
                    fecha       TEXT NOT NULL
                )
            """),
            libsql_client.Statement("""
                CREATE TABLE IF NOT EXISTS depositos (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    monto       INTEGER NOT NULL,
                    codigo      TEXT NOT NULL,
                    usuario_id  INTEGER NOT NULL,
                    usuario     TEXT NOT NULL,
                    confirmado  INTEGER DEFAULT 0,
                    fecha       TEXT NOT NULL,
                    msg_id      TEXT
                )
            """),
            libsql_client.Statement("""
                CREATE TABLE IF NOT EXISTS ingresos_stock (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    producto    TEXT NOT NULL,
                    cantidad    INTEGER NOT NULL,
                    usuario_id  INTEGER NOT NULL,
                    usuario     TEXT NOT NULL,
                    notas       TEXT,
                    fecha       TEXT NOT NULL
                )
            """),
        ]
        await self.client.batch(stmts)
        print("✅ Tablas verificadas", flush=True)

    async def _seed_productos(self):
        productos_default = [
            ("arqui",    "🏗️",  0),
            ("super",    "⛽",   0),
            ("barbe",    "🍖",   0),
            ("tatu",     "🐊",   0),
            ("lico",     "🦎",   0),
            ("vintage",  "🍷",   0),
            ("cargas",   "🔋",   0),
            ("bong",     "💨",   0),
            ("pcp",      "💊",   0),
            ("galleta",  "🍪",   0),
            ("gaso",     "⛽",   0),
            ("ropa",     "👕",   0),
            ("farmacia", "💊",   0),
        ]
        stmts = [
            libsql_client.Statement(
                "INSERT OR IGNORE INTO productos (nombre, emoji, precio_base) VALUES (?, ?, ?)",
                [nombre, emoji, precio]
            )
            for nombre, emoji, precio in productos_default
        ]
        await self.client.batch(stmts)

    # ──────────────── CONFIG ────────────────

    async def get_config(self, key: str) -> str | None:
        row = await self._row("SELECT value FROM config WHERE key=?", (key,))
        return row["value"] if row else None

    async def set_config(self, key: str, value: str):
        await self._q(
            "INSERT INTO config(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value)
        )

    # ──────────────── PRODUCTOS ────────────────

    async def get_productos(self) -> list:
        return await self._rows("SELECT * FROM productos WHERE activo=1 ORDER BY nombre")

    async def get_producto(self, nombre: str):
        return await self._row("SELECT * FROM productos WHERE nombre=? AND activo=1", (nombre,))

    async def agregar_producto(self, nombre: str, emoji: str, precio_base: int):
        await self._q(
            "INSERT INTO productos (nombre, emoji, precio_base, stock) VALUES (?, ?, ?, 0)",
            (nombre.lower().strip(), emoji, precio_base)
        )

    async def actualizar_precio_base(self, nombre: str, precio: int):
        await self._q("UPDATE productos SET precio_base=? WHERE nombre=?", (precio, nombre))

    async def sumar_stock(self, nombre: str, cantidad: int):
        await self._q("UPDATE productos SET stock = stock + ? WHERE nombre=?", (cantidad, nombre))

    async def restar_stock(self, nombre: str, cantidad: int) -> bool:
        row = await self._row("SELECT stock FROM productos WHERE nombre=?", (nombre,))
        if not row or int(row["stock"]) < cantidad:
            return False
        await self._q("UPDATE productos SET stock = stock - ? WHERE nombre=?", (cantidad, nombre))
        return True

    # ──────────────── VENTAS ────────────────

    async def registrar_venta(self, producto: str, cantidad: int, precio_unit: int,
                               usuario_id: int, usuario: str) -> int:
        total = cantidad * precio_unit
        now = datetime.now(timezone.utc).isoformat()
        await self._q(
            "INSERT INTO ventas (producto, cantidad, precio_unit, total, usuario_id, usuario, fecha) VALUES (?,?,?,?,?,?,?)",
            (producto, cantidad, precio_unit, total, usuario_id, usuario, now)
        )
        return total

    async def get_ventas(self, limit: int = 20, usuario_id: int = None) -> list:
        if usuario_id:
            return await self._rows(
                "SELECT * FROM ventas WHERE usuario_id=? ORDER BY fecha DESC LIMIT ?",
                (usuario_id, limit)
            )
        return await self._rows("SELECT * FROM ventas ORDER BY fecha DESC LIMIT ?", (limit,))

    async def get_total_ventas(self) -> int:
        row = await self._row("SELECT COALESCE(SUM(total),0) as s FROM ventas")
        return int(row["s"]) if row else 0

    async def get_ventas_por_usuario(self) -> list:
        return await self._rows(
            "SELECT usuario, usuario_id, COALESCE(SUM(total),0) as total, COUNT(*) as cant "
            "FROM ventas GROUP BY usuario_id ORDER BY total DESC"
        )

    async def get_ventas_por_producto(self) -> list:
        return await self._rows(
            "SELECT producto, COALESCE(SUM(cantidad),0) as unidades, COALESCE(SUM(total),0) as total "
            "FROM ventas GROUP BY producto ORDER BY total DESC"
        )

    # ──────────────── GASTOS ────────────────

    async def registrar_gasto(self, descripcion: str, monto: int,
                               usuario_id: int, usuario: str) -> int:
        now = datetime.now(timezone.utc).isoformat()
        await self._q(
            "INSERT INTO gastos (descripcion, monto, usuario_id, usuario, fecha) VALUES (?,?,?,?,?)",
            (descripcion, monto, usuario_id, usuario, now)
        )
        return monto

    async def get_gastos(self, limit: int = 20) -> list:
        return await self._rows("SELECT * FROM gastos ORDER BY fecha DESC LIMIT ?", (limit,))

    async def get_total_gastos(self) -> int:
        row = await self._row("SELECT COALESCE(SUM(monto),0) as s FROM gastos")
        return int(row["s"]) if row else 0

    async def get_gastos_por_usuario(self) -> list:
        return await self._rows(
            "SELECT usuario, usuario_id, COALESCE(SUM(monto),0) as total, COUNT(*) as cant "
            "FROM gastos GROUP BY usuario_id ORDER BY total DESC"
        )

    # ──────────────── DEPÓSITOS ────────────────

    async def registrar_deposito(self, monto: int, codigo: str,
                                  usuario_id: int, usuario: str, msg_id: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        await self._q(
            "INSERT INTO depositos (monto, codigo, usuario_id, usuario, confirmado, fecha, msg_id) VALUES (?,?,?,?,0,?,?)",
            (monto, codigo, usuario_id, usuario, now, msg_id)
        )

    async def confirmar_deposito(self, msg_id: str):
        await self._q("UPDATE depositos SET confirmado=1 WHERE msg_id=?", (msg_id,))

    async def get_deposito_por_msg(self, msg_id: str):
        return await self._row("SELECT * FROM depositos WHERE msg_id=?", (msg_id,))

    async def get_total_depositos(self) -> int:
        row = await self._row("SELECT COALESCE(SUM(monto),0) as s FROM depositos WHERE confirmado=1")
        return int(row["s"]) if row else 0

    async def get_depositos(self, limit: int = 15) -> list:
        return await self._rows("SELECT * FROM depositos ORDER BY fecha DESC LIMIT ?", (limit,))

    # ──────────────── INGRESOS DE STOCK ────────────────

    async def registrar_ingreso_stock(self, producto: str, cantidad: int,
                                       usuario_id: int, usuario: str, notas: str = None):
        now = datetime.now(timezone.utc).isoformat()
        await self._q(
            "INSERT INTO ingresos_stock (producto, cantidad, usuario_id, usuario, notas, fecha) VALUES (?,?,?,?,?,?)",
            (producto, cantidad, usuario_id, usuario, notas, now)
        )

    # ──────────────── RESUMEN ────────────────

    async def get_balance(self) -> dict:
        total_ventas    = await self.get_total_ventas()
        total_gastos    = await self.get_total_gastos()
        total_depositos = await self.get_total_depositos()
        row_pend        = await self._row("SELECT COALESCE(SUM(monto),0) as s FROM depositos WHERE confirmado=0")
        total_pendiente = int(row_pend["s"]) if row_pend else 0
        return {
            "ventas":    total_ventas,
            "gastos":    total_gastos,
            "depositos": total_depositos,
            "pendiente": total_pendiente,
            "neto":      total_ventas - total_gastos,
        }

    async def get_historial_general(self, limit: int = 15) -> list:
        return await self._rows(f"""
            SELECT 'venta' as tipo, fecha, usuario, total as monto, producto as detalle FROM ventas
            UNION ALL
            SELECT 'gasto' as tipo, fecha, usuario, monto, descripcion as detalle FROM gastos
            UNION ALL
            SELECT 'deposito' as tipo, fecha, usuario, monto, codigo as detalle FROM depositos WHERE confirmado=1
            ORDER BY fecha DESC LIMIT {int(limit)}
        """)
