"""PMD tracker board: the single source of truth for parts, nets and placement.

generate.py turns this into the KiCad schematic, symbol/footprint libs and PCB.
Pin numbers come from the KiCad 10 library symbols (MDBT50Q module, MAX-M10S,
MCP73831, AP2112K, USB-C, TC2030), cross-checked against the u-blox MAX-M10S, ADI ADXL372
Rev. C and ST LSM6DSO datasheets for those parts. The LSM6DSO uses KiCad's LGA-14
3 x 2.5 mm land pattern (the LSM6DS3/DSL package); ST lists the LSM6DSO in the same
2.5 x 3.0 x 0.83 mm LGA-14L package.
"""

NC = None  # pin deliberately left unconnected (gets a no-connect flag)

# ref: (lib_id, footprint, value, {pin: net}, (x_mm, y_mm, rot_deg) on the 45 x 30 board)
PARTS = {
    # nRF52840 module, normal-voltage mode (VDD = VDDH = 3V3). Antenna end at the top board edge.
    "U1": ("RF_Module:MDBT50Q-1MV2", "RF_Module:Raytac_MDBT50Q", "MDBT50Q-1MV2", {
        "1": "GND", "2": "GND", "15": "GND", "33": "GND", "55": "GND",
        "28": "+3V3", "30": "+3V3", "31": NC, "32": "VBUS",
        "34": "USB_DN", "35": "USB_DP",
        "51": "SWDIO", "53": "SWDCLK", "40": "NRST",                 # P0.18 = nRESET
        "37": "SPI_SCK", "39": "SPI_MOSI", "41": "SPI_MISO",         # P0.13 / P0.15 / P0.17
        "44": "ADXL_CS", "46": "IMU_CS",                             # P0.20 / P0.22
        "48": "ADXL_INT1", "26": "IMU_INT1",                         # P0.24 / P1.09
        "22": "UART_TX", "24": "UART_RX",                            # P0.06 / P0.08
        "16": "GNSS_RESET_N", "20": "VBAT_SENSE", "12": "LED",       # P0.27 / P0.04 (AIN2) / P0.31
    }, (22.5, 8.3, 0)),
    # GNSS. VIO_SEL open = 3.3 V I/O. Passive antenna via u.FL (module has an internal LNA + SAW).
    "U2": ("RF_GPS:MAX-M10S", "RF_GPS:ublox_MAX", "MAX-M10S", {
        "1": "GND", "10": "GND", "12": "GND",
        "2": "UART_RX", "3": "UART_TX", "4": NC, "5": NC,
        "6": "+3V3", "7": "+3V3", "8": "+3V3", "9": "GNSS_RESET_N",
        "11": "GNSS_RF", "13": NC, "14": NC, "15": NC, "16": NC, "17": NC, "18": NC,
    }, (37.5, 6.5, 0)),
    "J2": ("Connector:Conn_Coaxial", "Connector_Coaxial:U.FL_Hirose_U.FL-R-SMT-1_Vertical", "U.FL",
           {"1": "GNSS_RF", "2": "GND"}, (41.5, 15.5, 0)),
    # High-g accelerometer, SPI. Reserved pins to GND per datasheet.
    "U3": ("pmd:ADXL372", "pmd:ADI_LGA-16_3x3.25mm_P0.5mm", "ADXL372", {
        "1": "+3V3", "2": NC, "3": "GND", "4": "SPI_SCK", "5": "GND", "6": "SPI_MOSI",
        "7": "SPI_MISO", "8": "ADXL_CS", "9": NC, "10": "GND", "11": "ADXL_INT1",
        "12": "GND", "13": "GND", "14": "+3V3", "15": NC, "16": "GND",
    }, (35.0, 22.5, 0)),
    # 6-axis IMU, SPI mode 1: SDx/SCx to GND, aux pins open.
    "U4": ("pmd:LSM6DSO", "Package_LGA:LGA-14_3x2.5mm_P0.5mm_LayoutBorder3x4y", "LSM6DSO", {
        "1": "SPI_MISO", "2": "GND", "3": "GND", "4": "IMU_INT1", "5": "+3V3", "6": "GND",
        "7": "GND", "8": "+3V3", "9": NC, "10": NC, "11": NC, "12": "IMU_CS",
        "13": "SPI_SCK", "14": "SPI_MOSI",
    }, (28.0, 22.5, 0)),
    # LiPo charger. PROG 4.7k -> ~213 mA (0.4C for 500 mAh). STAT drives the charge LED.
    "U5": ("Battery_Management:MCP73831-2-OT", "Package_TO_SOT_SMD:SOT-23-5", "MCP73831-2-OT", {
        "1": "CHG_STAT", "2": "GND", "3": "VBAT", "4": "VBUS", "5": "PROG",
    }, (5.0, 9.5, 0)),
    # 3V3 LDO from the cell. GNSS inrush is up to 100 mA, too much for the nRF's own regulator.
    "U6": ("Regulator_Linear:AP2112K-3.3", "Package_TO_SOT_SMD:SOT-23-5", "AP2112K-3.3", {
        "1": "VBAT", "2": "GND", "3": "VBAT", "4": NC, "5": "+3V3",
    }, (11.5, 9.5, 0)),
    "J1": ("Connector:USB_C_Receptacle_USB2.0_16P", "Connector_USB:USB_C_Receptacle_HRO_TYPE-C-31-M-12",
           "USB-C", {
               "A1": "GND", "A12": "GND", "B1": "GND", "B12": "GND", "SH": "GND",
               "A4": "VBUS", "A9": "VBUS", "B4": "VBUS", "B9": "VBUS",
               "A5": "CC1", "B5": "CC2", "A6": "USB_DP", "B6": "USB_DP",
               "A7": "USB_DN", "B7": "USB_DN", "A8": NC, "B8": NC,
           }, (8.0, 26.3, 0)),  # receptacle front flush with the board edge
    "J3": ("Connector_Generic:Conn_01x02", "Connector_JST:JST_PH_S2B-PH-SM4-TB_1x02-1MP_P2.00mm_Horizontal",
           "JST PH 2-pin (battery)", {"1": "VBAT", "2": "GND"}, (21.0, 24.8, 180)),
    "J4": ("Connector:Conn_ARM_SWD_TagConnect_TC2030-NL", "Connector:Tag-Connect_TC2030-IDC-NL_2x03_P1.27mm_Vertical",
           "SWD", {"1": "+3V3", "2": "SWDIO", "3": "NRST", "4": "SWDCLK", "5": "GND", "6": NC},
           (34.8, 15.4, 0)),
    "D1": ("Device:LED", "LED_SMD:LED_0603_1608Metric", "Green", {"1": "GND", "2": "LED_A"}, (10.0, 4.0, 0)),
    "D2": ("Device:LED", "LED_SMD:LED_0603_1608Metric", "Red", {"1": "CHG_STAT", "2": "CHG_A"}, (1.6, 10.0, 90)),
}

R0402 = "Resistor_SMD:R_0402_1005Metric"
C0402 = "Capacitor_SMD:C_0402_1005Metric"
C0603 = "Capacitor_SMD:C_0603_1608Metric"

PASSIVES = {
    "R1": ("Device:R", R0402, "5.1k", ("CC1", "GND"), (14.8, 18.5, 90)),
    "R2": ("Device:R", R0402, "5.1k", ("CC2", "GND"), (1.6, 18.5, 90)),
    "R3": ("Device:R", R0402, "4.7k", ("PROG", "GND"), (5.0, 15.0, 0)),
    "R4": ("Device:R", R0402, "1k", ("VBUS", "CHG_A"), (1.6, 14.5, 90)),
    "R5": ("Device:R", R0402, "1k", ("LED", "LED_A"), (6.5, 4.0, 0)),
    "R6": ("Device:R", R0402, "1M", ("VBAT", "VBAT_SENSE"), (8.5, 17.0, 0)),
    "R7": ("Device:R", R0402, "1M", ("VBAT_SENSE", "GND"), (8.5, 18.6, 0)),
    "C1": ("Device:C", C0603, "4.7u", ("VBUS", "GND"), (5.0, 13.0, 0)),
    "C2": ("Device:C", C0603, "4.7u", ("VBAT", "GND"), (11.5, 13.0, 0)),
    "C3": ("Device:C", C0402, "1u", ("VBAT", "GND"), (11.5, 15.0, 0)),
    "C4": ("Device:C", C0603, "10u", ("+3V3", "GND"), (14.8, 9.5, 90)),
    "C5": ("Device:C", C0402, "100n", ("+3V3", "GND"), (15.6, 14.0, 90)),
    "C6": ("Device:C", C0603, "10u", ("+3V3", "GND"), (29.9, 13.5, 90)),
    "C7": ("Device:C", C0402, "100n", ("+3V3", "GND"), (29.9, 10.0, 90)),
    "C8": ("Device:C", C0402, "100n", ("+3V3", "GND"), (35.0, 19.3, 0)),
    "C9": ("Device:C", C0402, "100n", ("+3V3", "GND"), (35.0, 25.6, 0)),
    "C10": ("Device:C", C0402, "100n", ("+3V3", "GND"), (28.0, 25.6, 0)),
    "C11": ("Device:C", C0402, "100n", ("+3V3", "GND"), (28.0, 19.3, 0)),
    "C12": ("Device:C", C0402, "100n", ("VBAT_SENSE", "GND"), (12.0, 17.5, 0)),
}

for ref, (lib, fp, val, (a, b), pos) in PASSIVES.items():
    PARTS[ref] = (lib, fp, val, {"1": a, "2": b}, pos)

# Manufacturer part numbers for the BOM (passives are generic).
MPN = {
    "U1": "MDBT50Q-1MV2", "U2": "MAX-M10S-00B", "U3": "ADXL372BCCZ-RL7", "U4": "LSM6DSOTR",
    "U5": "MCP73831T-2ACI/OT", "U6": "AP2112K-3.3TRG1", "J1": "TYPE-C-31-M-12",
    "J2": "U.FL-R-SMT-1(10)", "J3": "S2B-PH-SM4-TB(LF)(SN)",
}

# Nets with no output pin driving them need a PWR_FLAG for ERC.
PWR_FLAGS = ["GND", "VBUS"]

BOARD_W, BOARD_H, CORNER_R = 45.0, 30.0, 3.0
NETCLASSES = {
    "Power": (0.4, ["VBAT", "VBUS"]),  # charge path
    "Rails": (0.25, ["GND", "+3V3"]),  # mostly carried by the inner planes; narrow enough to escape 0.5 mm LGA pads
    # ~50 ohm microstrip over In1 GND on a standard JLC 4-layer stackup; keep it short.
    "RF": (0.35, ["GNSS_RF"]),
}
DEFAULT_TRACK, CLEARANCE, VIA_D, VIA_DRILL = 0.15, 0.15, 0.6, 0.3


def nets():
    out = {}
    for ref, (_, _, _, pins, _) in PARTS.items():
        for pin, net in pins.items():
            if net:
                out.setdefault(net, []).append((ref, pin))
    return out


if __name__ == "__main__":
    n = nets()
    single = [k for k, v in n.items() if len(v) < 2]
    assert not single, f"single-pin nets: {single}"
    for k in sorted(n):
        print(f"{k:14s} {len(n[k]):2d}  " + " ".join(f"{r}.{p}" for r, p in n[k]))
