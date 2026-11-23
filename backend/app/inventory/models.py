import uuid
from datetime import datetime, timezone, timedelta

from sqlalchemy import String, Integer, ForeignKey, Enum, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
import enum

from app.core.database import Base
from app.core.types import UTCDateTime


def generate_uuid() -> str:
    return str(uuid.uuid4())


class HoldStatus(str, enum.Enum):
    ACTIVE = "active"
    COMMITTED = "committed"
    RELEASED = "released"
    EXPIRED = "expired"


class Inventory(Base):
    __tablename__ = "inventory"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    product_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("products.id"), unique=True, index=True, nullable=False
    )
    quantity_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    quantity_held: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    quantity_committed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    product = relationship("Product", back_populates="inventory")
    holds = relationship("StockHold", back_populates="inventory", lazy="selectin")

    @property
    def quantity_available(self) -> int:
        return self.quantity_total - self.quantity_held - self.quantity_committed


class StockHold(Base):
    __tablename__ = "stock_holds"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    inventory_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("inventory.id"), nullable=False, index=True
    )
    order_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[HoldStatus] = mapped_column(
        Enum(HoldStatus), default=HoldStatus.ACTIVE, nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    inventory = relationship("Inventory", back_populates="holds")

    @property
    def is_expired(self) -> bool:
        return datetime.now(timezone.utc) > self.expires_at
