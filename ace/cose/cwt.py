from ecdsa import SigningKey, VerifyingKey, NIST256p, NIST384p
from ace.cose import Signature1Message
from ace.cose.constants import Header, Key, Algorithm

from cbor2 import dumps, loads


def encode(claims: dict, key: SigningKey, kid: bytes):
    protected = { Header.ALG: Algorithm.ES256 }
    unprotected = { Header.KID: kid }

    msg = Signature1Message(payload=dumps(claims),
                            protected_header=dumps(protected),
                            unprotected_header=dumps(unprotected))

    return msg.serialize_signed(key)


def decode(encoded, key: VerifyingKey):
    return loads(Signature1Message.verify(encoded, key, external_aad=b''))
