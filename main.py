"""
gossip-publisher-zmq is a Core Lightning Plugin to publish collected gossip messages via ZeroMQ

This plugin monitors the Core Lightning gossip_store file, parses all gossip messages into a human readable format and forwards the result to a ZeroMQ PUB socket in the following format:
{
    "metadata": {
        "type": <int>,                      // Type of the gossip message as speficied in BOLT #7
        "timestamp": <unix_timestamp>,      // Unix timestamp when the gossip message was collected
        "sender_node_id": <hex>             // `node_id` of the Bitcoin Lightning node that runs the plugin
        "length": <int>                     // Length of the gossip message in bytes excluding the 2 byte field 
    },
    "raw_hex": <>                           // Actual gossip message in raw hex
    "parsed": {}                            // Parsed gossip message using lnhistoryclient library
}
"""

import json
import struct
import threading
import time
from pathlib import Path
from typing import Any, BinaryIO, Optional, Tuple, Union

import zmq
from lnhistoryclient.constants import GOSSIP_TYPE_NAMES, MSG_TYPE_ENDED
from lnhistoryclient.model.gossip_event_zmq.Header import HEADER_FORMAT

# Import the lnhistoryclient parser
from lnhistoryclient.parser import parser_factory
from lnhistoryclient.parser.common import get_message_type_by_raw_hex
from pyln.client import Plugin

from config import SENDER_NODE_ID, ZMQ_HOST, ZMQ_PORT

HEADER_SIZE = struct.calcsize(HEADER_FORMAT)


def is_json_serializable(obj: dict[Any, Any]) -> bool:
    try:
        json.dumps(obj)
        return True
    except Exception:
        return False


plugin = Plugin()


class GossipMonitor:
    def __init__(self, plugin: Plugin, zmq_endpoint: str, sender_node_id: Optional[str]) -> None:
        self.plugin: Plugin = plugin
        self.zmq_endpoint: str = zmq_endpoint
        self.zmq_context: zmq.Context = zmq.Context()
        self.zmq_socket: zmq.SyncSocket = self.zmq_context.socket(zmq.PUB)
        self.running: bool = False
        self.gossip_store_path: Union[str, Path]
        self.current_offset: int = 0
        self.file_handle: Optional[BinaryIO] = None
        self.monitor_thread: Optional[threading.Thread] = None
        self.sender_node_id: Optional[str] = sender_node_id

    def setup_zmq(self) -> None:
        try:
            self.zmq_socket.bind(self.zmq_endpoint)
            self.plugin.log(f"ZMQ publisher bound to {self.zmq_endpoint}", level="info")
        except zmq.error.ZMQError as e:
            self.plugin.log(f"Error binding ZMQ socket: {e}", level="error")
            raise

    def start(self) -> None:
        self.running = True
        self.monitor_thread = threading.Thread(target=self.monitor_loop)
        self.monitor_thread.daemon = True
        self.monitor_thread.start()

    def stop(self) -> None:
        self.running = False
        if self.monitor_thread and self.monitor_thread.is_alive():
            self.monitor_thread.join(timeout=1.0)
        if self.file_handle:
            self.file_handle.close()
        self.zmq_socket.close()
        self.zmq_context.term()

    def open_gossip_store(self) -> bool:
        """Open the gossip_store file and check version."""
        try:
            self.file_handle = open(self.gossip_store_path, "rb")

            # Read and verify version
            version_byte = self.file_handle.read(1)
            if not version_byte:
                self.plugin.log("Empty gossip_store file", level="warn")
                return False

            version: int = int(version_byte[0])
            major_version = (version >> 5) & 0x07
            minor_version = version & 0x1F

            if major_version != 0:
                self.plugin.log(f"Unsupported gossip_store major version: {major_version}", level="error")
                return False

            self.plugin.log(f"Opened gossip_store file, version {major_version}.{minor_version}")
            self.current_offset = 1  # Skip the version byte
            return True

        except Exception as e:
            self.plugin.log(f"Error opening gossip_store: {e}", level="error")
            if self.file_handle:
                self.file_handle.close()
                self.file_handle = None
            return False

    def read_header(self) -> Optional[Tuple[int, int, int, int]]:
        """Read and parse a record header."""
        try:
            header_data: bytes = self.file_handle.read(HEADER_SIZE)  # type: ignore[union-attr]
            if len(header_data) < HEADER_SIZE:
                return None

            flags, msg_len, crc, timestamp = struct.unpack(HEADER_FORMAT, header_data)
            self.current_offset += HEADER_SIZE

            return flags, msg_len, crc, timestamp
        except Exception as e:
            self.plugin.log(f"Error reading header: {e}", level="debug")
            return None

    def read_message(self, msg_len: int) -> Optional[bytes]:
        """Read the message body."""
        if self.file_handle is None:
            self.plugin.log("File handle is None, cannot read message", level="error")
            return None

        try:
            message_data = self.file_handle.read(msg_len)
            if message_data is None or len(message_data) < msg_len:
                return None

            self.current_offset += msg_len
            return message_data
        except Exception as e:
            self.plugin.log(f"Error reading message: {e}", level="error")
            return None

    def process_message(self, msg_data: bytes, timestamp: int) -> None:
        """Process and forward a gossip message."""
        if not msg_data or len(msg_data) < 2:
            return

        # Extract message type (big-endian 16-bit integer)
        msg_type = get_message_type_by_raw_hex(msg_data)
        msg_name = GOSSIP_TYPE_NAMES[msg_type]

        # Create message info object
        msg_info = {
            "type": msg_type,
            "name": msg_name,
            "timestamp": timestamp,
            "sender_node_id": self.sender_node_id,
            "length": len(msg_data) - 2,  # Exclude the type field
        }

        # Send message type as topic and full message data + metadata
        try:
            # Topic is the message name
            self.zmq_socket.send_string(msg_name, zmq.SNDMORE)

            # Use lnhistoryclient parser
            raw_hex = msg_data.hex()
            parsed_dict = None
            try:
                parsed = parser_factory.get_parser_by_message_type(msg_type)
                if parsed:
                    # Convert parsed object to dictionary if it has a to_dict method
                    if hasattr(parsed, "to_dict"):
                        parsed_dict = parsed.to_dict()
                    else:
                        # If no to_dict method, try to convert to dict directly
                        parsed_dict = vars(parsed)
            except Exception as parse_error:
                self.plugin.log(f"Error parsing {msg_name} payload: {parse_error}", level="error")
                self.plugin.log(f"Message data in hex: {raw_hex}", level="error")

            payload = {"metadata": msg_info, "raw_hex": raw_hex, "parsed": parsed_dict}

            self.plugin.log("Sending payload", level="debug")
            self.plugin.log(f"Metadata: {payload['metadata']}", level="debug")

            if not is_json_serializable(payload):
                self.plugin.log("Payload is not JSON serializable!", level="error")
                self.plugin.log(f"Payload: {payload}", level="error")

            try:
                json_str = json.dumps(payload)
                self.zmq_socket.send_string(json_str)
            except TypeError as type_error:
                self.plugin.log(f"Serialization TypeError: {type_error}", level="error")
                self.plugin.log(f"Offending payload: {repr(payload)}", level="error")

            self.plugin.log(f"Published {msg_name} message", level="info")
        except Exception as e:
            self.plugin.log(f"Error publishing message: {e}", level="error")

    def handle_ended_message(self) -> bool:
        """Handle the gossip_store_ended message by reopening the file."""
        self.plugin.log("Detected gossip_store_ended, reopening file", level="info")
        if self.file_handle:
            self.file_handle.close()
            self.file_handle = None

        time.sleep(1)  # Wait a bit for the new file to be ready
        return self.open_gossip_store()

    def monitor_loop(self) -> None:
        """Main monitoring loop."""
        poll_interval = 1.0  # seconds

        while self.running:
            # Get gossip_store path if we don't have it yet
            if not self.gossip_store_path:
                info = self.plugin.rpc.getinfo()
                lightning_dir = Path(info["lightning-dir"])
                self.gossip_store_path = lightning_dir / "gossip_store"
                self.plugin.log(f"Gossip store path: {self.gossip_store_path}")

            # (Re)open the file if needed
            if not self.file_handle:
                if not self.open_gossip_store():
                    time.sleep(poll_interval)
                    continue

            try:
                # Process records until we hit the end of the file
                while self.running:
                    header = self.read_header()
                    if not header:
                        break

                    flags, msg_len, crc, timestamp = header
                    msg_data = self.read_message(msg_len)
                    if not msg_data:
                        break

                    if timestamp == 0:
                        timestamp = int(time.time())

                    # Process the message
                    self.process_message(msg_data, timestamp)

                    # If this is a "store_ended" message, reopen the file
                    if len(msg_data) >= 2:
                        msg_type = get_message_type_by_raw_hex(msg_data)
                        if msg_type == MSG_TYPE_ENDED:
                            if not self.handle_ended_message():
                                break

                # Wait a bit before checking for new data
                time.sleep(poll_interval)

            except Exception as e:
                self.plugin.log(f"Error in monitor loop: {e}", level="error")
                if self.file_handle:
                    self.file_handle.close()
                    self.file_handle = None
                time.sleep(poll_interval)


@plugin.init()  # type: ignore[misc]
def init(options: dict[str, Any], configuration: dict[Any, Any], plugin: Plugin) -> None:
    plugin.log("Gossip ZMQ Publisher initializing")

    # Manually retrieve the ZMQ endpoint from options or use the default
    zmq_endpoint = options.get("gossip-zmq-endpoint", f"tcp://{ZMQ_HOST}:{ZMQ_PORT}")
    if not SENDER_NODE_ID:
        plugin.log("Missing SENDER_NODE_ID: No use of SENDER_NODE_ID in zmq published events", level="warning")

    # Create and start the gossip monitor
    plugin.gossip_monitor = GossipMonitor(plugin, zmq_endpoint, SENDER_NODE_ID)
    plugin.gossip_monitor.setup_zmq()
    plugin.gossip_monitor.start()

    plugin.log(f"Gossip ZMQ Publisher started, publishing to {zmq_endpoint}")
    plugin.log("Use `lightning-cli gpz-status` to get a status update of the plugin.")


@plugin.method("gpz-status", desc="Returns the live status of the plugin")  # type: ignore[misc]
def status() -> dict[str, object]:
    """Return status information about the gossip ZMQ publisher."""
    return {
        "running": plugin.gossip_monitor.running if hasattr(plugin, "gossip_monitor") else False,
        "zmq_endpoint": plugin.gossip_monitor.zmq_endpoint if hasattr(plugin, "gossip_monitor") else None,
        "gossip_store_path": (
            str(plugin.gossip_monitor.gossip_store_path)
            if hasattr(plugin, "gossip_monitor") and plugin.gossip_monitor.gossip_store_path
            else None
        ),
    }


if __name__ == "__main__":
    plugin.run()
