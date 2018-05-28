import time
import os

from aiohttp import web
from aiohttp.abc import AbstractRouter
from cbor2 import dumps, loads
from ecdsa import VerifyingKey, SigningKey, NIST256p

from lib.cbor.constants import Keys as CK
from lib.cose.constants import Key as Cose
from lib.cose import CoseKey
from .client_registry import ClientRegistry
from .key_registry import KeyRegistry
from .token_registry import TokenRegistry
from lib.access_token import AccessToken
from lib.edhoc.util import vk_from_point

RS_PUBLIC_KEY = VerifyingKey.from_der(bytes.fromhex("3059301306072a8648ce3d020106082a8648ce3d030107034200046cc415"
                                                    "12d92fb03cb3b35bed5b494643a8a8a55503e87a90282c78d6c58a7e3c88"
                                                    "a21c0287e7e8d76b0052b1f1a2dcebfea57714c1210d42f17b335adcb76d"
                                                    "7a"))


class AuthorizationServer():

    def __init__(self, signature_key: SigningKey, router: AbstractRouter):
        self.signature_key = signature_key
        self.client_registry = ClientRegistry()
        self.client_registry.register_client(client_id="ace_client_1",
                                             client_secret=b"ace_client_1_secret_123456")
        self.key_registry = KeyRegistry()
        self.token_registry = TokenRegistry()

        router.add_get('/clients', self.clients)
        router.add_post('/token', self.token)
        router.add_post('/introspect', self.introspect)

    def verify_client(self, client_id, client_secret):
        return self.client_registry.check_secret(client_id, client_secret)

    async def clients(self, request):
        """
        Returns a list of all approved client IDs.
        DEBUG ONLY!
        """
        response = {
            'approved_clients': [c.client_id for c in self.client_registry.registered_clients]
        }

        return web.json_response(response)

    # POST
    async def token(self, request):
        """
        Validates the incoming requests and grants an access token if valid. Must be POST [ACE 5.6.1]
        Returns error codes as stated in [ACE 5.6.3]
        """

        params = loads(await request.content.read())

        # Verify basic request
        if not self._verify_token_request(params):
            return web.Response(status=400, body=dumps({'error': 'invalid_request'}))

        client_id = params[CK.CLIENT_ID]
        client_secret = params[CK.CLIENT_SECRET]

        # Check if client is registered
        if not self.verify_client(client_id, client_secret):
            return web.Response(status=400, body=dumps({'error': 'unauthorized_client'}))

        # Extract Clients Public PoP key
        client_pop_key = CoseKey.from_cose(params[CK.CNF][Cose.COSE_KEY])

        # Extract client claims scope and audience
        client_claims = {k: params[k] for k in (CK.SCOPE, CK.AUD)}

        # Create access token, bind PoP key
        token = self._bind_token(client_claims, client_pop_key)

        # Register bound PoP key for later reference
        self.key_registry.add_key(client_id, client_pop_key)
        self.token_registry.add_token(token, self_contained=True)

        token_sent = token.sign_and_export_self_contained(self.signature_key)
        # token_sent = token.export_referential()

        response = {
            CK.ACCESS_TOKEN: token_sent,
            CK.TOKEN_TYPE: 'pop',
            CK.PROFILE: 'coap_oscore',
            CK.RS_CNF: CoseKey(RS_PUBLIC_KEY, b'rs_pub_key', CoseKey.Type.ECDSA).encode()
        }

        return web.Response(status=200, body=dumps(response))

    def _bind_token(self, client_claims: dict, session_key: VerifyingKey) -> AccessToken:
        """
        Bind session_key to access_token
        :param client_claims: client claims to be included in the access token
        :param session_key: PoP key to be bound to the access token
        :return:
        """
        cti = os.urandom(2)

        # Claims to be included in the access token
        claims = {
            CK.ISS: 'ace.as-server.com',
            CK.IAT: int(time.time()),
            CK.EXP: int(time.time() + 7200.0),
            CK.CTI: cti.hex()  # TODO: use 'bytes' instead of string as per spec
        }

        # Add client claims (aud and scope)
        claims.update(client_claims)

        # Create Token and bind PoP key
        token = AccessToken(claims=claims)
        token.bind_key(session_key)

        return token

    def _verify_token_request(self, request_data: dict) -> bool:
        """
        Verify that the incoming request data conform to the standard
        :param request_data: incoming data as CBOR Map
        :return: True if request payload is valid, False otherwise
        """
        expected_keys = [CK.GRANT_TYPE,
                         CK.CLIENT_ID,
                         CK.CLIENT_SECRET,
                         CK.AUD]

        if request_data is None:
            return False

        return all(key in request_data for key in expected_keys)

    # POST
    async def introspect(self, request):
        params = loads(await request.content.read())

        # Check if token was supplied
        if CK.TOKEN not in params:
            return web.Response(status=400, body=dumps({'error': 'missing "token" parameter'}))

        token = params[CK.TOKEN]  # required
        token_type_hint = params[CK.TOKEN_TYPE_HINT]  # optional

        access_context = self.token_registry.get_token(reference=token)

        response = {
            CK.ACTIVE: True,
            CK.SCOPE: access_context.scope,
            CK.AUD:   access_context.audience,
            CK.ISS:   access_context.issuer,
            CK.EXP:   access_context.expires,
            CK.IAT:   access_context.issued_at,
            CK.CNF: {
                Cose.COSE_KEY: access_context.bound_key.encode()
            }
        }

        return web.Response(status=201, body=dumps(response))
