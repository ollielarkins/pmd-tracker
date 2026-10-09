/* Host self-check: zig cc test_metrics.c metrics.c -lm -o t && ./t */
#include "metrics.h"

#include <assert.h>
#include <math.h>
#include <stdio.h>

#define LAT0 52.03   /* roughly Bedfordshire; any value works */
#define LON0 -0.49
#define M_PER_DEG_LAT 111194.93

static double lat_at(float north_m) { return LAT0 + north_m / M_PER_DEG_LAT; }

int main(void)
{
	pmd_config c = pmd_default_config();
	pmd_state s;
	pmd_init(&s, &c);

	/* 10 Hz north: 10 s jog at 3 m/s, 4 s sprint at 9 m/s, 10 s jog, one 500 m glitch. */
	float y = 0;
	uint32_t t = 0;
	for (int i = 0; i <= 240; i++, t += 100) {
		float v = (i > 100 && i <= 140) ? 9.0f : 3.0f;
		if (i) {
			y += v * 0.1f;
		}
		pmd_gnss(&s, t, i == 200 ? lat_at(y + 500) : lat_at(y), LON0);
	}

	/* Impacts: one 20 g hit with ringing (same event), one 40 g hit, sub-threshold noise. */
	pmd_accel(&s, 5000, 0, 0, 1);
	pmd_accel(&s, 5010, 12, 0, 0);
	pmd_accel(&s, 5020, 0, 20, 0);
	pmd_accel(&s, 5100, 9, 0, 0);
	pmd_accel(&s, 9000, 0, 40, 0);
	pmd_accel(&s, 12000, 3, 0, 0);
	pmd_finish(&s);

	const pmd_summary *r = &s.sum;
	float expect = 10 * 3 + 4 * 9 + 10 * 3; /* 96 m */
	printf("dist %.1f m (expect %.0f), max %.2f m/s, sprints %u (%.1f m), impacts %u bands %u/%u/%u peak %.0f g load %.0f g, %.1f m/min\n",
	       r->distance_m, expect, r->max_speed_mps, r->sprint_count, r->sprint_distance_m,
	       r->impact_count, r->impact_bands[0], r->impact_bands[1], r->impact_bands[2],
	       r->impact_peak_g, r->impact_load_g, pmd_work_rate(r));

	assert(fabsf(r->distance_m - expect) < 4.0f); /* glitch rejection costs one bridged step */
	assert(r->max_speed_mps > 8.0f && r->max_speed_mps < 9.1f);
	assert(r->sprint_count == 1);
	assert(r->sprint_distance_m > 20.0f && r->sprint_distance_m < 40.0f);
	assert(r->impact_count == 2);
	assert(r->impact_bands[1] == 1 && r->impact_bands[2] == 1);
	assert(fabsf(r->impact_peak_g - 40.0f) < 0.01f);
	assert(fabsf(r->impact_load_g - 60.0f) < 0.01f);
	assert(r->active_ms == 24000);

	/* All 24 s lie in column 0, rows 0..9 (96 m north = 10 cells, last 2 off the 8-row grid). */
	unsigned total = r->off_grid_s;
	for (int gy = 0; gy < PMD_GRID_H; gy++)
		for (int gx = 0; gx < PMD_GRID_W; gx++)
			total += r->heatmap_s[gy][gx];
	assert(total == 24);
	assert(r->heatmap_s[0][0] > 0 && r->off_grid_s > 0);

	/* A short burst over the entry speed is not a sprint. */
	pmd_init(&s, &c);
	y = 0;
	t = 0;
	for (int i = 0; i <= 60; i++, t += 100) {
		float v = (i > 20 && i <= 25) ? 9.0f : 2.0f;
		if (i) {
			y += v * 0.1f;
		}
		pmd_gnss(&s, t, lat_at(y), LON0);
	}
	pmd_finish(&s);
	assert(s.sum.sprint_count == 0);

	_Static_assert(sizeof(pmd_summary) == 228, "BLE layout changed: update the app decoder");
	puts("ok");
	return 0;
}
