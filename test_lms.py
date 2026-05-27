import httpx, asyncio, json

async def test():
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get('http://localhost:1234/v1/models')
        print(f'LM Studio status: {r.status_code}')
        data = r.json()
        models = data.get('data', [])
        for m in models:
            print(f'  Model: {m.get("id", m)}')
        if not models:
            print(f'  Full response: {json.dumps(data, indent=2)[:500]}')

asyncio.run(test())
