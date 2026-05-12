import asyncio
import json
import random
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Dict, List
import websockets


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
            counts=counts
        )


class TrafficSimulatorServer:
    def __init__(self, devices: List[TrafficDevice], interval_seconds: int = 300):
        self.devices = devices
        self.interval_seconds = interval_seconds
        self.clients = set()

    async def register_client(self, websocket):
        self.clients.add(websocket)
        print(f"✅ Client connected: {websocket.remote_address}")

    async def unregister_client(self, websocket):
        self.clients.discard(websocket)
        print(f"❌ Client disconnected: {websocket.remote_address}")

    async def broadcast(self, message: str):
        if not self.clients:
            return

        disconnected_clients = set()

        for client in self.clients:
            try:
                await client.send(message)
            except Exception:
                disconnected_clients.add(client)

        for client in disconnected_clients:
            self.clients.discard(client)

    async def simulate_device(self, device: TrafficDevice):
        while True:
            record = device.create_record(interval_minutes=self.interval_seconds // 60)
            message = record.to_json()

            print(f"[{device.device_id}] {message}")
            await self.broadcast(message)

            await asyncio.sleep(self.interval_seconds)

    async def ws_handler(self, websocket):
        await self.register_client(websocket)
        try:
            async for message in websocket:
                print(f"Message from client: {message}")
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            await self.unregister_client(websocket)

    async def run(self, host: str = "0.0.0.0", port: int = 8765):
        print(f"🚀 WebSocket server starting at ws://{host}:{port}")

        async with websockets.serve(self.ws_handler, host, port):
            tasks = [
                asyncio.create_task(self.simulate_device(device))
                for device in self.devices
            ]
            await asyncio.gather(*tasks)


def build_default_devices() -> List[TrafficDevice]:
    return [
        TrafficDevice("cam-01", "urban"),
        TrafficDevice("cam-02", "urban"),
        TrafficDevice("cam-03", "highway"),
        TrafficDevice("cam-04", "industrial"),
        TrafficDevice("cam-05", "highway"),
    ]


async def main():
    devices = build_default_devices()
    server = TrafficSimulatorServer(devices=devices, interval_seconds=300)
    await server.run(host="0.0.0.0", port=8765)


if __name__ == "__main__":
    asyncio.run(main())
