"""Static catalogue used to build synthetic contracts.

Nothing here is real customer data. Prices are plausible AUD figures for
Australian commercial facilities maintenance, invented for demo purposes.
"""

from app.models import ItemCategory

# (code, description, category, unit, base_price, max_qty_per_slip)
SHARED_ITEMS = [
    ("FLT-001", "Split System Air Filter", ItemCategory.MATERIAL, "ea", 68, None),
    ("FLT-002", "Cassette Unit Air Filter", ItemCategory.MATERIAL, "ea", 115, None),
    ("FLT-003", "Water Filter Cartridge 10 inch", ItemCategory.MATERIAL, "ea", 51, None),
    ("REF-001", "R410A Refrigerant", ItemCategory.MATERIAL, "kg", 185, 10),
    ("REF-002", "R32 Refrigerant", ItemCategory.MATERIAL, "kg", 210, 10),
    ("ELE-001", "Compressor Contactor 25A", ItemCategory.MATERIAL, "ea", 132, None),
    ("ELE-002", "Circuit Breaker C16", ItemCategory.MATERIAL, "ea", 32, None),
    ("ELE-003", "RCD Safety Switch 30mA", ItemCategory.MATERIAL, "ea", 176, None),
    ("CTL-001", "Digital Thermostat", ItemCategory.MATERIAL, "ea", 245, None),
    ("PMP-001", "Condensate Drain Pump", ItemCategory.MATERIAL, "ea", 348, None),
    ("PMP-002", "Float Switch", ItemCategory.MATERIAL, "ea", 96, None),
    ("PMP-003", "Circulation Pump Seal Kit", ItemCategory.MATERIAL, "ea", 142, None),
    ("MOT-001", "Fan Motor 1/4 HP", ItemCategory.MATERIAL, "ea", 465, None),
    ("BLT-001", "V-Belt Type A", ItemCategory.MATERIAL, "ea", 47, None),
    ("BRG-001", "Bearing 6204 ZZ", ItemCategory.MATERIAL, "ea", 41, None),
    ("PIP-001", "Copper Pipe 1/4 inch", ItemCategory.MATERIAL, "m", 62, None),
    ("INS-001", "Rubber Insulation 19mm", ItemCategory.MATERIAL, "m", 28, None),
    ("CBL-001", "TPS Cable 3 Core 2.5mm", ItemCategory.MATERIAL, "m", 22, None),
    ("GAU-001", "Pressure Gauge 0-10 Bar", ItemCategory.MATERIAL, "ea", 78, None),
    ("VLV-001", "Ball Valve 1/2 inch", ItemCategory.MATERIAL, "ea", 57, None),
    ("VNT-001", "Automatic Air Vent", ItemCategory.MATERIAL, "ea", 64, None),
    ("TNK-001", "Expansion Vessel 8L", ItemCategory.MATERIAL, "ea", 412, None),
    ("FIR-001", "Optical Smoke Detector", ItemCategory.MATERIAL, "ea", 198, None),
    ("LGT-001", "Emergency Exit Light", ItemCategory.MATERIAL, "ea", 163, None),
    ("LGT-002", "LED Panel Light 40W", ItemCategory.MATERIAL, "ea", 108, None),
    ("UPS-001", "UPS Battery 12V 7Ah", ItemCategory.MATERIAL, "ea", 236, None),
    ("DOR-001", "Hydraulic Door Closer", ItemCategory.MATERIAL, "ea", 287, None),
    ("CHM-001", "Glycol Antifreeze", ItemCategory.MATERIAL, "L", 43, None),
    ("CHM-002", "Condensate Pan Tablet", ItemCategory.MATERIAL, "ea", 25, None),
    ("MNT-001", "Anti-Vibration Mount", ItemCategory.MATERIAL, "ea", 36, None),

    ("SVC-001", "Scheduled Maintenance - Split System", ItemCategory.LABOUR, "ea", 128, 40),
    ("SVC-002", "Scheduled Maintenance - VRF System", ItemCategory.LABOUR, "ea", 360, 10),
    ("SVC-003", "Scheduled Maintenance - Chiller", ItemCategory.LABOUR, "ea", 840, 4),
    ("SVC-004", "Scheduled Maintenance - Generator", ItemCategory.LABOUR, "ea", 480, 4),
    ("SVC-005", "Scheduled Maintenance - Fire Detection System", ItemCategory.LABOUR, "ea", 420, 2),
    ("LAB-001", "Breakdown Callout - Business Hours", ItemCategory.LABOUR, "hr", 142, 12),
    ("LAB-002", "Breakdown Callout - After Hours", ItemCategory.LABOUR, "hr", 213, 8),
    ("LAB-003", "Breakdown Callout - Weekend", ItemCategory.LABOUR, "hr", 256, 8),
    ("LAB-004", "Refrigerant Charging Labour", ItemCategory.LABOUR, "ea", 165, 6),
    ("LAB-005", "Copper Brazing Labour", ItemCategory.LABOUR, "hr", 187, 8),
    ("LAB-006", "Switchboard Inspection", ItemCategory.LABOUR, "ea", 210, 6),
    ("LAB-007", "Plumbing Repair Labour", ItemCategory.LABOUR, "hr", 135, 10),
    ("LAB-008", "Commissioning and Testing", ItemCategory.LABOUR, "hr", 172, 8),
    ("LAB-009", "Travel and Transport", ItemCategory.LABOUR, "ea", 98, 1),
]

# Items that exist for exactly one customer. A slip that mentions another
# customer's speciality item must NOT be priced - it has to hit the queue.
CUSTOMER_ONLY_ITEMS = {
    "SBC": [
        ("SPC-101", "Escalator Monthly Service", ItemCategory.LABOUR, "ea", 630, 6),
        ("SPC-102", "Car Park Ventilation Fan Inspection", ItemCategory.LABOUR, "ea", 278, 8),
    ],
    "SMP": [
        ("SPC-201", "HEPA Filter Replacement (Operating Theatre)", ItemCategory.MATERIAL, "ea", 1335, 12),
        ("SPC-202", "Medical Gas Line Pressure Test", ItemCategory.LABOUR, "ea", 510, 4),
    ],
    "KMP": [
        ("SPC-301", "Compressor Oil 20L", ItemCategory.MATERIAL, "ea", 1005, 4),
        ("SPC-302", "Industrial Fan Balancing", ItemCategory.LABOUR, "ea", 780, 3),
    ],
}

# (code, name, price multiplier negotiated into that customer's contract)
CUSTOMERS = [
    ("SBC", "Southbank Central Shopping Centre", 1.00),
    ("SMP", "St Marlow Private Hospital", 1.12),
    ("KMP", "Kingsford Metals Pty Ltd", 0.94),
]

# Phrasings an expert has already confirmed in the past, seeded as aliases.
SEED_ALIASES = {
    "SVC-001": ["split system service", "split scheduled service"],
    "SVC-002": ["vrf service", "vrf system scheduled service"],
    "LAB-001": ["business hours callout", "normal hours breakdown"],
    "LAB-002": ["after hours callout", "out of hours breakdown"],
    "LAB-004": ["gas charge", "refrigerant top up labour"],
    "FLT-001": ["split system filter", "wall mounted unit filter"],
    "REF-001": ["r410 gas", "r 410 a refrigerant"],
    "BLT-001": ["v belt", "type a belt"],
    "ELE-002": ["c16 breaker", "circuit breaker c16 mcb"],
    "LGT-002": ["led panel 40w", "40 watt led panel"],
}

# Lines where the wording alone does not say whether something was SUPPLIED or
# DONE. The catalogue prices the gas and the labour of charging it, the pipe
# and the labour of brazing it, in almost the same words. Written with the unit
# 'ea', which this catalogue uses for both parts and labour, nothing in the
# line settles it. There is no correct automatic answer to these: the only
# right behaviour is to hand them to a human.
CATEGORY_TRAP_PHRASES = [
    "refrigerant charging",
    "refrigerant gas charge",
    "gas charge refrigerant",
    "r410a refrigerant charge",
    "r32 refrigerant charge",
    "copper pipe brazing",
]

# Work that appears on slips but exists in no contract at all.
OFF_CONTRACT_PHRASES = [
    "Roof membrane waterproofing renewed",
    "Irrigation controller reprogrammed",
    "Car park boom gate arm replaced",
    "External window cleaning completed",
    "Security camera lens realigned",
    "Epoxy floor coating patched",
    "Lawn mowing and hedge trimming",
    "Office furniture assembly",
    "Pest control treatment applied",
    "Signage LED strip replaced",
]

TECHNICIANS = [
    "Liam Harrison",
    "Ethan Brooks",
    "Jack Whitfield",
    "Noah Bennett",
    "Cooper Hayes",
    "Riley Donnelly",
]
