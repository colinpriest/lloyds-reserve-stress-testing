# Lloyd's syndicate numbers extracted from US Treasury list (January 2025)
# Source: https://www.fiscal.treasury.gov/files/surety-bonds/list-lloyds-list.pdf

# Active syndicates (Page 1)
ACTIVE_SYNDICATES = [
    33, 318, 382, 435, 457, 510, 566, 609, 623, 626, 727,
    1036, 1084, 1100, 1176, 1183, 1200, 1218, 1221, 1225, 1274, 1301, 1322, 1414, 1458, 1492,
    1609, 1618, 1686, 1699, 1729, 1796, 1856, 1880, 1886, 1902, 1910, 1919, 1922, 1945, 1947,
    1955, 1966, 1967, 1969, 1971, 1985, 1988, 1996,
    2001, 2003, 2010, 2015, 2019, 2050, 2121, 2232, 2357, 2358, 2488, 2623, 2689, 2786, 2791, 2843, 2987, 2988,
    3000, 3010, 3033, 3123, 3456, 3623, 3624, 3832, 3902, 3939,
    4000, 4020, 4141, 4242, 4321, 4444, 4472, 4711, 4747,
    5000, 5183, 5555, 5623, 5886
]

# Reinsured to close syndicates (Pages 2-3) - may have historical data
RITC_SYNDICATES = [
    2, 28, 34, 40, 47, 48, 51, 52, 53, 55, 62, 79, 102, 112, 122, 123, 136, 138, 159,
    172, 173, 178, 179, 183, 187, 190, 204, 205, 218, 219, 227, 228, 250, 270, 271, 282,
    314, 322, 328, 329, 340, 360, 362, 375, 376, 386, 397, 431, 441, 456, 473, 483, 484,
    488, 490, 500, 506, 507, 529, 535, 536, 538, 539, 545, 552, 557, 570, 575, 582, 588, 590,
    624, 625, 658, 672, 683, 702, 718, 724, 732, 734, 735, 741, 744, 765, 766, 780, 800, 807, 808,
    822, 823, 824, 839, 858, 861, 902, 920, 923, 925, 947, 955, 957, 958, 959, 960, 963, 990, 991, 994, 998,
    1003, 1007, 1009, 1010, 1019, 1023, 1027, 1028, 1038, 1047, 1051, 1055, 1057, 1069, 1087, 1093, 1095, 1096, 1101,
    1115, 1119, 1121, 1124, 1141, 1165, 1173, 1175, 1179, 1185, 1202, 1203, 1204, 1205, 1206, 1207, 1208, 1209,
    1210, 1211, 1212, 1213, 1214, 1215, 1219, 1223, 1224, 1227, 1229, 1232, 1234, 1236, 1239, 1241, 1242, 1243, 1245,
    1251, 1265, 1308, 1318, 1323, 1400, 1411, 1415, 1511, 1607, 1611, 1688, 1861, 1882, 1884, 1897, 1900, 1980, 1991, 1999,
    2000, 2007, 2011, 2014, 2020, 2021, 2027, 2088, 2147, 2176, 2183, 2227, 2241, 2243, 2271, 2322, 2323, 2341, 2345, 2376,
    2468, 2490, 2506, 2526, 2591, 2607, 2658, 2659, 2724, 2734, 2741, 2923, 2947,
    3030, 3210, 3268, 3334, 3786, 3820, 4040, 5151, 5678, 5820
]

# Run-off syndicates (Page 4)
RUNOFF_SYNDICATES = [1110, 1975, 1840]

# All syndicates to check (prioritize active, then RITC for historical data)
ALL_SYNDICATES = sorted(set(ACTIVE_SYNDICATES + RITC_SYNDICATES + RUNOFF_SYNDICATES))

# Years available online
ONLINE_YEARS = list(range(2014, 2025))  # 2014-2024

# Life syndicates to exclude (based on feasibility assessment)
LIFE_SYNDICATES = [779]  # Add others as identified

def get_syndicates_to_scrape():
    """Return list of syndicates excluding known life syndicates."""
    return [s for s in ALL_SYNDICATES if s not in LIFE_SYNDICATES]

if __name__ == "__main__":
    syndicates = get_syndicates_to_scrape()
    print(f"Total syndicates to check: {len(syndicates)}")
    print(f"Years available: {ONLINE_YEARS[0]}-{ONLINE_YEARS[-1]}")
    print(f"Maximum potential syndicate-years: {len(syndicates) * len(ONLINE_YEARS)}")
