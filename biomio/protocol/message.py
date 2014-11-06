
import json
import python_jsonschema_objects as pjs

import logging
logger = logging.getLogger(__name__)

BIOMIO_protocol_json_schema = {
    "title": "Biomio Schema",
    "id": "http://biom.io/entry-schema#",
    "$schema": "http://json-schema.org/draft-04/schema#",
    "description": "schema of BIOMIO communication protocol",
    "type": "object",
    "required": ["header", "msg"],
    "properties": {
        "header": {
            "oneOf": [
                {"$ref": "#/definitions/serverHeader"},
                {"$ref": "#/definitions/clientHeader"}
            ]
        },
        "msg": {
            "oneOf": [
                {"$ref": "#/definitions/bye"},
                {"$ref": "#/definitions/ack"},
                {"$ref": "#/definitions/nop"},
                {"$ref": "#/definitions/clientHello"},
                {"$ref": "#/definitions/resources"},
                {"$ref": "#/definitions/again"},
                {"$ref": "#/definitions/auth"},
                {"$ref": "#/definitions/probe"},
                {"$ref": "#/definitions/verify"},
                {"$ref": "#/definitions/identify"},
                {"$ref": "#/definitions/getData"},
                {"$ref": "#/definitions/setData"},
                {"$ref": "#/definitions/serverHello"},
                {"$ref": "#/definitions/try"},
                {"$ref": "#/definitions/data"}
            ]
        },
        "status": { "type": "string" }
    },
    "definitions": {
        "nop": {
            "type": "object",
            "required": ["oid"],
            "properties": {
                "oid": { "enum": ["nop"] }
            }
        },
        "ack": {
            "type": "object",
            "required": ["oid"],
            "properties": {
                "oid": { "enum": ["ack"] }
            }
        },
        "bye": {
            "type": "object",
            "required": ["oid"],
            "properties": {
                "oid": { "enum": ["bye"] }
            }
        },
        "resource": {
            "type": "object",
            "required": ["rType", "rProperties"],
            "properties": {
                "rType": {"enum": ["video", "fp-scanner", "mic"]},
                "rProperties": {"type": "string"}
            }
        },
        "serverHeader": {
            "type": "object",
            "name": "serverHeader",
            "required": ["oid","seq", "protoVer", "token"],
            "properties": {
                "oid": { "enum": ["serverHeader"] },
                "seq": {"type": "number"},
                "protoVer": {"type": "string"},
                "token": {"type": "string"}
            }
        },
        "serverHello": {
            "type": "object",
            "required": ["oid", "refreshToken", "ttl"],
            "properties": {
                "oid": { "enum": ["serverHello"] },
                "refreshToken": {"type": "string"},
                "ttl": {"type": "number"},
                "key": {"type": "string"}
            }
        },
        "try": {
            "type": "object",
            "required": ["oid", "resource"],
            "properties": {
            "oid": { "enum": ["try"] },
                "resource": {"$ref": "#/definitions/resource"},
                "samples": {"type": "number"}
            }
        },
        "data": {
            "type": "object",
            "required": ["keys", "values"],
            "properties": {
            "oid": { "enum": ["data"] },
                "keys": {
                    "type": "array",
                    "items": {"type": "string"}
                },
                "values": {
                    "type": "array",
                    "items": {"type": "string"}
                }
            }
        },
        "clientHeader": {
            "type": "object",
            "required": ["oid", "seq", "id", "protoVer", "osId", "appId"],
            "properties": {
                "oid": { "enum": ["clientHeader"] },
                "seq": {"type": "number"},
                "protoVer": {"type": "string"},
                "id": {"type": "string"},
                "appId": {"type": "string"},
                "osId": {"type": "string"},
                "devId": {"type": "string"},
                "token": {"type": "string"}
            }
        },
        "clientHello": {
            "type": "object",
            "required": ["oid", "secret"],
            "properties": {
                "oid": { "enum": ["clientHello"] },
                "secret": {"type": "string"}
            }
        },
        "auth": {
            "type": "object",
            "required": ["oid", "key"],
            "properties": {
            "oid": { "enum": ["auth"] },
            "key": { "type": "string" }
        }
        },
        "again": {
            "type": "object",
            "required": ["oid"],
            "properties": {
                "oid": { "enum": ["again"] }
            }
        },
        "resources": {
            "type": "object",
        "required": ["oid", "data"],
            "properties": {
                "oid": { "enum": ["resources"] },
                "data": {
                        "type": "array",
                        "items": {"$ref": "#/definitions/resource"}
                }
            }
        },
        "image": {
            "media": {
                "type": "image/png",
                "binaryEncoding": "base64"
            },
            "type": "string"
        },
        "sound": {
            "media": {
                "type": "sound/waw",
                "binaryEncoding": "base64"
            },
            "type": "string"
        },
        "probe": {
            "type": "object",
            "required": ["oid", "probeId", "samples"],
            "properties": {
            "oid": { "enum": ["probe"] },
                "probeId": {"type": "number"},
                "samples": {
                    "oneOf": [
                        {
                            "type": "array",
                            "items": {"$ref": "#/definitions/image"}
                        },
                        {
                            "type": "array",
                            "items": {"$ref": "#/definitions/sound"}
                        }
                    ]
                }
            }
        },
        "verify": {
            "type": "object",
            "required": ["oid", "id"],
            "properties": {
                "oid": { "enum": ["verify"] },
                "id": {"type": "string"}
            }
        },
        "identify": {
            "type": "object",
            "required": ["oid"],
            "properties": {
            "oid": { "enum": ["identify"] }
            }
        },
        "getData": {
            "type": "object",
            "required": ["oid", "keys"],
            "properties": {
            "oid": { "enum": ["getData"] },
                "keys": {
                    "type": "array",
                    "items": {"type": "string"}
                },
                "onBehalfOf": {"type": "string"}
            }
        },
        "setData": {
            "type": "object",
            "required": ["oid", "keys", "values"],
            "properties": {
            "oid": { "enum": ["setData"] },
                "keys": {
                    "type": "array",
                    "items": {"type": "string"}
                },
                "values": {
                    "type": "array",
                    "items": {"type": "string"}
                }
            }
        },
        "rect": {
            "type": "object",
            "required": ["x", "y", "width", "height"],
            "properties": {
                "x": {"type": "number"},
                "y": {"type": "number"},
                "height": {"type": "number"},
                "width": {"type": "number"}
            }
        },
        "detected": {
            "type": "object",
            "required": ["oid", "rects"],
            "properties": {
            "oid": { "enum": ["detected"] },
                "distance": {"type": "number"},
                "rects": {
                    "type": "array",
                    "items": {"$ref": "#/definitions/rect"}
                },
                "labels": {
                    "type": "array",
                    "items": {"type": "string"}
                }
            }
        }
    }
}

class BiomioMessageBuilder:
    _ns = None

    def __init__(self, **kwargs):
        self._header = {}
        self.set_header(**kwargs)

    def set_header(self, **kwargs):
        for k, v in kwargs.iteritems():
            self._header[k] = v

    def get_header_field_value(self, field_str):
        return self._header.get(field_str, None)

    @classmethod
    def _get_ns(cls):
        if not cls._ns:
            # Suppress logging inside of python_jsonschema_objects module
            logger = logging.getLogger("python_jsonschema_objects.classbuilder")
            logger.disabled = True

            builder = pjs.ObjectBuilder(BIOMIO_protocol_json_schema)
            cls._ns = builder.build_classes()
        return cls._ns

    @staticmethod
    def create_message_from_json(json_string):
        obj = json.loads(json_string)
        ns = BiomioMessageBuilder._get_ns()
        biomio_message = ns.BiomioSchema(**obj)
        return biomio_message

    def create_message(self, status=None, **kwargs):
        msg = {}

        for k, v in kwargs.iteritems():
            msg[k] = v

        obj = {
            'header': self._header,
            'msg': msg
        }

        if status:
            obj['status'] = status

        ns = self._get_ns()
        biomio_message = ns.BiomioSchema(**obj)

        return biomio_message