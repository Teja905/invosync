import re

GST_STATE_CODES = {
    "01": "Jammu & Kashmir", "02": "Himachal Pradesh", "03": "Punjab",
    "04": "Chandigarh", "05": "Uttarakhand", "06": "Haryana",
    "07": "Delhi", "08": "Rajasthan", "09": "Uttar Pradesh",
    "10": "Bihar", "11": "Sikkim", "12": "Arunachal Pradesh",
    "13": "Nagaland", "14": "Manipur", "15": "Mizoram",
    "16": "Tripura", "17": "Meghalaya", "18": "Assam",
    "19": "West Bengal", "20": "Jharkhand", "21": "Odisha",
    "22": "Chhattisgarh", "23": "Madhya Pradesh", "24": "Gujarat",
    "25": "Daman & Diu", "26": "Dadra & Nagar Haveli",
    "27": "Maharashtra", "28": "Andhra Pradesh (Old)",
    "29": "Karnataka", "30": "Goa", "31": "Lakshadweep",
    "32": "Kerala", "33": "Tamil Nadu", "34": "Puducherry",
    "35": "Andaman & Nicobar", "36": "Telangana",
    "37": "Andhra Pradesh (New)",
}

ALLOWED_GST_SLABS = {0, 0.1, 0.25, 3, 5, 12, 18, 28}


def extract_state_code(gstin: str) -> str:
    match = re.match(r"^(\d{2})", gstin.strip().upper())
    return match.group(1) if match else ""


def classify_gst(company_gstin: str, party_gstin: str) -> dict:
    comp_state = extract_state_code(company_gstin)
    party_state = extract_state_code(party_gstin)

    if not comp_state or not party_state:
        return {"gst_type": "CGST_SGST", "is_interstate": False,
                "company_state": comp_state, "party_state": party_state,
                "message": "Could not extract state codes, defaulting to intra-state"}

    if comp_state == party_state:
        return {"gst_type": "CGST_SGST", "is_interstate": False,
                "company_state": comp_state, "party_state": party_state,
                "message": f"Intra-state: both in {GST_STATE_CODES.get(comp_state, comp_state)}"}
    else:
        return {"gst_type": "IGST", "is_interstate": True,
                "company_state": comp_state, "party_state": party_state,
                "message": f"Inter-state: company in {GST_STATE_CODES.get(comp_state, comp_state)}, party in {GST_STATE_CODES.get(party_state, party_state)}"}


def compute_tax(taxable_total: float, tax_rate: float, gst_type: str) -> list[dict]:
    entries = []
    if taxable_total <= 0 or tax_rate <= 0:
        return entries

    if gst_type == "CGST_SGST":
        half_rate = tax_rate / 2.0
        cgst_amt = round(taxable_total * half_rate / 100.0, 2)
        sgst_amt = round(taxable_total * half_rate / 100.0, 2)
        if cgst_amt > 0:
            entries.append({"name": "CGST", "rate": half_rate, "amount": cgst_amt, "type": "cgst"})
        if sgst_amt > 0:
            entries.append({"name": "SGST", "rate": half_rate, "amount": sgst_amt, "type": "sgst"})
    elif gst_type == "IGST":
        igst_amt = round(taxable_total * tax_rate / 100.0, 2)
        if igst_amt > 0:
            entries.append({"name": "IGST", "rate": tax_rate, "amount": igst_amt, "type": "igst"})

    return entries


def compute_tax_from_items(items: list[dict], gst_type: str) -> list[dict]:
    tax_map: dict[str, dict] = {}
    for item in items:
        tv = float(item.get("taxable_amount", 0) or 0)
        tr = float(item.get("tax_rate", 0) or 0)
        if tv <= 0 or tr <= 0:
            continue
        entries = compute_tax(tv, tr, gst_type)
        for e in entries:
            key = f"{e['type']}_{e['rate']}"
            if key in tax_map:
                tax_map[key]["amount"] = round(tax_map[key]["amount"] + e["amount"], 2)
            else:
                tax_map[key] = e
    return list(tax_map.values())
