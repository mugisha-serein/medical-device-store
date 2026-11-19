"""
Seed script to populate the database with initial data.
Run with: python -m scripts.seed
"""

import asyncio
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import async_session_factory, engine
from app.core.security import hash_password
from app.identity.models import User
from app.catalog.models import Category, Product
from app.inventory.models import Inventory
from app.orders.models import Order, OrderItem, OutboxEvent  # noqa: F401 — registers models with SQLAlchemy

# ── Categories ────────────────────────────────────────────────────────────────

CATEGORIES = [
    {
        "slug": "diagnostic",
        "name": "Diagnostic Equipment",
        "tagline": "Precision tools for accurate clinical assessment.",
    },
    {
        "slug": "mobility",
        "name": "Mobility Aids",
        "tagline": "Wheelchairs, walkers, and daily-living support.",
    },
    {
        "slug": "monitoring",
        "name": "Monitoring Devices",
        "tagline": "Continuous vitals tracking for home and clinic.",
    },
    {
        "slug": "surgical",
        "name": "Surgical Instruments",
        "tagline": "Sterilizable, OR-grade precision instruments.",
    },
    {
        "slug": "ppe",
        "name": "Personal Protective Equipment",
        "tagline": "Certified protection for staff and patients.",
    },
    {
        "slug": "homecare",
        "name": "Home Care & Rehabilitation",
        "tagline": "Recovery and independent-living equipment.",
    },
]

# ── Products (mapped from js/products.js) ─────────────────────────────────────

PRODUCTS = [
    # Diagnostic
    {"sku": "dg-001", "name": "ClearTone Digital Stethoscope", "price": 189.00, "stock": 24, "category": "diagnostic",
     "description": "Electronic stethoscope with adjustable amplification and ambient noise reduction for accurate auscultation.",
     "specs": {"Weight": "192 g", "Battery life": "22 hrs", "Amplification": "Up to 24x", "Warranty": "2 years"}},
    {"sku": "dg-002", "name": "OtoView LED Otoscope Set", "price": 76.50, "stock": 40, "category": "diagnostic",
     "description": "Fiber-optic LED otoscope with 3 reusable specula sizes and a rechargeable handle.",
     "specs": {"Light source": "LED, 60000 lux", "Battery": "Li-ion rechargeable", "Specula sizes": "3, 4, 5 mm", "Warranty": "1 year"}},
    {"sku": "dg-003", "name": "PulseCheck Fingertip Oximeter", "price": 34.99, "stock": 120, "category": "diagnostic",
     "description": "Compact pulse oximeter with OLED display for SpO2 and heart-rate spot checks.",
     "specs": {"Display": "OLED, 4-direction", "SpO2 range": "70–100%", "Battery": "2x AAA", "Warranty": "1 year"}},
    {"sku": "dg-004", "name": "AccuTemp Infrared Thermometer", "price": 42.00, "stock": 8, "category": "diagnostic",
     "description": "Non-contact infrared thermometer for forehead temperature screening in under 2 seconds.",
     "specs": {"Accuracy": "±0.2°C", "Read time": "1 sec", "Memory": "32 readings", "Warranty": "1 year"}},

    # Mobility
    {"sku": "mb-001", "name": "GlideRest Folding Wheelchair", "price": 310.00, "stock": 15, "category": "mobility",
     "description": "Lightweight aluminum-frame folding wheelchair with padded armrests and swing-away footrests.",
     "specs": {"Weight capacity": "125 kg", "Frame": "Aluminum", "Seat width": "46 cm", "Folded size": "34 x 76 x 86 cm"}},
    {"sku": "mb-002", "name": "StrideSure Rollator Walker", "price": 145.00, "stock": 30, "category": "mobility",
     "description": "Four-wheel rollator with padded seat, storage pouch, and loop-lock brakes for stable indoor/outdoor use.",
     "specs": {"Weight capacity": "135 kg", "Seat height": "58 cm", "Brakes": "Loop-lock", "Folded width": "23 cm"}},
    {"sku": "mb-003", "name": "EasyGrip Adjustable Cane", "price": 28.00, "stock": 60, "category": "mobility",
     "description": "Height-adjustable aluminum cane with ergonomic offset handle and non-slip rubber tip.",
     "specs": {"Height range": "76–96 cm", "Weight capacity": "115 kg", "Material": "Aluminum", "Grip": "Ergonomic offset"}},
    {"sku": "mb-004", "name": "TransferPro Bed Rail", "price": 89.00, "stock": 0, "category": "mobility",
     "description": "Adjustable bedside safety rail providing support for transfers and repositioning.",
     "specs": {"Height adjustment": "5 positions", "Material": "Steel, powder-coated", "Fits": "Most bed frames", "Assembly": "Tool-free"}},

    # Monitoring
    {"sku": "mn-001", "name": "VitalSync Patient Monitor", "price": 640.00, "stock": 6, "category": "monitoring",
     "description": "Multi-parameter monitor tracking ECG, SpO2, NIBP, and respiration with a 10-inch touchscreen.",
     "specs": {"Display": "10.1\" touchscreen", "Parameters": "ECG / SpO2 / NIBP / RR", "Battery backup": "4 hrs", "Connectivity": "Wi-Fi / LAN"}},
    {"sku": "mn-002", "name": "HomeCuff Auto Blood Pressure Monitor", "price": 54.00, "stock": 45, "category": "monitoring",
     "description": "Upper-arm automatic blood pressure monitor with irregular heartbeat detection and 2-user memory.",
     "specs": {"Cuff size": "22–42 cm", "Memory": "2 users x 90", "Power": "AC adapter / 4x AA", "Warranty": "2 years"}},
    {"sku": "mn-003", "name": "GlucoTrack Blood Glucose Meter", "price": 29.50, "stock": 90, "category": "monitoring",
     "description": "Fast blood glucose meter with 5-second results and 500-reading memory, includes 25 test strips.",
     "specs": {"Sample size": "0.5 µL", "Result time": "5 sec", "Memory": "500 readings", "Includes": "25 strips + lancets"}},
    {"sku": "mn-004", "name": "SleepGuard Apnea Monitor", "price": 210.00, "stock": 12, "category": "monitoring",
     "description": "Wearable overnight monitor tracking SpO2, pulse, and breathing patterns with companion report export.",
     "specs": {"Battery life": "18 hrs", "Data export": "USB / SD card", "Alarm": "Audible + vibration", "Warranty": "1 year"}},

    # Surgical
    {"sku": "sg-001", "name": "PrecisionEdge Surgical Scissors Set", "price": 96.00, "stock": 20, "category": "surgical",
     "description": "Autoclavable stainless-steel scissor set including straight, curved, and iris variants.",
     "specs": {"Material": "Surgical stainless steel", "Pieces": "3", "Sterilization": "Autoclave up to 134°C", "Length": "14 cm avg."}},
    {"sku": "sg-002", "name": "ClampSecure Hemostatic Forceps", "price": 41.00, "stock": 35, "category": "surgical",
     "description": "Serrated-jaw hemostatic forceps with ratchet lock for reliable vessel clamping.",
     "specs": {"Material": "Stainless steel", "Length": "14 cm", "Lock type": "Ratchet, 3-position", "Sterilization": "Autoclavable"}},
    {"sku": "sg-003", "name": "SutureMaster Needle Holder", "price": 58.00, "stock": 18, "category": "surgical",
     "description": "Tungsten-carbide insert needle holder for precise, slip-free suturing.",
     "specs": {"Jaw insert": "Tungsten carbide", "Length": "16 cm", "Lock type": "Ratchet", "Sterilization": "Autoclavable"}},
    {"sku": "sg-004", "name": "ClearView Surgical Retractor Set", "price": 132.00, "stock": 5, "category": "surgical",
     "description": "Self-retaining retractor set for improved field visibility during minor procedures.",
     "specs": {"Pieces": "4 blades + frame", "Material": "Stainless steel", "Sterilization": "Autoclavable", "Case": "Included"}},

    # PPE
    {"sku": "pp-001", "name": "ShieldFit N95 Respirator (20-pack)", "price": 24.00, "stock": 200, "category": "ppe",
     "description": "NIOSH-listed N95 respirators with adjustable nose bridge and dual elastic straps, box of 20.",
     "specs": {"Rating": "N95 NIOSH-listed", "Quantity": "20 per box", "Fit": "Adjustable nose bridge", "Use": "Single-use"}},
    {"sku": "pp-002", "name": "SafeTouch Nitrile Exam Gloves (100-pack)", "price": 14.50, "stock": 300, "category": "ppe",
     "description": "Powder-free nitrile examination gloves offering strong puncture resistance, box of 100.",
     "specs": {"Material": "Nitrile, powder-free", "Quantity": "100 per box", "Sizes": "S / M / L / XL", "AQL": "1.5"}},
    {"sku": "pp-003", "name": "ClearGuard Face Shield (10-pack)", "price": 32.00, "stock": 75, "category": "ppe",
     "description": "Anti-fog full-face shields with foam headband padding for extended comfort, pack of 10.",
     "specs": {"Coating": "Anti-fog", "Quantity": "10 per pack", "Adjustable": "Yes", "Reusable": "Yes"}},
    {"sku": "pp-004", "name": "BioBarrier Isolation Gown", "price": 6.90, "stock": 0, "category": "ppe",
     "description": "Fluid-resistant Level 2 isolation gown with knit cuffs, sold individually.",
     "specs": {"Protection level": "Level 2", "Material": "SMS non-woven", "Cuff": "Knit", "Size": "Universal"}},

    # Home Care
    {"sku": "hc-001", "name": "ComfortRise Adjustable Bed Frame", "price": 780.00, "stock": 4, "category": "homecare",
     "description": "Electric adjustable bed frame with head/foot elevation and wireless remote control.",
     "specs": {"Adjustment": "Head + foot, motorized", "Weight capacity": "180 kg", "Remote": "Wireless", "Warranty": "3 years"}},
    {"sku": "hc-002", "name": "SteadyStep Bathroom Safety Kit", "price": 68.00, "stock": 22, "category": "homecare",
     "description": "Grab bar, non-slip mat, and raised toilet seat bundle for safer bathroom mobility.",
     "specs": {"Pieces": "3-piece kit", "Weight capacity": "150 kg", "Material": "Stainless + PVC", "Install": "Tool-free / suction & screw options"}},
    {"sku": "hc-003", "name": "TheraBand Resistance Rehab Set", "price": 22.00, "stock": 55, "category": "homecare",
     "description": "5-level resistance band set with door anchor and exercise guide for physiotherapy routines.",
     "specs": {"Resistance levels": "5", "Material": "Natural latex", "Includes": "Door anchor, guide", "Length": "1.5 m each"}},
    {"sku": "hc-004", "name": "NightWatch Bedside Commode", "price": 74.00, "stock": 17, "category": "homecare",
     "description": "Sturdy steel-frame bedside commode with removable pail and padded armrests.",
     "specs": {"Weight capacity": "140 kg", "Frame": "Steel, powder-coated", "Seat": "Padded, removable lid", "Height": "Adjustable, 4 levels"}},
]


def get_seed_admin_password() -> str:
    password = os.environ.get("ADMIN_SEED_PASSWORD", "")
    if len(password) < 12 or password.lower() in {"admin123456", "password123456"}:
        raise RuntimeError("Set ADMIN_SEED_PASSWORD to a unique password of at least 12 characters.")
    return password


async def seed():
    # Schema is managed by Alembic — run: alembic upgrade head
    admin_password = get_seed_admin_password()
    async with async_session_factory() as session:
        # Seed categories
        category_map = {}
        for cat_data in CATEGORIES:
            cat = Category(**cat_data)
            session.add(cat)
            await session.flush()
            category_map[cat.slug] = cat.id
            print(f"  ✓ Category: {cat.name}")

        # Seed products and inventory
        for prod_data in PRODUCTS:
            cat_slug = prod_data.pop("category")
            stock = prod_data.pop("stock")
            category_id = category_map[cat_slug]

            product = Product(
                category_id=category_id,
                **prod_data,
            )
            session.add(product)
            await session.flush()

            # Create inventory record
            inventory = Inventory(
                product_id=product.id,
                quantity_total=stock,
                quantity_held=0,
                quantity_committed=0,
            )
            session.add(inventory)
            print(f"  ✓ Product: {product.name} (stock: {stock})")

        # Create admin user
        admin = User(
            email="admin@activelife.rw",
            name="Admin User",
            password_hash=hash_password(admin_password),
            is_admin=True,
        )
        session.add(admin)
        print(f"  ✓ Admin user: admin@activelife.rw")

        await session.commit()
        print("\n✅ Seed complete!")


if __name__ == "__main__":
    asyncio.run(seed())
