"""
Database — Almacén Bot
SQLite async con aiosqlite
"""
import aiosqlite
import os
from datetime import datetime, timezone

DB_PATH = os.getenv("DB_PATH", "almacen.db")


class Database:
    def __init__(self):
        self.db = None

    async def init(self):
        self.db = await aiosqlite.connect(DB_PATH)
        self.db.row_factory = aiosqlite.Row
        await self.db.execute("PRAGMA journal_mode=WAL")
        await self._create_tables()
        await self._seed_productos()
        print("✅ Base de datos lista", flush=True)

    async def _create_tables(self):
        await self.db.executescript("""
            CREATE TABLE IF NOT EXISTS config (
                key   TEXT PRIMARY KEY,
                value TEXT
            );

            CREATE TABLE IF NOT EXISTS productos (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre      TEXT UNIQUE NOT NULL,
                emoji       TEXT DEFAULT '📦',
                precio_base INTEGER DEFAULT 0,
                stock       INTEGER DEFAULT 0,
                activo      INTEGER DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS ventas (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                producto    TEXT NOT NULL,
                cantidad    INTEGER NOT NULL,
                precio_unit INTEGER NOT NULL,
                total       INTEGER NOT NULL,
                usuario_id  INTEGER NOT NULL,
                usuario     TEXT NOT NULL,
                fecha       TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS gastos (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                descripcion TEXT NOT NULL,
                monto       INTEGER NOT NULL,
                usuario_id  INTEGER NOT NULL,
                usuario     TEXT NOT NULL,
                fecha       TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS depositos (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                monto       INTEGER NOT NULL,
                codigo      TEXT NOT NULL,
                usuario_id  INTEGER NOT NULL,
                usuario     TEXT NOT NULL,
                confirmado  INTEGER DEFAULT 0,
                fecha       TEXT NOT NULL,
                msg_id      TEXT
            );

            CREATE TABLE IF NOT EXISTS ingresos_stock (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                producto    TEXT NOT NULL,
                cantidad    INTEGER NOT NULL,
                usuario_id  INTEGER NOT NULL,
                usuario     TEXT NOT NULL,
                notas       TEXT,
                fecha       TEXT NOT NULL
            );
        """)
        await self.db.commit()

    async def _seed_productos(self):
        """Productos iniciales del almacén"""
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
        for nombre, emoji, precio in productos_default:
            await self.db.execute(
                "INSERT OR IGNORE INTO productos (nombre, emoji, precio_base) VALUES (?, ?, ?)",
                (nombre, emoji, precio)
            )
        await self.db.commit()

    # ──────────────── CONFIG ────────────────

    async def get_config(self, key: str) -> str | None:
        async with self.db.execute("SELECT value FROM config WHERE key=?", (key,)) as cur:
            row = await cur.fetchone()
            return row["value"] if row else None

    async def set_config(self, key: str, value: str):
        await self.db.execute(
            "INSERT INTO config(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value)
        )
        await self.db.commit()

    # ──────────────── PRODUCTOS ────────────────

    async def get_productos(self) -> list:
        async with self.db.execute("SELECT * FROM productos WHERE activo=1 ORDER BY nombre") as cur:
            return await cur.fetchall()

    async def get_producto(self, nombre: str):
        async with self.db.execute("SELECT * FROM productos WHERE nombre=? AND activo=1", (nombre,)) as cur:
            return await cur.fetchone()

    async def agregar_producto(self, nombre: str, emoji: str, precio_base: int):
        await self.db.execute(
            "INSERT INTO productos (nombre, emoji, precio_base, stock) VALUES (?, ?, ?, 0)",
            (nombre.lower().strip(), emoji, precio_base)
        )
        await self.db.commit()

    async def actualizar_precio_base(self, nombre: str, precio: int):
        await self.db.execute(
            "UPDATE productos SET precio_base=? WHERE nombre=?", (precio, nombre)
        )
        await self.db.commit()

    async def sumar_stock(self, nombre: str, cantidad: int):
        await self.db.execute(
            "UPDATE productos SET stock = stock + ? WHERE nombre=?", (cantidad, nombre)
        )
        await self.db.commit()

    async def restar_stock(self, nombre: str, cantidad: int) -> bool:
        async with self.db.execute("SELECT stock FROM productos WHERE nombre=?", (nombre,)) as cur:
            row = await cur.fetchone()
        if not row or row["stock"] < cantidad:
            return False
        await self.db.execute(
            "UPDATE productos SET stock = stock - ? WHERE nombre=?", (cantidad, nombre)
        )
        await self.db.commit()
        return True

    # ──────────────── VENTAS ────────────────

    async def registrar_venta(self, producto: str, cantidad: int, precio_unit: int,
                               usuario_id: int, usuario: str) -> int:
        total = cantidad * precio_unit
        now = datetime.now(timezone.utc).isoformat()
        async with self.db.execute(
            "INSERT INTO ventas (producto, cantidad, precio_unit, total, usuario_id, usuario, fecha) VALUES (?,?,?,?,?,?,?)",
            (producto, cantidad, precio_unit, total, usuario_id, usuario, now)
        ) as cur:
            rowid = cur.lastrowid
        await self.db.commit()
        return total

    async def get_ventas(self, limit: int = 20, usuario_id: int = None) -> list:
        if usuario_id:
            async with self.db.execute(
                "SELECT * FROM ventas WHERE usuario_id=? ORDER BY fecha DESC LIMIT ?", (usuario_id, limit)
            ) as cur:
                return await cur.fetchall()
        async with self.db.execute("SELECT * FROM ventas ORDER BY fecha DESC LIMIT ?", (limit,)) as cur:
            return await cur.fetchall()

    async def get_total_ventas(self) -> int:
        async with self.db.execute("SELECT COALESCE(SUM(total),0) as s FROM ventas") as cur:
            row = await cur.fetchone()
            return int(row["s"])

    async def get_ventas_por_usuario(self) -> list:
        async with self.db.execute(
            "SELECT usuario, usuario_id, COALESCE(SUM(total),0) as total, COUNT(*) as cant FROM ventas GROUP BY usuario_id ORDER BY total DESC"
        ) as cur:
            return await cur.fetchall()

    async def get_ventas_por_producto(self) -> list:
        async with self.db.execute(
            "SELECT producto, COALESCE(SUM(cantidad),0) as unidades, COALESCE(SUM(total),0) as total FROM ventas GROUP BY producto ORDER BY total DESC"
        ) as cur:
            return await cur.fetchall()

    # ──────────────── GASTOS ────────────────

    async def registrar_gasto(self, descripcion: str, monto: int,
                               usuario_id: int, usuario: str) -> int:
        now = datetime.now(timezone.utc).isoformat()
        await self.db.execute(
            "INSERT INTO gastos (descripcion, monto, usuario_id, usuario, fecha) VALUES (?,?,?,?,?)",
            (descripcion, monto, usuario_id, usuario, now)
        )
        await self.db.commit()
        return monto

    async def get_gastos(self, limit: int = 20) -> list:
        async with self.db.execute("SELECT * FROM gastos ORDER BY fecha DESC LIMIT ?", (limit,)) as cur:
            return await cur.fetchall()

    async def get_total_gastos(self) -> int:
        async with self.db.execute("SELECT COALESCE(SUM(monto),0) as s FROM gastos") as cur:
            row = await cur.fetchone()
            return int(row["s"])

    async def get_gastos_por_usuario(self) -> list:
        async with self.db.execute(
            "SELECT usuario, usuario_id, COALESCE(SUM(monto),0) as total, COUNT(*) as cant FROM gastos GROUP BY usuario_id ORDER BY total DESC"
        ) as cur:
            return await cur.fetchall()

    # ──────────────── DEPÓSITOS ────────────────

    async def registrar_deposito(self, monto: int, codigo: str,
                                  usuario_id: int, usuario: str, msg_id: str) -> int:
        now = datetime.now(timezone.utc).isoformat()
        async with self.db.execute(
            "INSERT INTO depositos (monto, codigo, usuario_id, usuario, confirmado, fecha, msg_id) VALUES (?,?,?,?,0,?,?)",
            (monto, codigo, usuario_id, usuario, now, msg_id)
        ) as cur:
            rowid = cur.lastrowid
        await self.db.commit()
        return rowid

    async def confirmar_deposito(self, deposito_id: int):
        await self.db.execute(
            "UPDATE depositos SET confirmado=1 WHERE id=?", (deposito_id,)
        )
        await self.db.commit()

    async def get_deposito_por_msg(self, msg_id: str):
        async with self.db.execute(
            "SELECT * FROM depositos WHERE msg_id=?", (msg_id,)
        ) as cur:
            return await cur.fetchone()

    async def get_total_depositos(self) -> int:
        async with self.db.execute("SELECT COALESCE(SUM(monto),0) as s FROM depositos WHERE confirmado=1") as cur:
            row = await cur.fetchone()
            return int(row["s"])

    async def get_depositos(self, limit: int = 10) -> list:
        async with self.db.execute("SELECT * FROM depositos ORDER BY fecha DESC LIMIT ?", (limit,)) as cur:
            return await cur.fetchall()

    # ──────────────── INGRESOS DE STOCK ────────────────

    async def registrar_ingreso_stock(self, producto: str, cantidad: int,
                                       usuario_id: int, usuario: str, notas: str = None):
        now = datetime.now(timezone.utc).isoformat()
        await self.db.execute(
            "INSERT INTO ingresos_stock (producto, cantidad, usuario_id, usuario, notas, fecha) VALUES (?,?,?,?,?,?)",
            (producto, cantidad, usuario_id, usuario, notas, now)
        )
        await self.db.commit()

    async def get_ingresos_stock(self, limit: int = 20) -> list:
        async with self.db.execute("SELECT * FROM ingresos_stock ORDER BY fecha DESC LIMIT ?", (limit,)) as cur:
            return await cur.fetchall()

    # ──────────────── RESUMEN ────────────────

    async def get_balance(self) -> dict:
        total_ventas = await self.get_total_ventas()
        total_gastos = await self.get_total_gastos()
        total_depositos = await self.get_total_depositos()
        return {
            "ventas": total_ventas,
            "gastos": total_gastos,
            "depositos": total_depositos,
            "neto": total_ventas - total_gastos,
        }

    async def get_historial_general(self, limit: int = 15) -> list:
        """Mezcla ventas, gastos y depósitos ordenados por fecha"""
        async with self.db.execute(f"""
            SELECT 'venta' as tipo, fecha, usuario, total as monto, producto as detalle FROM ventas
            UNION ALL
            SELECT 'gasto' as tipo, fecha, usuario, -monto as monto, descripcion as detalle FROM gastos
            UNION ALL
            SELECT 'deposito' as tipo, fecha, usuario, monto, codigo as detalle FROM depositos WHERE confirmado=1
            ORDER BY fecha DESC LIMIT {limit}
        """) as cur:
            return await cur.fetchall()
