import os
from dotenv import load_dotenv

load_dotenv()

ZMQ_HOST = os.getenv("ZMQ_HOST", "0.0.0.0")
ZMQ_PORT = os.getenv("ZMQ_PORT", "5675")

SENDER_NODE_ID = os.getenv("SENDER_NODE_ID")