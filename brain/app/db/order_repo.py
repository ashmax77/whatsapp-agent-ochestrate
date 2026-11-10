import json
import sqlite3
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from app.config import settings
from app.db.models import Customer, Handoff, MessageLog, Order, OrderItem, OrderStatus
from app.services import clock

log = logging.getLogger("brain.order_repo")

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS customers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL UNIQUE,
    push_name TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_no TEXT NOT NULL UNIQUE,
    customer_id INTEGER NOT NULL,
    branch_id TEXT NOT NULL,
    fulfilment TEXT NOT NULL,
    address TEXT,
    lat REAL,
    lng REAL,
    zone_id TEXT,
    subtotal INTEGER NOT NULL,
    delivery_fee INTEGER NOT NULL,
    discount INTEGER NOT NULL,
    total INTEGER NOT NULL,
    promo_code TEXT,
    status TEXT NOT NULL DEFAULT 'new',
    created_at TEXT NOT NULL,
    FOREIGN KEY (customer_id) REFERENCES customers(id)
);

CREATE TABLE IF NOT EXISTS order_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL,
    item_id TEXT NOT NULL,
    name_snapshot TEXT NOT NULL,
    size TEXT NOT NULL,
    qty INTEGER NOT NULL,
    unit_price INTEGER NOT NULL,
    line_total INTEGER NOT NULL,
    notes TEXT,
    combo_choices_json TEXT,
    FOREIGN KEY (order_id) REFERENCES orders(id)
);

CREATE TABLE IF NOT EXISTS handoffs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    branch_id TEXT,
    reason TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    created_at TEXT NOT NULL,
    resolved_at TEXT
);

CREATE TABLE IF NOT EXISTS message_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    direction TEXT NOT NULL,
    type TEXT NOT NULL,
    text TEXT,
    trace_id TEXT,
    created_at TEXT NOT NULL
);
"""


class OrderRepo:
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or settings.DB_PATH
        self.init_db()

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(SCHEMA_SQL)
            conn.commit()

    def get_or_create_customer(self, user_id: str, push_name: Optional[str] = None) -> Customer:
        now_iso = clock.now().isoformat()
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM customers WHERE user_id = ?", (user_id,)).fetchone()
            if row:
                if push_name and push_name != row["push_name"]:
                    conn.execute("UPDATE customers SET push_name = ? WHERE id = ?", (push_name, row["id"]))
                    conn.commit()
                return Customer(
                    id=row["id"],
                    user_id=row["user_id"],
                    push_name=push_name or row["push_name"],
                    created_at=datetime.fromisoformat(row["created_at"]),
                )

            cur = conn.execute(
                "INSERT INTO customers (user_id, push_name, created_at) VALUES (?, ?, ?)",
                (user_id, push_name, now_iso),
            )
            conn.commit()
            return Customer(
                id=cur.lastrowid,
                user_id=user_id,
                push_name=push_name,
                created_at=datetime.fromisoformat(now_iso),
            )

    def _next_order_no(self, conn: sqlite3.Connection, now_dt: datetime) -> str:
        date_prefix = f"PH-{now_dt.strftime('%Y%m%d')}-"
        row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM orders WHERE order_no LIKE ?",
            (f"{date_prefix}%",),
        ).fetchone()
        seq = (int(row["cnt"]) if row else 0) + 1
        return f"{date_prefix}{seq:04d}"

    def create_order(
        self,
        user_id: str,
        branch_id: str,
        fulfilment: str,
        subtotal: int,
        delivery_fee: int,
        discount: int,
        total: int,
        items: List[Dict[str, Any]],
        address: Optional[str] = None,
        lat: Optional[float] = None,
        lng: Optional[float] = None,
        zone_id: Optional[str] = None,
        promo_code: Optional[str] = None,
        push_name: Optional[str] = None,
        now_dt: Optional[datetime] = None,
    ) -> Order:
        current = clock.now(now_dt)
        now_iso = current.isoformat()
        customer = self.get_or_create_customer(user_id, push_name=push_name)

        with self._connect() as conn:
            order_no = self._next_order_no(conn, current)
            cur = conn.execute(
                """
                INSERT INTO orders (
                    order_no, customer_id, branch_id, fulfilment, address, lat, lng,
                    zone_id, subtotal, delivery_fee, discount, total, promo_code, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    order_no,
                    customer.id,
                    branch_id,
                    fulfilment,
                    address,
                    lat,
                    lng,
                    zone_id,
                    int(subtotal),
                    int(delivery_fee),
                    int(discount),
                    int(total),
                    promo_code,
                    OrderStatus.NEW.value,
                    now_iso,
                ),
            )
            order_id = int(cur.lastrowid)

            saved_items: List[OrderItem] = []
            for item in items:
                combo_json = (
                    json.dumps(item["combo_choices"], sort_keys=True)
                    if item.get("combo_choices")
                    else None
                )
                ic = conn.execute(
                    """
                    INSERT INTO order_items (
                        order_id, item_id, name_snapshot, size, qty,
                        unit_price, line_total, notes, combo_choices_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        order_id,
                        item["item_id"],
                        item["name"],
                        item["size"],
                        int(item["qty"]),
                        int(item["unit_price"]),
                        int(item["line_total"]),
                        item.get("notes"),
                        combo_json,
                    ),
                )
                saved_items.append(
                    OrderItem(
                        id=int(ic.lastrowid),
                        order_id=order_id,
                        item_id=item["item_id"],
                        name_snapshot=item["name"],
                        size=item["size"],
                        qty=int(item["qty"]),
                        unit_price=int(item["unit_price"]),
                        line_total=int(item["line_total"]),
                        notes=item.get("notes"),
                        combo_choices_json=combo_json,
                    )
                )
            conn.commit()

        return Order(
            id=order_id,
            order_no=order_no,
            customer_id=customer.id,
            user_id=user_id,
            branch_id=branch_id,
            fulfilment=fulfilment,  # type: ignore
            address=address,
            lat=lat,
            lng=lng,
            zone_id=zone_id,
            subtotal=int(subtotal),
            delivery_fee=int(delivery_fee),
            discount=int(discount),
            total=int(total),
            promo_code=promo_code,
            status=OrderStatus.NEW,
            created_at=current,
            items=saved_items,
        )

    def get_order_by_no(self, order_no: str) -> Optional[Order]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT o.*, c.user_id AS user_id
                FROM orders o
                JOIN customers c ON c.id = o.customer_id
                WHERE o.order_no = ?
                """,
                (order_no.strip().upper(),),
            ).fetchone()
            if not row:
                return None

            item_rows = conn.execute(
                "SELECT * FROM order_items WHERE order_id = ? ORDER BY id ASC",
                (row["id"],),
            ).fetchall()

            items = [
                OrderItem(
                    id=ir["id"],
                    order_id=ir["order_id"],
                    item_id=ir["item_id"],
                    name_snapshot=ir["name_snapshot"],
                    size=ir["size"],
                    qty=ir["qty"],
                    unit_price=ir["unit_price"],
                    line_total=ir["line_total"],
                    notes=ir["notes"],
                    combo_choices_json=ir["combo_choices_json"],
                )
                for ir in item_rows
            ]

            return Order(
                id=row["id"],
                order_no=row["order_no"],
                customer_id=row["customer_id"],
                user_id=row["user_id"],
                branch_id=row["branch_id"],
                fulfilment=row["fulfilment"],
                address=row["address"],
                lat=row["lat"],
                lng=row["lng"],
                zone_id=row["zone_id"],
                subtotal=row["subtotal"],
                delivery_fee=row["delivery_fee"],
                discount=row["discount"],
                total=row["total"],
                promo_code=row["promo_code"],
                status=OrderStatus(row["status"]),
                created_at=datetime.fromisoformat(row["created_at"]),
                items=items,
            )

    def list_orders_for_user(self, user_id: str) -> List[Order]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT o.order_no
                FROM orders o
                JOIN customers c ON c.id = o.customer_id
                WHERE c.user_id = ?
                ORDER BY o.id DESC
                """,
                (user_id,),
            ).fetchall()
        return [o for r in rows if (o := self.get_order_by_no(r["order_no"])) is not None]


order_repo = OrderRepo()

