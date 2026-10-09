# PMD Tracker

A wearable performance tracker for rugby. It sits in a jersey pouch between the shoulder blades, records a player's match, and syncs the results to a companion app for review after the game.

![System block diagram](docs/block-diagram.svg)

## What it measures

| Area | Metrics |
|---|---|
| Locomotion | distance, max speed, sprint count and sprint distance |
| Contact load | impact count, peak g, total load, impacts by intensity band |
| Position | time-on-pitch heatmap (10 m cells), work rate in m/min |

## How it works

1. **Sensing.** A u-blox MAX-M10S GNSS module gives position at 10 Hz. An ADXL372 high-g accelerometer (±200 g) catches impacts that a normal IMU would clip. An LSM6DSO 6-axis IMU is part of the design but is not used by the metrics yet.
2. **On-device metrics.** The nRF52840 runs Zephyr RTOS. Every fix and accel sample goes through [`firmware/lib/metrics`](firmware/lib/metrics), which is portable C:
   - **Position.** Each fix is projected to metres from a pitch origin.
   - **Distance.** Fixes that imply more than 12 m/s are rejected as GNSS glitches. Steps under 0.3 m/s count as standing jitter and add no distance.
   - **Speed and sprints.** Speed is an exponential moving average. A sprint starts above 7 m/s and ends below 6 m/s. It only counts if it lasts at least 1 s.
   - **Impacts.** An impact starts when |a| ≥ 8 g. Samples in the next 250 ms count as the same hit, and its peak is the hit's intensity.
   - **Heatmap.** The time spent at each position is binned into a grid in the pitch frame.
3. **Storage.** A summary checkpoint is written to flash (NVS) every 10 s, so a battery pull mid-match keeps the totals.
4. **Sync.** The device advertises over Bluetooth LE as `PMD`. The app reads one 228-byte summary characteristic (layout in [`metrics.h`](firmware/lib/metrics/metrics.h)). It writes the reset characteristic to start a new session.

Every threshold above sits in one `pmd_config` struct. They are starting values and still need calibrating against real sessions.

## Design targets

The device is designed against World Rugby Law 4.3(m), Regulation 12 and the Player Monitoring Device Performance Specification:

- total mass under 90 g
- no surface radius below 12 mm
- enclosure survives the specification's impact test and 2.5 kN compression test without rupture

| Part | Component |
|---|---|
| MCU | nRF52840 (BLE 5), custom 4-layer PCB |
| GNSS | u-blox MAX-M10S, 10 Hz |
| High-g accel | ADXL372 |
| IMU | LSM6DSO |
| Battery | 500 mAh LiPo |

The BOM is in [`hardware/bom.csv`](hardware/bom.csv).

## Repository layout

```
firmware/
  lib/metrics/     portable C metrics + host self-test
  src/main.c       Zephyr app: sensors, GNSS, flash checkpoint, BLE service
  boards/          devicetree overlay (nRF52840-DK bring-up wiring)
hardware/
  bom.csv
docs/
  block-diagram.svg
```

## Building

Test the metrics on a PC. Any C compiler works:

```
cd firmware/lib/metrics
cc -std=c11 -Wall test_metrics.c metrics.c -lm -o test && ./test
```

Build the firmware (needs Zephyr 4.x and `west`). The nRF52840-DK overlay is used for bring-up:

```
west build -b nrf52840dk/nrf52840 firmware
west flash
```

## Status

- [x] Metrics library with a host self-test
- [ ] Zephyr firmware: GNSS, high-g accel, flash checkpoint, BLE sync (written, not yet built against Zephyr or run on hardware)
- [ ] Custom PCB schematic and layout (KiCad)
- [ ] Gerbers
- [ ] Enclosure
- [ ] Companion app
