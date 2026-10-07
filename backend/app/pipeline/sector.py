"""Map SEC SIC codes to about 25 readable sector groups.

SIC codes come from each company's EDGAR submissions record. The groups are ours, chosen so
that sector medians compare businesses that look alike. Ranges are checked in order, so a
narrow range listed early wins over a broad one listed later.
"""

# (low, high, sector), inclusive. Order matters: specific ranges before broad ones.
_RANGES: list[tuple[int, int, str]] = [
    (100, 999, "Agriculture"),
    (1000, 1299, "Metals and mining"),
    (1300, 1399, "Oil and gas"),
    (1400, 1499, "Metals and mining"),
    (1500, 1799, "Homebuilding and construction"),
    (2000, 2099, "Food and beverage"),
    (2100, 2199, "Tobacco"),
    (2200, 2399, "Apparel and textiles"),
    (2400, 2499, "Building products"),
    (2500, 2599, "Household products"),
    (2600, 2699, "Paper and packaging"),
    (2700, 2799, "Media"),
    (2833, 2836, "Pharma and biotech"),
    (2840, 2844, "Household products"),
    (2800, 2899, "Chemicals"),
    (2900, 2999, "Oil and gas"),
    (3000, 3099, "Chemicals"),
    (3100, 3199, "Apparel and textiles"),
    (3200, 3299, "Building products"),
    (3300, 3399, "Steel and metals"),
    (3400, 3499, "Industrial machinery"),
    (3570, 3579, "Computer hardware"),
    (3600, 3669, "Electrical equipment"),
    (3670, 3679, "Semiconductors"),
    (3680, 3699, "Electrical equipment"),
    (3500, 3599, "Industrial machinery"),
    (3711, 3716, "Autos"),
    (3720, 3729, "Aerospace and defense"),
    (3760, 3769, "Aerospace and defense"),
    (3812, 3812, "Aerospace and defense"),
    (3700, 3799, "Autos"),
    (3841, 3851, "Medical devices"),
    (3800, 3899, "Instruments"),
    (3900, 3999, "Household products"),
    (4011, 4013, "Transportation"),
    (4512, 4522, "Airlines"),
    (4000, 4799, "Transportation"),
    (4800, 4899, "Telecom"),
    (4900, 4999, "Utilities"),
    (5000, 5199, "Wholesale"),
    (5200, 5999, "Retail"),
    (6000, 6199, "Banks"),
    (6200, 6299, "Capital markets"),
    (6300, 6499, "Insurance"),
    (6500, 6599, "Real estate"),
    (6798, 6798, "Real estate"),
    (6700, 6799, "Capital markets"),
    (7370, 7379, "Software and IT services"),
    (7000, 7099, "Hotels and leisure"),
    (7800, 7999, "Hotels and leisure"),
    (8000, 8099, "Healthcare services"),
    (7200, 8999, "Business services"),
    (9100, 9999, "Other"),
]

# Sectors the Lynch check treats as cyclical (used from phase 5).
CYCLICAL = {
    "Autos",
    "Airlines",
    "Steel and metals",
    "Chemicals",
    "Homebuilding and construction",
    "Oil and gas",
    "Semiconductors",
    "Metals and mining",
}


def sector_for_sic(sic: int | str | None) -> str | None:
    if sic in (None, ""):
        return None
    code = int(sic)
    for low, high, name in _RANGES:
        if low <= code <= high:
            return name
    return "Other"


def is_financial(sic: int | str | None) -> bool:
    """Banks and insurers (SIC 6000 to 6499) have no gross profit, EBITDA, or current ratio."""
    return sic not in (None, "") and 6000 <= int(sic) <= 6499
