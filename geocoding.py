import time
import logging
import asyncio
import httpx

logger = logging.getLogger("geocoding")

# Simple in-memory cache
# Key: (rounded_lat, rounded_lon), Value: (address_string, expiry_timestamp)
_geocoding_cache = {}

# Nominatim has a strict rate limit of 1 request per second.
_last_request_time = 0.0
_nominatim_lock = asyncio.Lock()

async def reverse_geocode(lat: float, lon: float) -> str:
    """
    Reverse-geocodes latitude and longitude coordinates to a human-readable address.
    Uses the free Nominatim OpenStreetMap API with a strict rate limiter and 60s cache.
    """
    global _last_request_time
    
    if lat is None or lon is None:
        return "Unknown Location"

    # Round coordinates to 5 decimal places (approx. 1 meter accuracy) for caching
    cache_key = (round(lat, 5), round(lon, 5))
    now = time.time()
    
    # Check cache
    if cache_key in _geocoding_cache:
        addr, expiry = _geocoding_cache[cache_key]
        if now < expiry:
            logger.info(f"Geocoding Cache Hit for {cache_key} -> '{addr}'")
            return addr
            
    # Cache miss - call Nominatim with rate limiting
    async with _nominatim_lock:
        # Respect Nominatim 1 req/sec limit
        elapsed = time.time() - _last_request_time
        if elapsed < 1.0:
            delay = 1.0 - elapsed
            logger.debug(f"Nominatim rate limit safeguard: sleeping for {delay:.2f}s...")
            await asyncio.sleep(delay)
            
        _last_request_time = time.time()
        
        try:
            url = f"https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lon}&format=json"
            headers = {
                # Distinct User-Agent requested by Nominatim TOS
                "User-Agent": "AstraSOS-Emergency/1.0 (emergency@astrasos.app)"
            }
            
            logger.info(f"Calling Nominatim API for coordinates: ({lat}, {lon})")
            async with httpx.AsyncClient() as client:
                response = await client.get(url, headers=headers, timeout=2.0)
                
            if response.status_code == 200:
                res_data = response.json()
                address = res_data.get("address", {})
                
                # Prioritize: road + house_number + suburb + city/town/village
                road = address.get("road")
                house_num = address.get("house_number")
                suburb = address.get("suburb")
                city = address.get("city") or address.get("town") or address.get("village")
                
                parts = []
                if house_num:
                    parts.append(house_num)
                if road:
                    parts.append(road)
                if suburb:
                    parts.append(suburb)
                if city:
                    parts.append(city)
                    
                if not parts:
                    # Fallback to town/county + state
                    town = address.get("town") or address.get("county")
                    state = address.get("state")
                    if town:
                        parts.append(town)
                    if state:
                        parts.append(state)
                        
                addr_str = ", ".join(parts) if parts else f"{lat:.4f}, {lon:.4f}"
                
                # Cache result with a 60-second TTL
                _geocoding_cache[cache_key] = (addr_str, time.time() + 60.0)
                logger.info(f"Nominatim Geocoded: ({lat}, {lon}) -> '{addr_str}'")
                return addr_str
            else:
                logger.warning(f"Nominatim returned status {response.status_code}: {response.text}")
                
        except Exception as e:
            logger.error(f"Failed to reverse-geocode coordinates ({lat}, {lon}): {e}")
            
    # Fallback to raw coordinates on error/timeout
    return f"{lat:.4f}, {lon:.4f}"
