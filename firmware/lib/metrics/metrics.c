#include "metrics.h"

#include <math.h>
#include <string.h>

#define EARTH_R_M 6371000.0
#define DEG2RAD (3.14159265358979323846 / 180.0)

pmd_config pmd_default_config(void)
{
	return (pmd_config){
		.speed_alpha = 0.4f,
		.max_speed_mps = 12.0f,  /* ~43 km/h, above any human sprint */
		.min_speed_mps = 0.3f,
		.sprint_entry_mps = 7.0f, /* ~25 km/h */
		.sprint_exit_mps = 6.0f,
		.sprint_min_ms = 1000,
		.impact_g = 8.0f,
		.impact_refractory_ms = 250,
		.impact_band_g = {15.0f, 30.0f},
		.cell_m = 10.0f,
	};
}

void pmd_init(pmd_state *s, const pmd_config *c)
{
	memset(s, 0, sizeof(*s));
	s->cfg = *c;
}

static void close_sprint(pmd_state *s, uint32_t t_ms)
{
	if (s->in_sprint && t_ms - s->sprint_start_ms >= s->cfg.sprint_min_ms) {
		s->sum.sprint_count++;
		s->sum.sprint_distance_m += s->sprint_dist;
	}
	s->in_sprint = false;
}

static void heat(pmd_state *s, uint32_t dt_ms)
{
	/* Rotate into the pitch frame, then bin. */
	float c = cosf(s->cfg.pitch_heading_rad), sn = sinf(s->cfg.pitch_heading_rad);
	float px = s->x * c + s->y * sn;
	float py = -s->x * sn + s->y * c;
	int gx = (int)floorf(px / s->cfg.cell_m);
	int gy = (int)floorf(py / s->cfg.cell_m);

	s->heat_ms_acc += dt_ms;
	uint16_t secs = (uint16_t)(s->heat_ms_acc / 1000);
	s->heat_ms_acc %= 1000;
	if (!secs) {
		return;
	}
	uint16_t *cell = (gx >= 0 && gx < PMD_GRID_W && gy >= 0 && gy < PMD_GRID_H)
				 ? &s->sum.heatmap_s[gy][gx]
				 : &s->sum.off_grid_s;
	*cell = (uint16_t)(*cell + secs > UINT16_MAX ? UINT16_MAX : *cell + secs);
}

void pmd_gnss(pmd_state *s, uint32_t t_ms, double lat, double lon)
{
	if (!s->have_fix) {
		if (s->cfg.origin_lat == 0.0 && s->cfg.origin_lon == 0.0) {
			s->cfg.origin_lat = lat;
			s->cfg.origin_lon = lon;
		}
		s->cos_lat0 = cos(s->cfg.origin_lat * DEG2RAD);
		/* ponytail: equirectangular projection, error is sub-cm across a pitch */
		s->x = (float)((lon - s->cfg.origin_lon) * DEG2RAD * EARTH_R_M * s->cos_lat0);
		s->y = (float)((lat - s->cfg.origin_lat) * DEG2RAD * EARTH_R_M);
		s->have_fix = true;
		s->last_ms = t_ms;
		return;
	}

	uint32_t dt_ms = t_ms - s->last_ms;
	if (dt_ms == 0) {
		return;
	}
	float x = (float)((lon - s->cfg.origin_lon) * DEG2RAD * EARTH_R_M * s->cos_lat0);
	float y = (float)((lat - s->cfg.origin_lat) * DEG2RAD * EARTH_R_M);
	float step = sqrtf((x - s->x) * (x - s->x) + (y - s->y) * (y - s->y));
	float raw = step * 1000.0f / (float)dt_ms;

	heat(s, dt_ms); /* time at the previous position */
	s->last_ms = t_ms;
	s->sum.active_ms += dt_ms; /* accumulated so a restored checkpoint keeps counting */

	if (raw > s->cfg.max_speed_mps) {
		return; /* glitch: keep the old position, the next good fix bridges it */
	}
	s->x = x;
	s->y = y;
	s->speed += s->cfg.speed_alpha * (raw - s->speed);
	if (s->speed > s->sum.max_speed_mps) {
		s->sum.max_speed_mps = s->speed;
	}
	if (raw >= s->cfg.min_speed_mps) {
		s->sum.distance_m += step;
		if (s->in_sprint) {
			s->sprint_dist += step;
		}
	}

	if (!s->in_sprint && s->speed >= s->cfg.sprint_entry_mps) {
		s->in_sprint = true;
		s->sprint_start_ms = t_ms;
		s->sprint_dist = 0.0f;
	} else if (s->in_sprint && s->speed < s->cfg.sprint_exit_mps) {
		close_sprint(s, t_ms);
	}
}

static void close_impact(pmd_state *s)
{
	if (!s->in_impact) {
		return;
	}
	float p = s->impact_peak;
	s->sum.impact_count++;
	s->sum.impact_load_g += p;
	s->sum.impact_bands[p < s->cfg.impact_band_g[0] ? 0 : p < s->cfg.impact_band_g[1] ? 1 : 2]++;
	if (p > s->sum.impact_peak_g) {
		s->sum.impact_peak_g = p;
	}
	s->in_impact = false;
}

void pmd_accel(pmd_state *s, uint32_t t_ms, float ax_g, float ay_g, float az_g)
{
	float g = sqrtf(ax_g * ax_g + ay_g * ay_g + az_g * az_g);

	if (s->in_impact && t_ms - s->impact_start_ms >= s->cfg.impact_refractory_ms) {
		close_impact(s);
	}
	if (s->in_impact) {
		if (g > s->impact_peak) {
			s->impact_peak = g;
		}
	} else if (g >= s->cfg.impact_g) {
		s->in_impact = true;
		s->impact_start_ms = t_ms;
		s->impact_peak = g;
	}
}

void pmd_finish(pmd_state *s)
{
	close_sprint(s, s->last_ms);
	close_impact(s);
}

float pmd_work_rate(const pmd_summary *sum)
{
	return sum->active_ms ? sum->distance_m * 60000.0f / (float)sum->active_ms : 0.0f;
}
