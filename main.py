#!/Users/fabiankraus/Programming/lightning/plugins/gossip-publisher-zmq/.venv/bin/python

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
from typing import Any, BinaryIO, Dict, Optional, Tuple, Union, cast

import zmq
from lnhistoryclient.constants import (
    CORE_LIGHTNING_TYPES,
    GOSSIP_TYPE_NAMES,
    HEADER_FORMAT,
    LIGHTNING_TYPES,
    MSG_TYPE_GOSSIP_STORE_ENDED,
)
from lnhistoryclient.model.ChannelAnnouncement import ChannelAnnouncement
from lnhistoryclient.model.ChannelUpdate import ChannelUpdate
from lnhistoryclient.model.core_lightning_internal.ChannelAmount import ChannelAmount
from lnhistoryclient.model.core_lightning_internal.ChannelDying import ChannelDying
from lnhistoryclient.model.core_lightning_internal.DeleteChannel import DeleteChannel
from lnhistoryclient.model.core_lightning_internal.GossipStoreEnded import GossipStoreEnded
from lnhistoryclient.model.core_lightning_internal.PrivateChannelAnnouncement import PrivateChannelAnnouncement
from lnhistoryclient.model.core_lightning_internal.PrivateChannelUpdate import PrivateChannelUpdate
from lnhistoryclient.model.core_lightning_internal.types import ParsedCoreLightningGossipDict, PluginCoreLightningEvent
from lnhistoryclient.model.NodeAnnouncement import NodeAnnouncement
from lnhistoryclient.model.types import ParsedGossipDict, PluginEvent, PluginEventMetadata
from lnhistoryclient.parser import parser_factory
from lnhistoryclient.parser.common import get_message_type_by_raw_hex, strip_known_message_type
from pyln.client import Plugin

from config import DEFAULT_POLL_INTERVAL, DEFAULT_SENDER_NODE_ID, DEFAULT_ZMQ_HOST, DEFAULT_ZMQ_PORT, OFFSET_FILE_NAME

# Constants
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)


class GossipPublisher:
    """Monitors the gossip_store file and publishes messages to ZMQ."""

    def __init__(self, plugin: Plugin, zmq_endpoint: str, sender_node_id: Optional[str]) -> None:
        """Initialize the publisher with plugin instance and configuration."""
        self.plugin = plugin
        self.zmq_endpoint = zmq_endpoint
        self.sender_node_id = sender_node_id

        # ZeroMQ setup
        self.zmq_context = zmq.Context()
        self.zmq_socket = self.zmq_context.socket(zmq.PUB)

        # File handling
        self.offset_store_path: Path = Path(OFFSET_FILE_NAME)
        self.gossip_store_path: Optional[Path] = None
        self.current_offset = 0
        self.file_handle: Optional[BinaryIO] = None

        # Threading
        self.running = False
        self.monitor_thread: Optional[threading.Thread] = None

    def _publish_to_zmq(self, topic: str, payload: Union[ParsedGossipDict, ParsedCoreLightningGossipDict]) -> None:
        """Publish a message to the ZMQ socket."""
        try:
            # First frame: topic
            self.zmq_socket.send_string(topic, zmq.SNDMORE)

            # Check JSON serializability
            if not self._is_json_serializable(payload):
                self.plugin.log("Payload is not JSON serializable!", level="error")
                self.plugin.log(f"Payload: {payload}", level="debug")
                return

            # Second frame: JSON payload
            json_str = json.dumps(payload)
            self.zmq_socket.send_string(json_str)

            self.plugin.log(f"Published {topic} message", level="info")

        except Exception as e:
            self.plugin.log(f"Error publishing message: {e}", level="error")

    def _is_json_serializable(self, obj: Any) -> bool:
        """Check if an object can be serialized to JSON."""
        try:
            json.dumps(obj)
            return True
        except (TypeError, OverflowError):
            return False

    def _parse_gossip(
        self, msg_type: int, msg_name: str, raw_hex: str
    ) -> Optional[Union[ParsedGossipDict, ParsedCoreLightningGossipDict]]:
        """Parse a message using lnhistoryclient parser."""
        try:
            parser_fn = parser_factory.get_parser_by_message_type(msg_type)
            if not parser_fn:
                self.plugin.log(f"No parser function found for msg_type: {msg_type}", level="debug")
                return None

            raw_bytes = bytes.fromhex(raw_hex)
            parsed: Union[
                ChannelAnnouncement,
                NodeAnnouncement,
                ChannelUpdate,
                ChannelAmount,
                ChannelDying,
                DeleteChannel,
                GossipStoreEnded,
                PrivateChannelAnnouncement,
                PrivateChannelUpdate,
            ] = parser_fn(raw_bytes)
            self.plugin.log(f"Parsed message: {parsed.to_dict()}")

            if hasattr(parsed, "to_dict"):
                return parsed.to_dict()
            else:
                return vars(parsed)

        except Exception as e:
            self.plugin.log(f"Error parsing {msg_name} payload: {e}", level="error")
            self.plugin.log(f"Message data in hex: {raw_hex}", level="error")
            return None

    def setup_zmq(self) -> None:
        """Bind the ZMQ socket to the specified endpoint."""
        try:
            self.zmq_socket.bind(self.zmq_endpoint)
            self.plugin.log(f"ZMQ publisher bound to {self.zmq_endpoint}", level="info")
        except zmq.error.ZMQError as e:
            self.plugin.log(f"Error binding ZMQ socket: {e}", level="error")
            raise

    def load_offset(self) -> int:
        """Load the last known offset from a file."""
        if self.offset_store_path.exists():
            try:
                with open(self.offset_store_path, "r") as f:
                    data = json.load(f)
                    offset: int = data.get("offset", 1)
                    self.plugin.log(f"Loaded offset: {offset}", level="info")
                    return offset
            except Exception as e:
                self.plugin.log(f"Failed to read offset file: {e}", level="warn")
        return 1  # default offset after version byte

    def save_offset(self) -> None:
        """Persist the current offset to a file."""
        try:
            with open(self.offset_store_path, "w") as f:
                json.dump({"offset": self.current_offset}, f)
        except Exception as e:
            self.plugin.log(f"Failed to write offset: {e}", level="error")

    def start(self) -> None:
        """Start the monitoring thread."""
        self.running = True
        self.monitor_thread = threading.Thread(target=self.monitor_loop)
        self.monitor_thread.daemon = True
        self.monitor_thread.start()
        self.plugin.log("GossipPublisher thread started", level="info")

    def stop(self) -> None:
        """Stop the monitoring thread and clean up resources."""
        self.running = False

        # Join thread
        if self.monitor_thread and self.monitor_thread.is_alive():
            self.monitor_thread.join(timeout=1.0)
            self.plugin.log("Monitor thread stopped", level="info")

        # Close file
        if self.file_handle:
            self.file_handle.close()

        # Close ZMQ
        self.zmq_socket.close()
        self.zmq_context.term()
        self.plugin.log("ZMQ resources cleaned up", level="info")

    def open_gossip_store(self) -> bool:
        """Open the gossip_store file and validate its version."""
        try:
            self.file_handle = cast(BinaryIO, open(self.gossip_store_path, "rb"))  # type: ignore[arg-type]

            # Read and verify version
            version_byte = self.file_handle.read(1)
            if not version_byte:
                self.plugin.log("Empty gossip_store file", level="warn")
                return False

            version = int(version_byte[0])
            major_version = (version >> 5) & 0x07
            minor_version = version & 0x1F

            if major_version != 0:
                self.plugin.log(f"Unsupported gossip_store major version: {major_version}", level="error")
                return False

            self.plugin.log(f"Opened gossip_store file, version {major_version}.{minor_version}", level="info")

            # Attempt to resume from stored offset
            offset = self.load_offset()
            self.file_handle.seek(offset)
            self.current_offset = offset
            self.plugin.log(f"Seeked to offset {offset}", level="info")

            # Test if this offset is valid by attempting to read one header
            header = self.read_header()
            if header is None:
                self.plugin.log(f"Offset {offset} is invalid. Falling back to beginning.", level="warn")
                self.file_handle.seek(1)
                self.current_offset = 1

            return True

        except Exception as e:
            self.plugin.log(f"Error opening gossip_store: {e}", level="error")
            if self.file_handle:
                self.file_handle.close()
            return False

    def read_header(self) -> Optional[Tuple[int, int, int, int]]:
        """Read and parse a message header from the file."""
        if not self.file_handle:
            return None

        try:
            header_data = self.file_handle.read(HEADER_SIZE)
            if len(header_data) < HEADER_SIZE:
                return None

            flags, msg_len, crc, timestamp = struct.unpack(HEADER_FORMAT, header_data)
            self.current_offset += HEADER_SIZE
            return flags, msg_len, crc, timestamp

        except Exception as e:
            self.plugin.log(f"Error reading header: {e}", level="debug")
            return None

    def read_message(self, msg_len: int) -> Optional[bytes]:
        """Read message data of specified length from file."""
        if not self.file_handle:
            self.plugin.log("File handle is None, cannot read message", level="error")
            return None

        try:
            message_data = self.file_handle.read(msg_len)
            if not message_data or len(message_data) < msg_len:
                return None

            self.current_offset += msg_len
            return message_data

        except Exception as e:
            self.plugin.log(f"Error reading message: {e}", level="error")
            return None

    def process_message(self, msg_data: bytes, timestamp: int) -> bool:
        """Process and publish a gossip message. Return False if processing should stop."""
        if not msg_data or len(msg_data) < 2:
            return True

        msg_type = get_message_type_by_raw_hex(msg_data)
        msg_name = GOSSIP_TYPE_NAMES.get(msg_type, f"UNKNOWN_{msg_type}")
        raw_hex = msg_data.hex()

        metadata: PluginEventMetadata = {
            "type": msg_type,
            "name": msg_name,
            "timestamp": timestamp or int(time.time()),
            "sender_node_id": self.sender_node_id,
            "length": len(msg_data) - 2,
        }

        parsed = self._parse_gossip(msg_type, msg_name, strip_known_message_type(msg_data).hex())

        if msg_type in LIGHTNING_TYPES or msg_type in CORE_LIGHTNING_TYPES:
            payload: Union[PluginEvent, PluginCoreLightningEvent] = {
                "metadata": metadata,
                "raw_hex": raw_hex,
                "parsed": parsed,
            }
            self._publish_to_zmq(msg_name, payload)
        else:
            self.plugin.log(f"Skipped publishing unknown message type {msg_type} ({msg_name})", level="debug")

        # Handle special message: gossip_store_ended
        if msg_type == MSG_TYPE_GOSSIP_STORE_ENDED:
            return self.handle_ended_message()

        return True

    def handle_ended_message(self) -> bool:
        """Handle the gossip_store_ended message by reopening the file."""
        self.plugin.log("Detected gossip_store_ended, reopening file", level="warn")
        if self.file_handle:
            self.file_handle.close()

        time.sleep(1)  # Wait a bit for the new file to be ready
        return self.open_gossip_store()

    def monitor_loop(self) -> None:
        """Main monitoring loop that processes messages from the gossip store."""
        while self.running:
            if not self.gossip_store_path:
                self._resolve_gossip_store_path()
                if not self.gossip_store_path:
                    time.sleep(DEFAULT_POLL_INTERVAL)
                    continue

            if not self.file_handle and not self.open_gossip_store():
                time.sleep(DEFAULT_POLL_INTERVAL)
                continue

            try:
                while self.running:
                    header = self.read_header()
                    if not header:
                        break  # End of file

                    flags, msg_len, crc, timestamp = header
                    msg_data = self.read_message(msg_len)
                    if not msg_data:
                        break

                    if not self.process_message(msg_data, timestamp):
                        break  # For example, when GOSSIP_STORE_ENDED is received

                time.sleep(DEFAULT_POLL_INTERVAL)

            except Exception as e:
                self.plugin.log(f"Error in monitor loop: {e}", level="error")
                if self.file_handle:
                    self.file_handle.close()
                time.sleep(DEFAULT_POLL_INTERVAL)

    def _resolve_gossip_store_path(self) -> None:
        """Determine the path to the gossip_store file."""
        try:
            info = self.plugin.rpc.getinfo()
            lightning_dir = Path(info["lightning-dir"])
            self.gossip_store_path = lightning_dir / "gossip_store"
            self.plugin.log(f"Resolved gossip store path: {self.gossip_store_path}", level="info")
        except Exception as e:
            self.plugin.log(f"Failed to resolve gossip store path: {e}", level="error")


# Initialize plugin
plugin = Plugin()

plugin.add_option("zmq-port", "5675", "Port to bind ZMQ PUB socket")
plugin.add_option("zmq-host", "127.0.0.1", "Host to bind ZMQ PUB socket")
plugin.add_option("sender-node-id", "", "Optional override for sender_node_id")


def resolve_sender_node_id(plugin: Plugin) -> Optional[str]:
    """Attempt to get sender_node_id from RPC, fallback to env variable."""
    try:
        info = plugin.rpc.call("getinfo")
        sender_node_id = str(info["id"])  # explicitly convert to str
        plugin.log(f"Retrieved node_id via getinfo: {sender_node_id}", level="info")
        return sender_node_id
    except Exception as e:
        plugin.log(f"Failed to retrieve node_id from getinfo: {e}", level="warn")

    # Fall back to default
    fallback_node_id = DEFAULT_SENDER_NODE_ID
    if fallback_node_id:
        plugin.log(f"Using DEFAULT_SENDER_NODE_ID from environment: {fallback_node_id}", level="info")
    else:
        plugin.log("No DEFAULT_SENDER_NODE_ID found via RPC or environment", level="warn")

    return fallback_node_id or None


@plugin.init()
def init(options: Dict[str, Any], configuration: Dict[str, Any], plugin: Plugin) -> None:
    """Initialize the plugin."""
    plugin.log("Gossip ZMQ Publisher initializing", level="info")

    # Get configuration
    zmq_port: int = plugin.get_option("zmq-port") or DEFAULT_ZMQ_PORT
    zmq_host: str = plugin.get_option("zmq-host") or DEFAULT_ZMQ_HOST
    sender_node_id: Optional[str] = plugin.get_option("sender-node-id") or resolve_sender_node_id(plugin)

    zmq_endpoint = f"tcp://{zmq_host}:{zmq_port}"

    # Create and start the gossip publisher
    plugin.gossip_monitor = GossipPublisher(plugin, zmq_endpoint, sender_node_id)
    plugin.gossip_monitor.setup_zmq()
    plugin.gossip_monitor.start()

    plugin.log(f"Gossip ZMQ Publisher started, publishing to {zmq_endpoint}", level="info")
    plugin.log("Use `lightning-cli gpz-status` to get a status update of the plugin.", level="info")


@plugin.method("gpz-status", desc="Returns the live status of the plugin")
def status() -> Dict[str, Any]:
    """Return status information about the gossip ZMQ publisher."""
    gossip_publisher: GossipPublisher = cast(GossipPublisher, getattr(plugin, "gossip_monitor", None))

    return {
        "running": gossip_publisher.running if gossip_publisher else False,
        "zmq_endpoint": gossip_publisher.zmq_endpoint if gossip_publisher else None,
        "sender_node_id": gossip_publisher.sender_node_id if gossip_publisher else None,
        "gossip_store_path": (
            str(gossip_publisher.gossip_store_path) if gossip_publisher and gossip_publisher.gossip_store_path else None
        ),
    }


if __name__ == "__main__":
    plugin.run()
