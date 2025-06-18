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

Clone the repository
```sh
git clone https://github.com/ln-history/gossip-publisher-zmq.git
cd gossip-publisher-zmq
```

Install dependencies
```sh
pip install -r requirements.txt
```

## 🎮 Usage
Configure the plugin.
Create a .env file with your ZeroMQ settings:
```sh
ZMQ_HOST=0.0.0.0
ZMQ_PORT=5675
SENDER_NODE_ID=<your_node_pubkey_here>
```

#### Start the plugin with Core Lightning

Add to your lightning configuration
```sh
echo "plugin=/path/to/gossip-publisher-zmq/main.py" >> ~/.lightning/config
```

Or start it directly with lightningd
```bash
lightningd --plugin=/path/to/gossip-publisher-zmq/main.py
```

Check plugin status

```
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
    "raw_hex": "0102...", #raw_hex
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

## 🧙‍♂️ Subscribing to messages
You can subscribe to gossip messages in any language with ZeroMQ support:

This repository provides a simple python [example](./subscriber.py)

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

## 💬 Message Types
The plugin handles all types of Lightning Network gossip messages:

📢 channel_announcement - Announces new channels
👤 node_announcement - Broadcasts node information and features
🔄 channel_update - Updates channel routing policies
💰 channel_amount - Channel capacity information (Core Lightning specific)
🕵️ private_update - Updates for private channels (Core Lightning specific)
🗑️ delete_channel - Channel deletion notifications (Core Lightning specific)
🔒 private_channel - Private channel information (Core Lightning specific)
🏁 store_ended - Gossip store end markers (Core Lightning specific)
💀 channel_dying - Channels about to be removed (Core Lightning specific)

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
This project is licensed under the Apache License 2.0 - see the [LICENSE file](./LICENSE) for details.

## 🙏 Acknowledgements
Core Lightning team for their amazing work
All the contributors to the Lightning Network specifications


Made with ⚡ by Fabian Kraus