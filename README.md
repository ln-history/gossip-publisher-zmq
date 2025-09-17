[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![Checked with mypy](https://img.shields.io/badge/type%20checked-mypy-blue)](http://mypy-lang.org/)
![Uses: typing](https://img.shields.io/badge/uses-typing-blue)

[![Commitizen friendly](https://img.shields.io/badge/commitizen-friendly-brightgreen.svg)](http://commitizen.github.io/cz-cli/)

# ⚡ Gossip Publisher ZMQ
A Core Lightning plugin that **monitors your node's gossip store and broadcasts network events in real-time via ZeroMQ**!
It is a part of the [ln-history project](https://github.com/ln-history)

## Lightning Network Gossip

### 🔍 What is this?
This plugin acts as a bridge between your Core Lightning node and any application that wants to consume Lightning Network gossip data. It continuously monitors the gossip_store file, parses every gossip message into a human-readable format, and broadcasts the gossip data in its raw and parsed form through a ZeroMQ publisher socket.

## 🚀 Features
   - 🔄 Real-time monitoring of the gossip store
   - 🧩 Parses all Lightning Network gossip message types
   - 📡 Publishes structured data via ZeroMQ
   - 🔌 Easy integration with any programming language supporting ZMQ
   - 🧠 Uses the [lnhistoryclient](https://pypi.org/project/lnhistoryclient/) library for accurate message parsing

## 🛠️ Installation

### Prerequisites
   - [Core Lightning node](https://corelightning.org/)
   - [Python 3](https://www.python.org/)
   - [ZeroMQ library](https://zeromq.org/)

### Install the plugin

### Clone the repository
```sh
git clone https://github.com/ln-history/gossip-publisher-zmq.git
cd gossip-publisher-zmq
```

### Install dependencies
```sh
pip install -r requirements.txt
```

### Correcting the shebang
On top of the [main.py](main.py) file there is a line starting with `#!`.
This should be an absolute path pointing to the virual environment just created.

Put in this as the first line: `#!/home/<your-user>/path/to/plugin/gossip-publisher-zmq/.venv/bin/python`

## 🎮 Usage
### Configure the plugin
Create a .env file (feel free to copy the .example.env file) with your configuration settings:
```sh
ZMQ_HOST=127.0.0.1
ZMQ_PORT=5675

DEFAULT_POLL_INTERVAL=1                             # Seconds
DEFAULT_SENDER_NODE_ID=my-gossip-publisher-zmq      # Set a name or id for your node that gets attached to every published message

START_AT_BYTE=<number-of-bytes-to-skip>             # In case your gossip_store file is very big it might make sense to start at a high value due to performance reasons, skipping older gossip messages  
```

#### Start the plugin with Core Lightning

Add to your lightning configuration
```sh
echo "plugin=/path/to/gossip-publisher-zmq/main.py" >> ~/.lightning/config
```

Or start it directly with lightningd
```sh
lightningd --plugin=/path/to/gossip-publisher-zmq/main.py
```

In case you want to configure the env variables, you can also pass them as <key>=<value>, using this syntax:
```sh
lightning-cli -k plugin subcommand=start plugin=/path/to/plugin/gossip-publisher-zmq/main.py zmq-port=5675
```

Check plugin status
```sh
lightning-cli gpz-status
```

## 📊 Message Format
Each message published by the plugin follows a JSON structure. For example a `channel_announcement`, looks like this:

```json
{
    "metadata": {
        "type": 256,
        "name": "channel_announcement",
        "timestamp": 1686923456,
        "sender_node_id": "03a...b2c",
        "length": 414
    },
    "raw_hex": "0102...",
    "parsed": {
        "channel_id": "631...ab9",
        "node1_id": "02d...f4c",
        "node2_id": "03a...e7b",
        "bitcoin_key1": "02e...a4d",
        "bitcoin_key2": "03f...c7e",
        "chain_hash": "06...ee",
        "scid": "103x2x1"
    }
}
```

The library [lnhistoryclient](https://pypi.org/project/lnhistoryclient/) provides python classes, types, functions and much more for the gossip messages.


## 🧙‍♂️ Subscribing to messages
You can subscribe to gossip messages in any language with ZeroMQ support:

This repository provides a simple python [example](./subscriber.py), to see the results of this plugin.

```python
import zmq
import json

context = zmq.Context()
socket = context.socket(zmq.SUB)
socket.connect("tcp://localhost:5675")

# Subscribe to all messages
socket.setsockopt_string(zmq.SUBSCRIBE, "")
# Or specific message types
# socket.setsockopt_string(zmq.SUBSCRIBE, "channel_announcement")

while True:
    topic = socket.recv_string()
    message = socket.recv_string()
    data = json.loads(message)
    print(f"Received {topic}: {data}")
```

# Message Types
| Type Number | Name | Description |
| :--- | :--- | :--- |
| 256 | `channel_announcement` | Announces new channels |
| 257 | `node_announcement` | Broadcasts node information and features |
| 258 | `channel_update` | Updates channel routing policies |
| 4101 | `channel_amount` | Channel capacity information (Core Lightning specific) |
| 4102 | `private_update` | Updates for private channels (Core Lightning specific) |
| 4103 | `delete_channel` | Channel deletion notifications (Core Lightning specific) |
| 4104 | `private_channel` | Private channel information (Core Lightning specific) |
| 4105 | `store_ended` | Gossip store end markers (Core Lightning specific) |
| 4106 | `channel_dying` | Channels about to be removed (Core Lightning specific) |



## 🧪 Development

### Setup development environment
```sh
python -m venv venv
source venv/bin/activate
pip install -r requirements-dev.txt
```

## 🧹 Format code
```sh
pre-commit run --all-files --verbose
```

## 🤝 Contributing
Contributions are welcome! Please feel free to submit a Pull Request.
   - Fork the repository
   - Create your feature branch (git checkout -b feature/amazing-feature)
   - Commit your changes (git commit -m 'Add some amazing feature')
   - Push to the branch (git push origin feature/amazing-feature)
   - Open a Pull Request

## 📜 License
This project is licensed under the MIT License - see the [LICENSE file](./LICENSE) for details.

## 🙏 Acknowledgements
Core Lightning team for their amazing work
All the contributors to the Lightning Network specifications


Made with ⚡ by Fabian Kraus