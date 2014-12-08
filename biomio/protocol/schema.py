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
                {"$ref": "#/definitions/rpcReq"},
                {"$ref": "#/definitions/rpcResp"},
                {"$ref": "#/definitions/rpcEnumNsReq"},
                {"$ref": "#/definitions/rpcEnumNsResp"},
                {"$ref": "#/definitions/rpcEnumCallsReq"},
                {"$ref": "#/definitions/rpcEnumCallsResp"},
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
            "required": ["oid"],
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
        "rpcData": {
            "type": "object",
            "required": ["keys", "values"],
            "properties": {
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
        "rpcEnumNsReq": {
            "type": "object",
            "required": ["oid"],
            "properties": {
                "oid": { "enum": ["rpcEnumNsReq"] }
            }
        },
        "rpcEnumNsResp": {
            "type": "object",
            "required": ["oid", "namespaces"],
            "properties": {
                "oid": { "enum": ["rpcEnumNsResp"] },
                "namespaces": {
                    "type": "array",
                    "items": {"type": "string"}
                }
            }
        },
        "rpcEnumCallsReq": {
            "type": "object",
            "required": ["oid", "ns"],
            "properties": {
                "oid": { "enum": ["rpcEnumNsReq"] },
                "ns": {"type": "string"}
            }
        },
        "rpcEnumCallsResp": {
            "type": "object",
            "required": ["oid", "calls"],
            "properties": {
                "oid": { "enum": ["rpcEnumCallsResp"] },
                "calls": {
                    "type": "array",
                    "items": {"type": "string"}
                },
                "params": {
                    "type": "array",
                    "items": {"type": "string"}
                    # fixed to make fysom works
                    # {
                    #     "type": "array",
                    #     "items": {"type": "string"}
                    # }
                }
            }
        },
        "rpcReq": {
            "type": "object",
            "required": ["oid", "namespace", "call"],
            "properties": {
                "oid": { "enum": ["rpcReq"] },
                "namespace": {"type": "string"},
                "call": {"type": "string"},
                "data": {"$ref": "#/definitions/rpcData"}
            }
        },
        "rpcResp": {
            "type": "object",
            "required": ["oid", "namespace", "call", "data"],
            "properties": {
                "oid": { "enum": ["rpcResp"] },
                "namespace": {"type": "string"},
                "call": {"type": "string"},
                "data": {"$ref": "#/definitions/rpcData"}
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
