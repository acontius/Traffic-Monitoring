import asyncio
import websockets
import asyncpg
import json
from datetime import datetime, timezone, UTC # Import UTC

DB_DSN = "postgresql://acontius:1234@localhost:5432/traffic_monitoring"
WS_URL = "ws://localhost:8765"


async def save_to_db(pool, message):
    try:
        data = json.loads(message)
        device_id = data.get("device_id", "unknown")

        # --- START FIX ---
        timestamp_str = data.get("timestamp")
        if timestamp_str:
            # Parse the string to a datetime object.
            # Assumes the string is in ISO format like "2026-05-12T00:48:49"
            # If it includes timezone, use fromisoformat. Otherwise, assume UTC.
            try:
                # Try parsing with timezone info if present, otherwise assume UTC
                timestamp = datetime.fromisoformat(timestamp_str).replace(tzinfo=timezone.utc)
            except ValueError:
                # Fallback for strings without timezone info
                timestamp = datetime.strptime(timestamp_str, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)

        else:
            # If timestamp is missing from payload, use current UTC time
            timestamp = datetime.now(UTC) # Use timezone-aware object

        # --- END FIX ---

        async with pool.acquire() as con:
            await con.execute(
                """
                INSERT INTO traffic_data (device_id, timestamp, payload)
                VALUES ($1, $2, $3)
                """,
                device_id, timestamp, json.dumps(data) # Now 'timestamp' is a datetime object
            )

    except json.JSONDecodeError:
        print(f"Error: Could not decode JSON: {message}")
    except Exception as e:
        print(f"Error storing message: {e}")


async def client():
    try:
        pool = await asyncpg.create_pool(DB_DSN)
        print("Connected to DB.")
    except Exception as e:
        print(f"Error connecting to DB: {e}")
        return # Exit if DB connection fails

    while True: # Loop for reconnecting to WebSocket
        try:
            async with websockets.connect(WS_URL) as websocket:
                print("Connected to WebSocket.")
                while True:
                    try:
                        message = await websocket.recv()
                        print("Received:", message)
                        await save_to_db(pool, message)
                    except websockets.exceptions.ConnectionClosedOK:
                        print("WebSocket connection closed normally.")
                        break # Exit inner loop to reconnect
                    except websockets.exceptions.ConnectionClosedError as e:
                        print(f"WebSocket connection closed with error: {e}")
                        break # Exit inner loop to reconnect
                    except Exception as e:
                        print(f"Error receiving message: {e}")
                        # Decide if you want to break or continue
                        # For now, let's continue, but log it
        except ConnectionRefusedError:
            print(f"WebSocket connection refused. Retrying in 5 seconds...")
            await asyncio.sleep(5)
        except Exception as e:
            print(f"Error during WebSocket connection: {e}")
            await asyncio.sleep(5) # Wait before retrying


if __name__ == "__main__":
    asyncio.run(client())
