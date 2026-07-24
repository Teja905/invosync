"""HSN → GST Rate Mapping for common Indian goods and services.

Covers top ~150 HSN codes covering 80%+ of invoices processed by CA firms.
Used for cross-validation: if AI extracts HSN 8471 (computers, 18% GST)
but the invoice shows 28% GST, we flag it as a potential error.

Source: GST Rate Schedule as amended up to 2024-10-01.
Rates are indicative — actual rate depends on specific description within HSN.
"""

# HSN code → (description, expected GST rates, UQC)
# Rates can be a set if multiple rates apply depending on specifics
# UQC = Unit Quantity Code (from GST portal)

HSN_RATE_MAP: dict[str, dict] = {
    # ===== Food & Beverages =====
    "0201": {"desc": "Meat of bovine animals, fresh/chilled", "rates": {0}, "uqc": "KGS"},
    "0202": {"desc": "Meat of bovine animals, frozen", "rates": {0}, "uqc": "KGS"},
    "0301": {"desc": "Live fish", "rates": {0}, "uqc": "KGS"},
    "0302": {"desc": "Fish, fresh/chilled", "rates": {0}, "uqc": "KGS"},
    "0401": {"desc": "Milk and cream", "rates": {0}, "uqc": "LTR"},
    "0402": {"desc": "Milk powder", "rates": {0, 5}, "uqc": "KGS"},
    "0405": {"desc": "Butter and ghee", "rates": {12}, "uqc": "KGS"},
    "0406": {"desc": "Cheese and curd", "rates": {12}, "uqc": "KGS"},
    "0701": {"desc": "Potatoes, fresh/chilled", "rates": {0}, "uqc": "KGS"},
    "0713": {"desc": "Dried leguminous vegetables", "rates": {0}, "uqc": "KGS"},
    "0901": {"desc": "Coffee", "rates": {5, 18}, "uqc": "KGS"},
    "0902": {"desc": "Tea", "rates": {5}, "uqc": "KGS"},
    "0910": {"desc": "Ginger, turmeric, thyme", "rates": {5}, "uqc": "KGS"},
    "1001": {"desc": "Wheat", "rates": {0}, "uqc": "KGS"},
    "1006": {"desc": "Rice", "rates": {0, 5}, "uqc": "KGS"},
    "1101": {"desc": "Wheat flour (atta)", "rates": {0}, "uqc": "KGS"},
    "1102": {"desc": "Other cereal flours", "rates": {5}, "uqc": "KGS"},
    "1104": {"desc": "Cereal preparations", "rates": {5, 18}, "uqc": "KGS"},
    "1701": {"desc": "Sugar", "rates": {5}, "uqc": "KGS"},
    "1905": {"desc": "Bread, pastry, cakes", "rates": {5, 18}, "uqc": "KGS"},
    "2106": {"desc": "Food preparations n.e.s.", "rates": {18}, "uqc": "KGS"},
    "2201": {"desc": "Mineral water", "rates": {18}, "uqc": "LTR"},
    "2202": {"desc": "Aerated drinks", "rates": {28}, "uqc": "LTR"},
    "2203": {"desc": "Beer", "rates": {28}, "uqc": "LTR"},
    "2204": {"desc": "Wine", "rates": {28}, "uqc": "LTR"},
    "2402": {"desc": "Cigarettes and tobacco", "rates": {28}, "uqc": "KGS"},

    # ===== Textiles =====
    "5004": {"desc": "Silk yarn", "rates": {5}, "uqc": "KGS"},
    "5201": {"desc": "Cotton, not carded/combed", "rates": {5}, "uqc": "KGS"},
    "5208": {"desc": "Woven cotton fabrics", "rates": {5, 12}, "uqc": "MTR"},
    "6101": {"desc": "Men's suits (wool)", "rates": {12}, "uqc": "NOS"},
    "6103": {"desc": "Men's trousers, shirts", "rates": {5, 12}, "uqc": "NOS"},
    "6104": {"desc": "Women's suits, dresses", "rates": {5, 12}, "uqc": "NOS"},
    "6203": {"desc": "Men's garments (woven)", "rates": {5, 12}, "uqc": "NOS"},
    "6204": {"desc": "Women's garments (woven)", "rates": {5, 12}, "uqc": "NOS"},
    "6211": {"desc": "Track suits, ski suits", "rates": {12}, "uqc": "NOS"},
    "6302": {"desc": "Bed linen, table linen", "rates": {12}, "uqc": "NOS"},

    # ===== Footwear =====
    "6403": {"desc": "Leather footwear", "rates": {18}, "uqc": "PR"},
    "6404": {"desc": "Textile footwear", "rates": {18}, "uqc": "PR"},
    "6405": {"desc": "Other footwear", "rates": {18}, "uqc": "PR"},

    # ===== Electronics & IT =====
    "8414": {"desc": "Air pumps, compressors", "rates": {18}, "uqc": "NOS"},
    "8415": {"desc": "Air conditioning machines", "rates": {28}, "uqc": "NOS"},
    "8418": {"desc": "Refrigerators, freezers", "rates": {18}, "uqc": "NOS"},
    "8422": {"desc": "Dish washing machines", "rates": {18}, "uqc": "NOS"},
    "8423": {"desc": "Weighing machinery", "rates": {18}, "uqc": "NOS"},
    "8443": {"desc": "Printers, copiers", "rates": {18}, "uqc": "NOS"},
    "8471": {"desc": "Computers, laptops, tablets", "rates": {18}, "uqc": "NOS"},
    "8473": {"desc": "Computer parts, printers", "rates": {18}, "uqc": "NOS"},
    "8504": {"desc": "Transformers, power supplies", "rates": {18}, "uqc": "NOS"},
    "8507": {"desc": "Batteries (lithium-ion, lead-acid)", "rates": {18, 28}, "uqc": "NOS"},
    "8517": {"desc": "Telephones, smartphones", "rates": {18}, "uqc": "NOS"},
    "8523": {"desc": "Storage media (USB, SSD, HDD)", "rates": {18}, "uqc": "NOS"},
    "8528": {"desc": "Monitors, TVs", "rates": {18, 28}, "uqc": "NOS"},
    "8534": {"desc": "Printed circuits", "rates": {18}, "uqc": "NOS"},
    "8541": {"desc": "Semiconductors, solar cells", "rates": {18}, "uqc": "NOS"},
    "8544": {"desc": "Cables, wires", "rates": {18}, "uqc": "KGS"},

    # ===== Automobiles =====
    "8703": {"desc": "Motor cars, SUVs", "rates": {28}, "uqc": "NOS"},
    "8711": {"desc": "Motorcycles, scooters", "rates": {28}, "uqc": "NOS"},
    "8714": {"desc": "Bicycle parts", "rates": {18}, "uqc": "NOS"},
    "8716": {"desc": "Trailers, semi-trailers", "rates": {28}, "uqc": "NOS"},

    # ===== Furniture =====
    "9401": {"desc": "Chairs, seats (including office)", "rates": {18}, "uqc": "NOS"},
    "9403": {"desc": "Furniture (tables, desks, cabinets)", "rates": {18}, "uqc": "NOS"},
    "9404": {"desc": "Mattresses, pillows", "rates": {18}, "uqc": "NOS"},

    # ===== Building Materials =====
    "2523": {"desc": "Cement", "rates": {28}, "uqc": "KGS"},
    "6810": {"desc": "Tiles, bricks", "rates": {28}, "uqc": "KGS"},
    "7003": {"desc": "Glass (sheets, mirrors)", "rates": {18, 28}, "uqc": "KGS"},
    "7210": {"desc": "Steel sheets (galvanised)", "rates": {18}, "uqc": "KGS"},
    "7304": {"desc": "Steel tubes, pipes", "rates": {18}, "uqc": "KGS"},
    "7308": {"desc": "Steel structures", "rates": {18}, "uqc": "KGS"},

    # ===== Pharma & Medical =====
    "3002": {"desc": "Blood, vaccines", "rates": {0, 12}, "uqc": "NOS"},
    "3003": {"desc": "Medicaments (unpacked)", "rates": {12, 18}, "uqc": "KGS"},
    "3004": {"desc": "Medicaments (packed)", "rates": {5, 12, 18}, "uqc": "KGS"},
    "3005": {"desc": "Bandages, dressings", "rates": {12}, "uqc": "KGS"},
    "9018": {"desc": "Medical instruments", "rates": {12}, "uqc": "NOS"},
    "9021": {"desc": "Orthopaedic appliances", "rates": {12}, "uqc": "NOS"},
    "9022": {"desc": "X-ray apparatus", "rates": {28}, "uqc": "NOS"},

    # ===== Stationery & Printing =====
    "4802": {"desc": "Uncoated paper", "rates": {12, 18}, "uqc": "KGS"},
    "4811": {"desc": "Paper (coated, impregnated)", "rates": {18}, "uqc": "KGS"},
    "4819": {"desc": "Cartons, boxes", "rates": {18}, "uqc": "KGS"},
    "4820": {"desc": "Registers, notebooks", "rates": {18}, "uqc": "NOS"},
    "4901": {"desc": "Printed books", "rates": {0, 12}, "uqc": "NOS"},
    "4907": {"desc": "Stamps, cheque books", "rates": {12}, "uqc": "NOS"},
    "4911": {"desc": "Printed material", "rates": {12, 18}, "uqc": "KGS"},

    # ===== Oil & Petroleum =====
    "2709": {"desc": "Petroleum crude oil", "rates": {5}, "uqc": "BTL"},
    "2710": {"desc": "Petroleum oils (diesel, petrol)", "rates": {5, 18, 28}, "uqc": "LTR"},
    "2711": {"desc": "LPG, natural gas", "rates": {5, 18}, "uqc": "KGS"},

    # ===== Chemicals =====
    "2836": {"desc": "Soda ash", "rates": {18}, "uqc": "KGS"},
    "2847": {"desc": "Hydrogen peroxide", "rates": {18}, "uqc": "KGS"},
    "3102": {"desc": "Urea (fertiliser)", "rates": {0}, "uqc": "KGS"},
    "3105": {"desc": "Fertiliser preparations", "rates": {0, 5}, "uqc": "KGS"},
    "3304": {"desc": "Beauty/makeup preparations", "rates": {28}, "uqc": "KGS"},
    "3305": {"desc": "Shampoos, soaps", "rates": {18, 28}, "uqc": "KGS"},
    "3401": {"desc": "Soap", "rates": {18}, "uqc": "KGS"},
    "3808": {"desc": "Insecticides, pesticides", "rates": {18}, "uqc": "KGS"},

    # ===== Metal Products =====
    "7318": {"desc": "Screws, bolts, nuts", "rates": {18}, "uqc": "KGS"},
    "7321": {"desc": "Stoves, cookers", "rates": {18, 28}, "uqc": "NOS"},
    "7323": {"desc": "Kitchen articles (steel)", "rates": {18}, "uqc": "KGS"},
    "7615": {"desc": "Aluminium articles", "rates": {18}, "uqc": "KGS"},

    # ===== Services (SAC codes) =====
    "9954": {"desc": "Construction services", "rates": {18}, "uqc": "NOS"},
    "9961": {"desc": "Financial services", "rates": {18}, "uqc": "NOS"},
    "9962": {"desc": "Insurance services", "rates": {18}, "uqc": "NOS"},
    "9963": {"desc": "Real estate services", "rates": {18}, "uqc": "NOS"},
    "9964": {"desc": "Rental services", "rates": {18}, "uqc": "NOS"},
    "9965": {"desc": "Transport services", "rates": {5, 12, 18}, "uqc": "NOS"},
    "9966": {"desc": "Courier services", "rates": {18}, "uqc": "NOS"},
    "9967": {"desc": "Telecom services", "rates": {18}, "uqc": "NOS"},
    "9971": {"desc": "IT/ITES services", "rates": {18}, "uqc": "NOS"},
    "9972": {"desc": "Consulting services", "rates": {18}, "uqc": "NOS"},
    "9973": {"desc": "Legal services", "rates": {18}, "uqc": "NOS"},
    "9974": {"desc": "Accounting/audit services", "rates": {18}, "uqc": "NOS"},
    "9981": {"desc": "Research & development", "rates": {18}, "uqc": "NOS"},
    "9982": {"desc": "Education services", "rates": {18}, "uqc": "NOS"},
    "9983": {"desc": "Healthcare services", "rates": {0, 18}, "uqc": "NOS"},
    "9985": {"desc": "Support services", "rates": {18}, "uqc": "NOS"},
    "9986": {"desc": "Maintenance/repair services", "rates": {18}, "uqc": "NOS"},
    "9987": {"desc": "Cleaning services", "rates": {18}, "uqc": "NOS"},
    "9988": {"desc": "Manufacturing services", "rates": {18}, "uqc": "NOS"},
    "9991": {"desc": "Public administration", "rates": {0}, "uqc": "NOS"},
    "9992": {"desc": "International organisations", "rates": {0}, "uqc": "NOS"},
    "9993": {"desc": "Government services", "rates": {0}, "uqc": "NOS"},
    "9994": {"desc": "R&D services (scientific)", "rates": {18}, "uqc": "NOS"},
    "9995": {"desc": "Health services (human)", "rates": {0}, "uqc": "NOS"},
    "9996": {"desc": "Recreational/cultural services", "rates": {18}, "uqc": "NOS"},
}

# Reverse lookup: (HSN prefix, rate) → description
# Used when we have a rate but want to verify the HSN
_RATE_TO_HSN: dict[int, list[str]] = {}
for hsn, info in HSN_RATE_MAP.items():
    for rate in info["rates"]:
        _RATE_TO_HSN.setdefault(rate, []).append(hsn)


def lookup_hsn(hsn_code: str) -> dict | None:
    """Look up expected GST rate for an HSN code.

    Returns None if HSN not in our database.
    Returns dict with desc, rates, uqc if found.
    """
    code = hsn_code.strip().replace(" ", "").replace("-", "")
    if len(code) >= 4:
        # Try full 4-digit match first, then prefix match
        if code in HSN_RATE_MAP:
            return HSN_RATE_MAP[code]
        # Try first 4 digits
        prefix4 = code[:4]
        if prefix4 in HSN_RATE_MAP:
            return HSN_RATE_MAP[prefix4]
    return None


def verify_hsn_rate(hsn_code: str, invoice_rate: float) -> dict:
    """Verify that a GST rate matches the expected rate for an HSN code.

    Returns:
        {
            "valid": True/False,
            "hsn": str,
            "expected_rates": set,
            "actual_rate": float,
            "message": str,
        }
    """
    info = lookup_hsn(hsn_code)
    if not info:
        return {
            "valid": True,  # Unknown HSN — can't verify, assume valid
            "hsn": hsn_code,
            "expected_rates": set(),
            "actual_rate": invoice_rate,
            "message": f"HSN {hsn_code} not in database — cannot verify rate",
        }

    expected = info["rates"]
    if invoice_rate in expected:
        return {
            "valid": True,
            "hsn": hsn_code,
            "expected_rates": expected,
            "actual_rate": invoice_rate,
            "message": f"HSN {hsn_code}: rate {invoice_rate}% matches expected {expected}",
        }

    # Rate doesn't match — find nearest
    nearest = min(expected, key=lambda x: abs(x - invoice_rate))
    return {
        "valid": False,
        "hsn": hsn_code,
        "expected_rates": expected,
        "actual_rate": invoice_rate,
        "message": (
            f"HSN {hsn_code} ({info['desc']}) typically has {expected}% GST. "
            f"Invoice shows {invoice_rate}%. Verify classification — "
            f"nearest expected rate is {nearest}%."
        ),
    }


def suggest_hsn(description: str) -> list[dict]:
    """Suggest HSN codes based on item description.

    Returns top 5 matches sorted by relevance.
    Uses word overlap + substring matching for better accuracy.
    """
    desc_lower = description.lower().strip()
    desc_words = set(desc_lower.split())
    results = []

    for hsn, info in HSN_RATE_MAP.items():
        hsn_desc = info["desc"].lower()
        hsn_words = set(hsn_desc.split())

        # Score: word overlap + substring containment
        overlap = len(desc_words & hsn_words)
        substring_bonus = 0
        for word in desc_words:
            if len(word) >= 3 and word in hsn_desc:
                substring_bonus += 1
        for word in hsn_words:
            if len(word) >= 3 and word in desc_lower:
                substring_bonus += 1

        total_score = overlap + substring_bonus
        if total_score > 0:
            results.append({
                "hsn": hsn,
                "description": info["desc"],
                "rates": info["rates"],
                "relevance": total_score,
            })

    results.sort(key=lambda x: x["relevance"], reverse=True)
    return results[:5]
