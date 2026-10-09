/* PMD tracker: GNSS + high-g accel -> on-device match metrics,
 * checkpointed to flash and read over BLE by the companion app. */
#include <zephyr/kernel.h>
#include <zephyr/device.h>
#include <zephyr/drivers/gnss.h>
#include <zephyr/drivers/sensor.h>
#include <zephyr/drivers/flash.h>
#include <zephyr/fs/nvs.h>
#include <zephyr/storage/flash_map.h>
#include <zephyr/bluetooth/bluetooth.h>
#include <zephyr/bluetooth/gatt.h>
#include <zephyr/bluetooth/uuid.h>
#include <zephyr/logging/log.h>

#include "metrics.h"

LOG_MODULE_REGISTER(pmd, LOG_LEVEL_INF);

#define ACCEL_PERIOD_MS 2      /* ~500 Hz poll; ponytail: move to ADXL372 FIFO if hits are missed */
#define CHECKPOINT_MS   10000
#define NVS_SUMMARY_ID  1

static const struct device *const gnss = DEVICE_DT_GET(DT_NODELABEL(gnss));
static const struct device *const hg = DEVICE_DT_GET(DT_NODELABEL(adxl372));

static pmd_state st;
static K_MUTEX_DEFINE(st_lock);
static struct nvs_fs nvs;

/* ---- GNSS (10 Hz, set by fix-rate in the overlay) ---- */

static void on_gnss(const struct device *dev, const struct gnss_data *d)
{
	if (d->info.fix_status == GNSS_FIX_STATUS_NO_FIX) {
		return;
	}
	k_mutex_lock(&st_lock, K_FOREVER);
	pmd_gnss(&st, k_uptime_get_32(), d->nav_data.latitude / 1e9, d->nav_data.longitude / 1e9);
	k_mutex_unlock(&st_lock);
}
GNSS_DATA_CALLBACK_DEFINE(DEVICE_DT_GET(DT_NODELABEL(gnss)), on_gnss);

/* ---- High-g accel ---- */

static void accel_thread(void)
{
	struct sensor_value v[3];

	while (1) {
		if (sensor_sample_fetch(hg) == 0 &&
		    sensor_channel_get(hg, SENSOR_CHAN_ACCEL_XYZ, v) == 0) {
			k_mutex_lock(&st_lock, K_FOREVER);
			pmd_accel(&st, k_uptime_get_32(),
				  sensor_value_to_float(&v[0]) / SENSOR_G * 1e6f,
				  sensor_value_to_float(&v[1]) / SENSOR_G * 1e6f,
				  sensor_value_to_float(&v[2]) / SENSOR_G * 1e6f);
			k_mutex_unlock(&st_lock);
		}
		k_msleep(ACCEL_PERIOD_MS);
	}
}
K_THREAD_DEFINE(accel_tid, 1024, accel_thread, NULL, NULL, NULL, 5, 0, 0);

/* ---- BLE: one read (summary) and one write (reset) characteristic ---- */

#define PMD_UUID(n) BT_UUID_128_ENCODE(0x9d1e0000 + (n), 0x5a1b, 0x4c6e, 0x8f2d, 0x3b7a6c1e2f40)
static const struct bt_uuid_128 svc_uuid = BT_UUID_INIT_128(PMD_UUID(0));
static const struct bt_uuid_128 sum_uuid = BT_UUID_INIT_128(PMD_UUID(1));
static const struct bt_uuid_128 rst_uuid = BT_UUID_INIT_128(PMD_UUID(2));

static ssize_t read_summary(struct bt_conn *c, const struct bt_gatt_attr *a, void *buf,
			    uint16_t len, uint16_t off)
{
	pmd_summary snap;

	k_mutex_lock(&st_lock, K_FOREVER);
	snap = st.sum;
	k_mutex_unlock(&st_lock);
	return bt_gatt_attr_read(c, a, buf, len, off, &snap, sizeof(snap));
}

static ssize_t write_reset(struct bt_conn *c, const struct bt_gatt_attr *a, const void *buf,
			   uint16_t len, uint16_t off, uint8_t flags)
{
	pmd_config cfg = pmd_default_config();

	k_mutex_lock(&st_lock, K_FOREVER);
	pmd_init(&st, &cfg);
	k_mutex_unlock(&st_lock);
	nvs_delete(&nvs, NVS_SUMMARY_ID);
	return len;
}

BT_GATT_SERVICE_DEFINE(pmd_svc,
	BT_GATT_PRIMARY_SERVICE(&svc_uuid),
	BT_GATT_CHARACTERISTIC(&sum_uuid.uuid, BT_GATT_CHRC_READ, BT_GATT_PERM_READ,
			       read_summary, NULL, NULL),
	BT_GATT_CHARACTERISTIC(&rst_uuid.uuid, BT_GATT_CHRC_WRITE, BT_GATT_PERM_WRITE,
			       NULL, write_reset, NULL));

static const struct bt_data ad[] = {
	BT_DATA_BYTES(BT_DATA_FLAGS, BT_LE_AD_GENERAL | BT_LE_AD_NO_BREDR),
	BT_DATA_BYTES(BT_DATA_UUID128_ALL, PMD_UUID(0)),
};
static const struct bt_data sd[] = {
	BT_DATA(BT_DATA_NAME_COMPLETE, CONFIG_BT_DEVICE_NAME, sizeof(CONFIG_BT_DEVICE_NAME) - 1),
};

/* ---- Flash checkpoint: survives a battery pull mid-match ---- */

static int nvs_setup(void)
{
	struct flash_pages_info info;

	nvs.flash_device = FIXED_PARTITION_DEVICE(storage_partition);
	nvs.offset = FIXED_PARTITION_OFFSET(storage_partition);
	if (flash_get_page_info_by_offs(nvs.flash_device, nvs.offset, &info)) {
		return -EIO;
	}
	nvs.sector_size = info.size;
	nvs.sector_count = FIXED_PARTITION_SIZE(storage_partition) / info.size;
	return nvs_mount(&nvs);
}

int main(void)
{
	pmd_config cfg = pmd_default_config();

	pmd_init(&st, &cfg);
	if (!device_is_ready(gnss) || !device_is_ready(hg)) {
		LOG_ERR("sensor not ready");
		return 0;
	}
	if (nvs_setup() == 0 &&
	    nvs_read(&nvs, NVS_SUMMARY_ID, &st.sum, sizeof(st.sum)) == sizeof(st.sum)) {
		/* ponytail: restores totals only; the next fix re-seeds position */
		LOG_INF("restored session: %u m", (unsigned)st.sum.distance_m);
	}
	if (bt_enable(NULL) == 0) {
		bt_le_adv_start(BT_LE_ADV_CONN_FAST_1, ad, ARRAY_SIZE(ad), sd, ARRAY_SIZE(sd));
	}

	while (1) {
		k_msleep(CHECKPOINT_MS);
		pmd_summary snap;

		k_mutex_lock(&st_lock, K_FOREVER);
		snap = st.sum;
		k_mutex_unlock(&st_lock);
		nvs_write(&nvs, NVS_SUMMARY_ID, &snap, sizeof(snap)); /* NVS skips unchanged data */
	}
}
