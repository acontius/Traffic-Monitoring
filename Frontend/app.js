const API_BASE = "http://localhost:8000";

/*
  چیدمان منطقی و غیر دقیق:
  - urban داخل شهر
  - highway روی لبه‌ها / مسیرهای بیرونی
  - industrial در حاشیه
*/
const CAMERA_CONFIG = {
  "cam-01": {
    type: "urban",
    label: "دوربین شهری ۱",
    lat: 35.7008,
    lng: 51.3890,
  },
  "cam-02": {
    type: "urban",
    label: "دوربین شهری ۲",
    lat: 35.7095,
    lng: 51.4060,
  },
  "cam-03": {
    type: "highway",
    label: "دوربین اتوبان ۱",
    lat: 35.7340,
    lng: 51.4480,
  },
  "cam-04": {
    type: "industrial",
    label: "دوربین صنعتی",
    lat: 35.7685,
    lng: 51.4870,
  },
  "cam-05": {
    type: "highway",
    label: "دوربین اتوبان ۲",
    lat: 35.7440,
    lng: 51.4625,
  },
};

const map = L.map("map", {
  zoomControl: true,
  minZoom: 10,
}).setView([35.724, 51.420], 11);

L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 19,
  attribution: "&copy; OpenStreetMap contributors",
}).addTo(map);

// --- خطوط جاده و مسیر ---
const urbanPath = [
  [35.705, 51.385],
  [35.700, 51.395],
  [35.709, 51.410],
  [35.712, 51.405],
];
L.polyline(urbanPath, {
  color: "#3b82f6", // Blue for urban
  weight: 5,
  opacity: 0.7,
  smoothFactor: 1
}).addTo(map).bindTooltip("مسیر شهری");

const highwayPath = [
  [35.725, 51.430],
  [35.730, 51.440],
  [35.738, 51.450],
  [35.742, 51.460],
  [35.745, 51.468],
];
L.polyline(highwayPath, {
  color: "#10b981", // Green for highway
  weight: 8,
  opacity: 0.8,
  smoothFactor: 1
}).addTo(map).bindTooltip("مسیر اتوبان");

const industrialPath = [
  [35.760, 51.475],
  [35.765, 51.482],
  [35.770, 51.490],
];
L.polyline(industrialPath, {
  color: "#64748b", // Gray for industrial
  weight: 6,
  opacity: 0.75,
  smoothFactor: 1
}).addTo(map).bindTooltip("مسیر صنعتی");
// --- پایان خطوط جاده ---

let markers = {};
let latestDataMap = {};
let selectedDeviceId = null;

const emptyStateEl = document.getElementById("empty-state");
const cameraDetailsEl = document.getElementById("camera-details");
const refreshSelectedBtn = document.getElementById("refresh-selected");

const cameraNameEl = document.getElementById("camera-name");
const cameraTypeEl = document.getElementById("camera-type");
const cameraStatusBadgeEl = document.getElementById("camera-status-badge");
const cameraTimestampEl = document.getElementById("camera-timestamp");
const cameraConnectionEl = document.getElementById("camera-connection");
const countsGridEl = document.getElementById("counts-grid");
const payloadViewerEl = document.getElementById("payload-viewer");

function safeJsonParse(value) {
  if (typeof value !== "string") return value || {};
  try {
    return JSON.parse(value);
  } catch (error) {
    console.warn("payload parse error:", error);
    return {};
  }
}

function isCameraActive(item, payload) {
  if (!item) return false;

  if (!item.payload) return false;

  if (payload && Object.keys(payload).length > 0) return true;

  return false;
}

function getConnectionText(active) {
  return active ? "متصل / فعال" : "بدون داده / غیرفعال";
}

function typeToPersian(type) {
  const mapping = {
    urban: "شهری",
    highway: "اتوبانی",
    industrial: "صنعتی",
  };
  return mapping[type] || type || "نامشخص";
}

function buildMarkerHtml(active) {
  const stateClass = active ? "camera-marker--active" : "camera-marker--inactive";

  return `
    <div class="camera-marker ${stateClass}">
      <div class="camera-marker__pulse"></div>
      <div class="camera-marker__core">
        <div class="camera-marker__icon">📷</div>
      </div>
      <div class="camera-marker__status"></div>
    </div>
  `;
}

function createDivIcon(active) {
  return L.divIcon({
    html: buildMarkerHtml(active),
    className: "",
    iconSize: [54, 54],
    iconAnchor: [27, 27],
    popupAnchor: [0, -20],
  });
}

function buildPopupHtml(deviceId, config, active, timestamp) {
  return `
    <div class="camera-popup">
      <div class="camera-popup__title">${config.label}</div>
      <div class="camera-popup__meta">
        ${deviceId} • ${typeToPersian(config.type)}
      </div>
      <div class="camera-popup__meta">
        آخرین زمان: ${timestamp || "—"}
      </div>
      <div class="camera-popup__status ${active ? "camera-popup__status--active" : "camera-popup__status--inactive"}">
        ${active ? "فعال" : "غیرفعال"}
      </div>
    </div>
  `;
}

function renderCounts(counts) {
  countsGridEl.innerHTML = "";

  const entries = Object.entries(counts || {});
  if (!entries.length) {
    countsGridEl.innerHTML = `
      <div class="count-chip">
        <div class="count-chip__label">داده‌ای ثبت نشده</div>
        <div class="count-chip__value">—</div>
      </div>
    `;
    return;
  }

  for (const [key, value] of entries) {
    const chip = document.createElement("div");
    chip.className = "count-chip";
    chip.innerHTML = `
      <div class="count-chip__label">${key}</div>
      <div class="count-chip__value">${value ?? 0}</div>
    `;
    countsGridEl.appendChild(chip);
  }
}

function renderDetails(deviceId, item) {
  const config = CAMERA_CONFIG[deviceId];
  const payload = safeJsonParse(item?.payload);
  const active = isCameraActive(item, payload);

  emptyStateEl.classList.add("hidden");
  cameraDetailsEl.classList.remove("hidden");

  cameraNameEl.textContent = config?.label || deviceId;
  cameraTypeEl.textContent = `${deviceId} • ${typeToPersian(config?.type)}`;
  cameraTimestampEl.textContent = item?.timestamp || "—";
  cameraConnectionEl.textContent = getConnectionText(active);

  cameraStatusBadgeEl.textContent = active ? "فعال" : "غیرفعال";
  cameraStatusBadgeEl.classList.toggle("status-badge--active", active);
  cameraStatusBadgeEl.classList.toggle("status-badge--inactive", !active);

  renderCounts(payload?.counts || {});
  payloadViewerEl.textContent = JSON.stringify(payload || {}, null, 2);
}

function updateMarker(deviceId, item) {
  const marker = markers[deviceId];
  const config = CAMERA_CONFIG[deviceId];
  if (!marker || !config) return;

  const payload = safeJsonParse(item?.payload);
  const active = isCameraActive(item, payload);
  const timestamp = item?.timestamp || "—";

  marker.setIcon(createDivIcon(active));
  marker.bindPopup(buildPopupHtml(deviceId, config, active, timestamp));

  latestDataMap[deviceId] = item;
}

function createInitialMarkers() {
  Object.entries(CAMERA_CONFIG).forEach(([deviceId, config]) => {
    const marker = L.marker([config.lat, config.lng], {
      icon: createDivIcon(false),
    }).addTo(map);

    marker.bindPopup(buildPopupHtml(deviceId, config, false, "—"));

    marker.on("click", async () => {
      selectedDeviceId = deviceId;
      await fetchSingleDevice(deviceId, true);
    });

    markers[deviceId] = marker;
  });
}

async function fetchLatest() {
  try {
    const response = await fetch(`${API_BASE}/latest`);
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    const data = await response.json();
    if (!Array.isArray(data)) return;

    data.forEach((item) => {
      if (!item?.device_id || !CAMERA_CONFIG[item.device_id]) return;
      updateMarker(item.device_id, item);
    });

    if (selectedDeviceId && latestDataMap[selectedDeviceId]) {
      renderDetails(selectedDeviceId, latestDataMap[selectedDeviceId]);
    }
  } catch (error) {
    console.error("fetchLatest error:", error);
  }
}

async function fetchSingleDevice(deviceId, renderAfterFetch = false) {
  try {
    const response = await fetch(`${API_BASE}/device/${deviceId}`);
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    const item = await response.json();
    updateMarker(deviceId, item);

    if (renderAfterFetch) {
      renderDetails(deviceId, item);
    }
  } catch (error) {
    console.error(`fetchSingleDevice error for ${deviceId}:`, error);

    if (renderAfterFetch) {
      const fallback = latestDataMap[deviceId] || {
        device_id: deviceId,
        timestamp: null,
        payload: null,
      };
      renderDetails(deviceId, fallback);
    }
  }
}

refreshSelectedBtn.addEventListener("click", async () => {
  if (!selectedDeviceId) return;
  await fetchSingleDevice(selectedDeviceId, true);
});

createInitialMarkers();
fetchLatest();
setInterval(fetchLatest, 15000);
