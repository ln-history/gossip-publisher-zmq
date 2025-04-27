#!/usr/bin/env python3
# -*- mode: python -*-

import sys
import os
import json
import socket


helloworld_out="/tmp/helloworld_out"
if os.path.isfile(helloworld_out):
    os.remove(helloworld_out)
def printout(s):
    with open(helloworld_out, "a") as output:
        output.write(s)

# getmanifest

request = sys.stdin.readline()
sys.stdin.readline() # "\n"
# printout(request)

req_id = json.loads(request)["id"]

manifest = {
    "jsonrpc": "2.0",
    "id": req_id,
    "result": {
        "dynamic": True,
        "options": [{
            "name": "foo_opt",
            "type": "string",
            "default": "bar",
            "description": "description"
        }],
        "rpcmethods": [{
            "name": "helloworld",
            "usage": "",
            "description": "description"
        }]
    }
}

sys.stdout.write(json.dumps(manifest))
sys.stdout.flush()

# init 
request = sys.stdin.readline()
sys.stdin.readline() # "\n"
# printout(request)

jsreq = json.loads(request)
req_id = jsreq["id"]

init = {
    "jsonrpc": "2.0",
    "id": req_id,
    "result": {}
}

sys.stdout.write(json.dumps(init))
sys.stdout.flush()

foo_opt = jsreq["params"]["options"]["foo_opt"]
lightning_dir = jsreq["params"]["configuration"]["lightning-dir"]
rpc_file = jsreq["params"]["configuration"]["rpc-file"]
socket_file = os.path.join(lightning_dir,rpc_file)

# io loop

for request in sys.stdin:
    sys.stdin.readline() # "\n"
    printout(request)
    jsreq = json.loads(request)
    req_id = jsreq["id"]
    cli_params = jsreq["params"]

    getinfo = {
        "jsonrpc": "2.0",
        "id": "1",
        "method": "getinfo",
        "params": [],
        "filter": {"id": True}
    }

    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.connect(socket_file)
        s.sendall(bytes(json.dumps(getinfo), encoding="utf-8"))
        getinfo_resp = s.recv(4096)

    node_id = json.loads(getinfo_resp)["result"]["id"] 

    result = {
	"node_id": node_id,
        "option": {
            "foo_opt": foo_opt
        },
        "cli_params": cli_params
    }

    resp = {
        "jsonrpc": "2.0",
        "id": req_id,
        "result": result
    }

    sys.stdout.write(json.dumps(resp))
    sys.stdout.flush()

