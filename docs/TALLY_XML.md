# Tally XML Format

## Purchase Voucher (Goods)

```xml
<ENVELOPE>
  <HEADER>
    <TALLYREQUEST>Import Data</TALLYREQUEST>
    <TYPE>Data</TYPE>
    <ID>All Masters</ID>
  </HEADER>
  <BODY>
    <DESC>
      <STATICVARIABLES>
        <SVCURRENTCOMPANY>Company Name</SVCURRENTCOMPANY>
      </STATICVARIABLES>
    </DESC>
    <DATA>
      <TALLYMESSAGE>
        <VOUCHER VCHTYPE="Purchase">
          <!-- Basic fields -->
          <DATE>20240115</DATE>
          <VOUCHERNUMBER>INV-001</VOUCHERNUMBER>
          <PARTYLEDGERNAME>Vendor Name</PARTYLEDGERNAME>
          <PARTYGSTIN>27AABCU1234F1ZP</PARTYGSTIN>

          <!-- Debit: Purchase ledger -->
          <ALLLEDGERENTRIES.LIST>
            <LEDGERNAME>Purchase</LEDGERNAME>
            <ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>
            <AMOUNT>100000.00</AMOUNT>
          </ALLLEDGERENTRIES.LIST>

          <!-- Debit: CGST -->
          <ALLLEDGERENTRIES.LIST>
            <LEDGERNAME>Input CGST 9%</LEDGERNAME>
            <ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>
            <AMOUNT>9000.00</AMOUNT>
          </ALLLEDGERENTRIES.LIST>

          <!-- Debit: SGST -->
          <ALLLEDGERENTRIES.LIST>
            <LEDGERNAME>Input SGST 9%</LEDGERNAME>
            <ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>
            <AMOUNT>9000.00</AMOUNT>
          </ALLLEDGERENTRIES.LIST>

          <!-- Credit: Party (with bill allocation) -->
          <ALLLEDGERENTRIES.LIST>
            <LEDGERNAME>Vendor Name</LEDGERNAME>
            <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
            <AMOUNT>-118000.00</AMOUNT>
            <BILLALLOCATIONS.LIST>
              <NAME>INV-001</NAME>
              <BILLTYPE>New Ref</BILLTYPE>
              <AMOUNT>-118000.00</AMOUNT>
            </BILLALLOCATIONS.LIST>
          </ALLLEDGERENTRIES.LIST>

          <!-- Inventory (goods only) -->
          <ALLINVENTORYENTRIES.LIST>
            <STOCKITEMNAME>Product Name</STOCKITEMNAME>
            <QUANTITY>500</QUANTITY>
            <RATE>200.00</RATE>
            <AMOUNT>100000.00</AMOUNT>
            <GSTCLASS>18%</GSTCLASS>
            <HSNCODE>7214</HSNCODE>
            <UNIT>Kgs</UNIT>
          </ALLINVENTORYENTRIES.LIST>
        </VOUCHER>
      </TALLYMESSAGE>
    </DATA>
  </BODY>
</ENVELOPE>
```

## Sign Convention

| Entry Type | ISDEEMEDPOSITIVE | AMOUNT sign | Tally Effect |
|---|---|---|---|
| Debit (Purchase, Expense, GST) | Yes | Positive | Debit |
| Credit (Party, Supplier) | No | Negative | Credit |

## Voucher Types

| VCHTYPE | When |
|---|---|
| Purchase | Goods/services purchased (default) |
| Sales | Goods/services sold |
| Payment | Money paid to vendor |
| Receipt | Money received from customer |
| Journal | Non-cash adjustments |
| Credit Note | Purchase return / reduction |
| Debit Note | Additional charge / increase |

## Service vs Goods

- **Service**: No `<ALLINVENTORYENTRIES.LIST>`. Expense ledger instead of Purchase ledger.
- **Goods**: `<ALLINVENTORYENTRIES.LIST>` with HSN, unit, GST class.

## Balance Check Formula

After removing `<BILLALLOCATIONS.LIST>` and `<ALLINVENTORYENTRIES.LIST>`:
```
sum of all <AMOUNT> values should be 0
```
