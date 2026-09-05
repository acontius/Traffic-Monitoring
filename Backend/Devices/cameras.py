"""Traffic-count device simulator.

Generates realistic per-interval vehicle counts and connects to the TCMS
hub's WebSocket ingestion gateway (`Backend/app/ws/ingest.py`) as a client —
this is the actual SRS 2.1 shape: devices push data *into* the hub, rather
than the hub pulling from a server the devices expose.
"""

import asyncio
import json
import os
import random
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import websockets

# Controllable anomaly scenarios (spec: simulator upgrade for ML testing).
# TCMS_SIMULATOR_ANOMALY_MODE applies to every device unless overridden per
# device via TCMS_SIMULATOR_DEVICE_SCENARIOS (a JSON map device_id -> mode).
# Mode "none" (the default) leaves TrafficPattern.generate_counts's output
# byte-for-byte unchanged.
SCENARIO_NONE = "none"
SCENARIO_MISSING_DATA = "missing_data"
SCENARIO_ZERO_DATA = "zero_data"
SCENARIO_SPIKE = "spike"
SCENARIO_DROP = "drop"
SCENARIO_CONSTANT_VALUE = "constant_value"
SCENARIO_CATEGORY_CORRUPTION = "category_corruption"
SCENARIO_TIMESTAMP_DRIFT = "timestamp_drift"
SCENARIO_BURST = "burst"
SCENARIO_HOLIDAY_PATTERN = "holiday_pattern"
SCENARIO_EVENT_PATTERN = "event_pattern"
SCENARIO_GRADUAL_DRIFT = "gradual_drift"


class ScenarioController:
    """Wraps one device's send loop to optionally corrupt/suppress/skew its
    readings, so the ML layer (device health, anomaly detection,
    reconstruction) can actually be exercised end to end. Kept out of
    `TrafficPattern` itself so the "normal" generator stays untouched."""

    def __init__(self, mode: str):
        self.mode = mode
        self._tick = 0
        self._constant_counts: Optional[Dict[str, int]] = None
        self._burst_buffer: List["TrafficRecord"] = []

    def apply(self, record: "TrafficRecord") -> Optional[List["TrafficRecord"]]:
        """Returns a list of records to actually send for this tick (may be
        empty to suppress sending, or contain more than one to simulate a
        burst), or `None` to send `record` unchanged."""
        self._tick += 1

        if self.mode == SCENARIO_NONE:
            return None

        if self.mode == SCENARIO_MISSING_DATA:
            return [] if self._tick % 3 == 0 else None

        if self.mode == SCENARIO_ZERO_DATA:
            record.counts = {k: 0 for k in record.counts}
            return [record]

        if self.mode == SCENARIO_SPIKE:
            record.counts = {k: v * 8 + 50 for k, v in record.counts.items()}
            return [record]

        if self.mode == SCENARIO_DROP:
            record.counts = {k: max(0, v // 10) for k, v in record.counts.items()}
            return [record]

        if self.mode == SCENARIO_CONSTANT_VALUE:
            if self._constant_counts is None:
                self._constant_counts = dict(record.counts)
            record.counts = dict(self._constant_counts)
            return [record]

        if self.mode == SCENARIO_CATEGORY_CORRUPTION:
            # One category (motorcycles) silently freezes at zero while
            # others behave normally — spec's PARTIAL_FAILURE example.
            record.counts["موتور"] = 0
            return [record]

        if self.mode == SCENARIO_TIMESTAMP_DRIFT:
            drifted = datetime.fromisoformat(record.timestamp) + timedelta(
                minutes=5 * self._tick
            )
            record.timestamp = drifted.isoformat(timespec="seconds")
            return [record]

        if self.mode == SCENARIO_BURST:
            self._burst_buffer.append(record)
            if len(self._burst_buffer) < 4:
                return []
            flush = self._burst_buffer
            self._burst_buffer = []
            return flush

        if self.mode == SCENARIO_GRADUAL_DRIFT:
            factor = 1.0 + min(3.0, self._tick * 0.05)
            record.counts = {k: round(v * factor) for k, v in record.counts.items()}
            return [record]

        if self.mode in (SCENARIO_HOLIDAY_PATTERN, SCENARIO_EVENT_PATTERN):
            # A large but *legitimate* shift, meant to exercise the calendar
            # context rather than look like a device failure.
            record.counts = {k: round(v * 2.5) for k, v in record.counts.items()}
            return [record]

        return None


def load_device_scenarios() -> Dict[str, str]:
    raw = os.environ.get("TCMS_SIMULATOR_DEVICE_SCENARIOS", "{}")
    try:
        parsed = json.loads(raw)
        return (
            {str(k): str(v) for k, v in parsed.items()}
            if isinstance(parsed, dict)
            else {}
        )
    except json.JSONDecodeError:
        return {}


@dataclass
class TrafficRecord:
    device_id: str
    location_type: str
    timestamp: str
    interval_minutes: int
    counts: Dict[str, int]

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)


class TrafficPattern:
    """
    الگوی تولید ترافیک بر اساس:
    - نوع محل نصب دستگاه
    - ساعت شبانه‌روز
    - رفتار متفاوت انواع وسیله نقلیه
    """

    VEHICLES = ["سواری", "کامیون", "موتور", "اتوبوس", "وانت"]

    def __init__(self, location_type: str):
        self.location_type = location_type
        self.base_profile = self._build_base_profile(location_type)

    def _build_base_profile(self, location_type: str) -> Dict[str, int]:
        """
        پایه‌ی تردد برای هر ۵ دقیقه در شرایط نرمال روز
        """
        profiles = {
            "urban": {
                "سواری": 18,
                "کامیون": 3,
                "موتور": 10,
                "اتوبوس": 2,
                "وانت": 5,
            },
            "highway": {
                "سواری": 22,
                "کامیون": 8,
                "موتور": 4,
                "اتوبوس": 3,
                "وانت": 6,
            },
            "industrial": {
                "سواری": 12,
                "کامیون": 10,
                "موتور": 3,
                "اتوبوس": 1,
                "وانت": 7,
            },
        }
        return profiles.get(location_type, profiles["urban"])

    def _time_factor(self, hour: int) -> Dict[str, float]:
        """
        ضرایب وابسته به ساعت.
        می‌خواهیم رفتار طبیعی‌تر شود:
        - صبح و عصر اوج
        - شب کم‌تردد
        - نیمه‌شب خیلی کم
        - موتور در شب کمتر
        """
        # پیش‌فرض
        factors = {
            "سواری": 1.0,
            "کامیون": 1.0,
            "موتور": 1.0,
            "اتوبوس": 1.0,
            "وانت": 1.0,
        }

        # نیمه‌شب تا 5 صبح
        if 0 <= hour < 5:
            factors["سواری"] = 0.20
            factors["کامیون"] = 0.45
            factors["موتور"] = 0.10
            factors["اتوبوس"] = 0.15
            factors["وانت"] = 0.25

        # 5 تا 7 صبح
        elif 5 <= hour < 7:
            factors["سواری"] = 0.60
            factors["کامیون"] = 0.70
            factors["موتور"] = 0.35
            factors["اتوبوس"] = 0.50
            factors["وانت"] = 0.60

        # اوج صبح
        elif 7 <= hour < 10:
            factors["سواری"] = 1.80
            factors["کامیون"] = 0.85
            factors["موتور"] = 1.50
            factors["اتوبوس"] = 1.60
            factors["وانت"] = 1.20

        # میانه روز
        elif 10 <= hour < 16:
            factors["سواری"] = 1.20
            factors["کامیون"] = 1.10
            factors["موتور"] = 1.00
            factors["اتوبوس"] = 1.00
            factors["وانت"] = 1.15

        # اوج عصر
        elif 16 <= hour < 20:
            factors["سواری"] = 1.90
            factors["کامیون"] = 0.90
            factors["موتور"] = 1.40
            factors["اتوبوس"] = 1.30
            factors["وانت"] = 1.10

        # اوایل شب
        elif 20 <= hour < 23:
            factors["سواری"] = 0.90
            factors["کامیون"] = 0.80
            factors["موتور"] = 0.50
            factors["اتوبوس"] = 0.60
            factors["وانت"] = 0.75

        # 23 تا 24
        elif 23 <= hour <= 24:
            factors["سواری"] = 0.40
            factors["کامیون"] = 0.60
            factors["موتور"] = 0.20
            factors["اتوبوس"] = 0.20
            factors["وانت"] = 0.35

        return factors

    def _location_adjustment(self) -> Dict[str, float]:
        """
        اصلاح ضرایب بر اساس نوع محل
        """
        if self.location_type == "urban":
            return {
                "سواری": 1.25,
                "کامیون": 0.65,
                "موتور": 1.35,
                "اتوبوس": 1.10,
                "وانت": 1.00,
            }

        if self.location_type == "highway":
            return {
                "سواری": 1.10,
                "کامیون": 1.60,
                "موتور": 0.60,
                "اتوبوس": 1.00,
                "وانت": 1.15,
            }

        if self.location_type == "industrial":
            return {
                "سواری": 0.80,
                "کامیون": 1.90,
                "موتور": 0.50,
                "اتوبوس": 0.60,
                "وانت": 1.40,
            }

        return {
            "سواری": 1.0,
            "کامیون": 1.0,
            "موتور": 1.0,
            "اتوبوس": 1.0,
            "وانت": 1.0,
        }

    def _random_noise(self, base_value: float) -> int:
        """
        نوسان طبیعی اطراف مقدار اصلی
        """
        std_dev = max(1.0, base_value * 0.15)
        value = random.gauss(base_value, std_dev)
        return max(0, round(value))

    def generate_counts(self, now: datetime) -> Dict[str, int]:
        hour = now.hour
        time_factors = self._time_factor(hour)
        location_factors = self._location_adjustment()

        counts = {}

        for vehicle in self.VEHICLES:
            base = self.base_profile[vehicle]
            value = base * time_factors[vehicle] * location_factors[vehicle]

            # کمی رفتار منطقی اضافه
            # سواری معمولاً از کامیون بیشتر باشد
            # موتور شب‌ها خیلی کمتر شود
            # کامیون در بزرگراه/صنعتی بیشتر دیده شود
            count = self._random_noise(value)
            counts[vehicle] = count

        # تضمین چند قاعده منطقی مهم
        if counts["سواری"] < counts["کامیون"]:
            diff = counts["کامیون"] - counts["سواری"]
            counts["سواری"] += diff + random.randint(1, 4)

        # در ساعات شب موتور خیلی کم باشد
        if 0 <= hour < 6 or 21 <= hour <= 23:
            counts["موتور"] = min(counts["موتور"], random.randint(0, 3))

        return counts


class TrafficDevice:
    def __init__(self, device_id: str, location_type: str):
        self.device_id = device_id
        self.location_type = location_type
        self.pattern = TrafficPattern(location_type)

    def create_record(self, interval_minutes: int = 5) -> TrafficRecord:
        now = datetime.now()
        counts = self.pattern.generate_counts(now)

        return TrafficRecord(
            device_id=self.device_id,
            location_type=self.location_type,
            timestamp=now.isoformat(timespec="seconds"),
            interval_minutes=interval_minutes,
            counts=counts,
        )


async def run_device(
    device: TrafficDevice,
    hub_ws_url: str,
    token: str,
    interval_seconds: int,
    scenario_mode: str = SCENARIO_NONE,
) -> None:
    """Connects this device to the hub's ingestion gateway and pushes a new
    reading every `interval_seconds`, reconnecting on failure. `scenario_mode`
    (spec: simulator anomaly scenarios) optionally corrupts/suppresses/skews
    what's actually sent so device-health/anomaly/reconstruction can be
    exercised end to end; `"none"` (default) is unchanged behaviour."""
    url = f"{hub_ws_url}?device_id={device.device_id}&token={token}"
    controller = ScenarioController(scenario_mode)
    while True:
        try:
            async with websockets.connect(url) as websocket:
                print(
                    f"✅ [{device.device_id}] connected to hub "
                    f"(scenario={scenario_mode})"
                )
                while True:
                    record = device.create_record(
                        interval_minutes=max(1, interval_seconds // 60)
                    )
                    to_send = controller.apply(record)
                    records = [record] if to_send is None else to_send
                    for r in records:
                        message = r.to_json()
                        await websocket.send(message)
                        print(f"[{device.device_id}] sent {message}")
                    await asyncio.sleep(interval_seconds)
        except (websockets.exceptions.ConnectionClosed, OSError) as exc:
            print(f"❌ [{device.device_id}] connection lost ({exc}); retrying in 5s")
            await asyncio.sleep(5)


def build_default_devices() -> List[TrafficDevice]:
    return [
        TrafficDevice("cam-01", "urban"),
        TrafficDevice("cam-02", "urban"),
        TrafficDevice("cam-03", "highway"),
        TrafficDevice("cam-04", "industrial"),
        TrafficDevice("cam-05", "highway"),
    ]


async def main() -> None:
    hub_ws_url = os.environ.get("TCMS_HUB_WS_URL", "ws://localhost:8000/ws/ingest")
    token = os.environ.get("TCMS_DEVICE_TOKEN", "change-me-device-token")
    interval_seconds = int(os.environ.get("TCMS_SIMULATOR_INTERVAL_SECONDS", "300"))
    default_mode = os.environ.get("TCMS_SIMULATOR_ANOMALY_MODE", SCENARIO_NONE)
    device_scenarios = load_device_scenarios()

    devices = build_default_devices()
    await asyncio.gather(
        *(
            run_device(
                device,
                hub_ws_url,
                token,
                interval_seconds,
                scenario_mode=device_scenarios.get(device.device_id, default_mode),
            )
            for device in devices
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
