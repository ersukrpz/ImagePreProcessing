from fastapi import Request
from redis.asyncio import Redis
from config import Config

class RedisService:
    def __init__(self):
        self._cli: Redis | None = None

    async def cli(self) -> Redis:
        if self._cli is None:
            self._cli = Redis(host=Config.REDIS_HOST, port=Config.REDIS_PORT, decode_responses=True)
        return self._cli

    async def sse_stream(self, request: Request):
        cli = await self.cli()
        ps = cli.pubsub()
        await ps.subscribe(Config.CHANNEL)
        try:
            while True:
                if await request.is_disconnected():
                    break
                msg = await ps.get_message(ignore_subscribe_messages=True, timeout=1)
                if not msg:
                    continue
                yield f"data: {msg['data']}\n\n"
        finally:
            await ps.unsubscribe(Config.CHANNEL)
            await ps.close()
            await cli.close()
