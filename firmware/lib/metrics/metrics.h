/* Match metrics derived on-device from GNSS fixes and high-g accel samples.
 * Portable C, no Zephyr dependency, no malloc: host-testable (see test_metrics.c). */
#ifndef PMD_METRICS_H
#define PMD_METRICS_H

#include <stdbool.h>
#include <stdint.h>

/* Heatmap grid: 12 x 8 cells of 10 m covers a 120 x 80 m area from the origin
 * (pitch plus in-goal). Sized so the summary fits one 512-byte BLE attribute. */
#define PMD_GRID_W 12
#define PMD_GRID_H 8

/* Calibration knobs. Defaults are placeholders: tune them against real
 * sessions before trusting any number. */
typedef struct {
	float speed_alpha;      /* EMA weight on new speed sample, 0..1 */
	float max_speed_mps;    /* faster step = GNSS glitch, rejected */
	float min_speed_mps;    /* slower step = standing jitter, no distance */
	float sprint_entry_mps; /* smoothed speed that starts a sprint */
	float sprint_exit_mps;  /* smoothed speed that ends it (hysteresis) */
	uint32_t sprint_min_ms; /* shorter efforts are not counted */
	float impact_g;         /* |a| at or above this starts an impact */
	uint32_t impact_refractory_ms; /* samples within this window are the same impact */
	float impact_band_g[2]; /* low < [0] <= medium < [1] <= high */
	float cell_m;           /* heatmap cell size */
	double origin_lat, origin_lon; /* heatmap origin; 0,0 = first fix */
	float pitch_heading_rad; /* rotation of the pitch long axis from east */
} pmd_config;

/* Sent over BLE as raw little-endian bytes: field order has no padding
 * (228 bytes) and the app decodes it in this order. Append, don't reorder. */
typedef struct {
	float distance_m;
	float max_speed_mps;
	float sprint_distance_m;
	float impact_peak_g;
	float impact_load_g;      /* sum of per-impact peaks */
	uint32_t active_ms;       /* time with a GNSS fix */
	uint16_t sprint_count;
	uint16_t impact_count;
	uint16_t impact_bands[3]; /* low, medium, high */
	uint16_t heatmap_s[PMD_GRID_H][PMD_GRID_W]; /* seconds spent per cell, row = 10 m up-pitch */
	uint16_t off_grid_s;
} pmd_summary;

typedef struct {
	pmd_config cfg;
	pmd_summary sum;
	bool have_fix;
	uint32_t last_ms;
	double cos_lat0;
	float x, y, speed;        /* metres from origin, smoothed m/s */
	uint32_t heat_ms_acc;     /* sub-second remainder for heatmap */
	bool in_sprint;
	uint32_t sprint_start_ms;
	float sprint_dist;
	bool in_impact;
	uint32_t impact_start_ms;
	float impact_peak;
} pmd_state;

pmd_config pmd_default_config(void);
void pmd_init(pmd_state *s, const pmd_config *c);
void pmd_gnss(pmd_state *s, uint32_t t_ms, double lat, double lon);
void pmd_accel(pmd_state *s, uint32_t t_ms, float ax_g, float ay_g, float az_g);
/* Closes any open sprint/impact. Call at session end before reading s->sum. */
void pmd_finish(pmd_state *s);
/* Metres per minute over active time. */
float pmd_work_rate(const pmd_summary *sum);

#endif
