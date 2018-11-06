import random

from lib.ace.rs import HTTPResourceServer

from aiohttp import web
from aiohttp.abc import AbstractRouter
from cbor2 import dumps, loads
from ecdsa import VerifyingKey, SigningKey


class TemperatureServer(HTTPResourceServer):

    def __init__(self,
                 audience: str,
                 identity: SigningKey,
                 as_url: str,
                 as_public_key: VerifyingKey,
                 router: AbstractRouter,
                 client_id=None,
                 client_secret=None):
        super().__init__(audience, identity, as_url, as_public_key, router, client_id, client_secret)
        router.add_get('/temperature', self.wrap(scope="read_temperature", handler=self.get_temperature))
        router.add_post('/led', self.wrap(scope="post_led", handler=self.post_led))

    async def post_led(self, request, payload, token, oscore_context):
        data = loads(oscore_context.decrypt(payload))

        print(f"Setting LED value to: {data[b'led_value']}")

        response = oscore_context.encrypt(dumps(b'OK'))
        return web.Response(status=201, body=response)

    # GET /temperature
    async def get_temperature(self, request, payload, token, oscore_context):
        temperature = random.randint(22, 26)
        response = oscore_context.encrypt(dumps({'temperature': f"{temperature}C"}))

        return web.Response(status=200, body=response)
