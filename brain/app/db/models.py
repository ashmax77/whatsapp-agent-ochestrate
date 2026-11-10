from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field


class OrderStatus(str, Enum):
    NEW = "new"
    ACCEPTED = "accepted"
    PREPARING = "preparing"
    OUT_FOR_DELIVERY = "out_for_delivery"
    READY_FOR_PICKUP = "ready_for_pickup"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class Customer(BaseModel):
    id: Optional[int] = None
    user_id: str
    push_name: Optional[str] = None
    created_at: datetime


class OrderItem(BaseModel):
    id: Optional[int] = None
    order_id: Optional[int] = None
    item_id: str
    name_snapshot: str
    size: str
    qty: int
    unit_price: int
    line_total: int
    notes: Optional[str] = None
    combo_choices_json: Optional[str] = None


class Order(BaseModel):
    id: Optional[int] = None
    order_no: str
    customer_id: int
    user_id: Optional[str] = None
    branch_id: str
    fulfilment: Literal["delivery", "pickup"]
    address: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    zone_id: Optional[str] = None
    subtotal: int
    delivery_fee: int
    discount: int
    total: int
    promo_code: Optional[str] = None
    status: OrderStatus = OrderStatus.NEW
    created_at: datetime
    items: List[OrderItem] = Field(default_factory=list)


class Handoff(BaseModel):
    id: Optional[int] = None
    user_id: str
    branch_id: Optional[str] = None
    reason: str
    status: Literal["open", "resolved"] = "open"
    created_at: datetime
    resolved_at: Optional[datetime] = None


class MessageLog(BaseModel):
    id: Optional[int] = None
    user_id: str
    direction: Literal["in", "out"]
    type: str = "text"
    text: Optional[str] = None
    trace_id: Optional[str] = None
    created_at: datetime

