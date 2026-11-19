/* ============================================================
   Active Life Medical — Featured products (home page strip)

   The strip shows a rotating batch of products drawn from
   FEATURED_POOL. Admins: edit FEATURED_POOL to control which
   products can be featured (display order is the pool order;
   duplicates are ignored; IDs not in the catalog are skipped).
   Every ROTATION.interval the strip advances to the next batch,
   so the home page shows a different selection over time.

   The chosen batch is pinned per visitor session (sessionStorage):
   it never flips while someone is browsing the site, and only
   rotates on their next visit. No build step — changes take
   effect on the next page load.
   ============================================================ */

/* exported FEATURED_POOL, ROTATION, getFeaturedProducts */
/* global getProductById */

const ROTATION_STORAGE_KEY = "md_featured_rotation";

const ROTATION = {
  // How often the strip swaps to the next batch: "daily" or "weekly".
  interval: "daily",
  // How many products to show in the strip at once.
  count: 6
};

const FEATURED_POOL = [
  "dg-001", // ClearTone Digital Stethoscope
  "dg-002", // OtoView LED Otoscope Set
  "dg-003", // PulseCheck Fingertip Oximeter
  "dg-004", // AccuTemp Infrared Thermometer
  "mb-001", // GlideRest Folding Wheelchair
  "mb-002", // StrideSure Rollator Walker
  "mb-003", // EasyGrip Adjustable Cane
  "mb-004", // TransferPro Bed Rail
  "mn-001", // VitalSync Patient Monitor
  "mn-002", // HomeCuff Auto Blood Pressure Monitor
  "mn-003", // GlucoTrack Blood Glucose Meter
  "mn-004", // SleepGuard Apnea Monitor
  "sg-001", // PrecisionEdge Surgical Scissors Set
  "sg-002", // ClampSecure Hemostatic Forceps
  "sg-003", // SutureMaster Needle Holder
  "sg-004", // ClearView Surgical Retractor Set
  "pp-001", // ShieldFit N95 Respirator (20-pack)
  "pp-002", // SafeTouch Nitrile Exam Gloves (100-pack)
  "pp-003", // ClearGuard Face Shield (10-pack)
  "pp-004", // BioBarrier Isolation Gown
  "hc-001", // ComfortRise Adjustable Bed Frame
  "hc-002", // SteadyStep Bathroom Safety Kit
  "hc-003", // TheraBand Resistance Rehab Set
  "hc-004" // NightWatch Bedside Commode
];

/** Days since the start of the current year (0-based). */
function dayOfYear(date) {
  const start = new Date(date.getFullYear(), 0, 1);
  return Math.floor((date - start) / 86400000);
}

/** A rotation index that advances by 1 every interval (day or week). */
function rotationIndex(date) {
  const days = dayOfYear(date);
  return ROTATION.interval === "weekly" ? Math.floor(days / 7) : days;
}

function readStoredGroup() {
  try {
    const raw = sessionStorage.getItem(ROTATION_STORAGE_KEY);
    const n = raw === null ? NaN : Number(raw);
    return Number.isInteger(n) && n >= 0 ? n : null;
  } catch (e) {
    return null;
  }
}

function writeStoredGroup(group) {
  try {
    sessionStorage.setItem(ROTATION_STORAGE_KEY, String(group));
  } catch (e) {
    // Storage unavailable — the strip still rotates by date.
  }
}

function sessionGroup(groups) {
  let group = readStoredGroup();
  if (group === null || group >= groups) {
    group = rotationIndex(new Date()) % groups;
    writeStoredGroup(group);
  }
  return group;
}

function getFeaturedProducts(date) {
  const pool = [...new Set(FEATURED_POOL)]
    .map(getProductById)
    .filter(Boolean)
    .filter(p => p.stock > 0);
  if (pool.length === 0) return [];
  const count = Math.min(ROTATION.count, pool.length);
  const groups = Math.ceil(pool.length / count);
  const group = date === undefined ? sessionGroup(groups) : rotationIndex(date) % groups;
  const start = group * count;
  const batch = pool.slice(start, start + count);
  return batch.length === count ? batch : [...batch, ...pool.slice(0, count - batch.length)];
}
