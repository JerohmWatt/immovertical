import asyncio
import httpx
import base64
import json
from datetime import datetime, timedelta

async def test_c21_pagesize():
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Origin": "https://www.century21.be",
        "Referer": "https://www.century21.be/"
    }
    
    yesterday = datetime.now() - timedelta(days=30)
    iso_date = yesterday.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    
    c21_filter = {
        "bool": {
            "filter": {
                "bool": {
                    "must": [
                        {"match": {"address.countryCode": "be"}},
                        {"match": {"listingType": "FOR_SALE"}},
                        {"range": {"creationDate": {"gte": iso_date}}}
                    ]
                }
            }
        }
    }
    filter_b64 = base64.b64encode(json.dumps(c21_filter, separators=(',', ':')).encode()).decode()
    
    base_api = "https://api.prd.cloud.century21.be/api/v2/properties"
    
    for ps in [24, 25, 30, 50]:
        params = {
            "filter": filter_b64,
            "pageSize": str(ps),
            "sort": "-creationDate"
        }
        query_string = "&".join([f"{k}={v}" for k, v in params.items()])
        url = f"{base_api}?{query_string}"
        
        async with httpx.AsyncClient(headers=headers, follow_redirects=True, timeout=30.0) as client:
            response = await client.get(url)
            if response.status_code == 200:
                data = response.json()
                items = data.get("data", [])
                print(f"Requested pageSize {ps} -> Got {len(items)} items")
            else:
                print(f"Error for pageSize {ps}: {response.status_code}")

if __name__ == "__main__":
    asyncio.run(test_c21_pagesize())
