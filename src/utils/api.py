# Default
import asyncio
import httpx

# User-Agent
_HEADERS = {
    "User-Agent": "lodNer/1.0 (https://github.com/logo94/lodner; logo94@example.com)"
}

# Module-level rate limit: one call every 0.4s (150/min, under the 200/min anonymous cap).
_RATE_PER_MIN = 150
_MIN_INTERVAL = 60.0 / _RATE_PER_MIN
_throttle_lock = asyncio.Lock()
_next_slot = 0.0


async def _throttle():

    global _next_slot
    async with _throttle_lock:
        now = asyncio.get_event_loop().time()
        delay = max(0.0, _next_slot - now)
        _next_slot = max(now, _next_slot) + _MIN_INTERVAL
    if delay > 0:
        await asyncio.sleep(delay)


async def wikidata_api_call(params, max_retries: int = 4):

    url = "https://www.wikidata.org/w/api.php"

    for attempt in range(max_retries):
        await _throttle()
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.get(url=url, params=params, headers=_HEADERS)

            if response.status_code == 429:
                # Retry-After
                wait = float(response.headers.get("Retry-After", 2 ** attempt))
                print(f"[Wikidata 429] rate limited, waiting {wait}s (attempt {attempt + 1})")
                await asyncio.sleep(wait)
                continue

            response.raise_for_status()
            return response.json()

        except httpx.HTTPStatusError as e:
            print(f"HTTP error: {e.response.status_code} - {e.response.text}")
            return None
        except httpx.RequestError as e:
            print(f"Request error: {e}")

            if attempt < max_retries - 1:
                await asyncio.sleep(2 ** attempt)
                continue
            return None

    print("[Wikidata] too many retries after repeated 429s")
    return None