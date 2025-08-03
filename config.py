import os

from dotenv import load_dotenv

load_dotenv()

DEFAULT_ZMQ_HOST = os.getenv("DEFAULT_ZMQ_HOST", "127.0.0.1")
DEFAULT_ZMQ_PORT = int(os.getenv("DEFAULT_ZMQ_PORT", "5675"))

DEFAULT_SENDER_NODE_ID = str(os.getenv("DEFAULT_SENDER_NODE_ID"))  # no default value for sender_node_id

DEFAULT_POLL_INTERVAL = float(os.getenv("DEFAULT_POLL_INTERVAL", 1.0))  # seconds

OFFSET_FILE_NAME_WITH_PATH = os.getenv("OFFSET_FILE_NAME_WITH_PATH", "gossip_offset.json")

SAVE_INTERVAL = float(os.getenv("SAVE_INTERVAL", 60))
