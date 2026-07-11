# GST Engine Reference

## State Codes

| Code | State | Code | State |
|---|---|---|---|
| 01 | Jammu & Kashmir | 20 | Jharkhand |
| 02 | Himachal Pradesh | 21 | Odisha |
| 03 | Punjab | 22 | Chhattisgarh |
| 04 | Chandigarh | 23 | Madhya Pradesh |
| 05 | Uttarakhand | 24 | Gujarat |
| 06 | Haryana | 25 | Daman & Diu |
| 07 | Delhi | 26 | Dadra & Nagar Haveli |
| 08 | Rajasthan | 27 | **Maharashtra** |
| 09 | Uttar Pradesh | 28 | Andhra Pradesh (Old) |
| 10 | Bihar | 29 | Karnataka |
| 11 | Sikkim | 30 | Goa |
| 12 | Arunachal Pradesh | 31 | Lakshadweep |
| 13 | Nagaland | 32 | Kerala |
| 14 | Manipur | 33 | Tamil Nadu |
| 15 | Mizoram | 34 | Puducherry |
| 16 | Tripura | 35 | Andaman & Nicobar |
| 17 | Meghalaya | 36 | Telangana |
| 18 | Assam | 37 | Andhra Pradesh (New) |
| 19 | West Bengal | | |

## GST Determination

```
If vendor state == buyer state:
  → CGST + SGST (half rate each)
Else:
  → IGST (full rate)
```

## Allowed Tax Slabs

0%, 0.1%, 0.25%, 3%, 5%, 12%, 18%, 28%

## GSTIN Format

`27 AABCU 1234 F 1 Z P`
│  │     │    │ │ │ │
│  │     │    │ │ │ └─ Check digit (alphanumeric)
│  │     │    │ │ └─── Fixed "Z"
│  │     │    │ └───── Entity number (1-9)
│  │     │    └─────── PAN 10th char (letter)
│  │     └──────────── PAN (5 letters + 4 digits)
│  └────────────────── State code (01-37)
└───────────────────── Format indicator
```

## Checksum Algorithm

1. Codepoints: `0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ`
2. For each char (0-indexed, excluding check digit):
   - Odd position → multiply value by 2
   - Add (product // 36 + product % 36) to total
3. Check digit = codepoints[(36 - total % 36) % 36]
