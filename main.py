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
from zmq import SyncSocket
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
from lnhistoryclient.parser.common import get_message_type_by_bytes, strip_known_message_type, varint_decode
from pyln.client import Plugin

from config import DEFAULT_POLL_INTERVAL, DEFAULT_SENDER_NODE_ID, DEFAULT_ZMQ_HOST, DEFAULT_ZMQ_PORT, SAVE_INTERVAL, OFFSET_FILE_NAME_WITH_PATH

# Constants
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)


class GossipPublisher:
    """Monitors the gossip_store file and publishes messages to ZMQ."""

    def __init__(self, plugin: Plugin, zmq_endpoint: str, sender_node_id: str, save_interval: float, offset_file_name_with_path: str) -> None:
        """Initialize the publisher with plugin instance and configuration."""
        self.plugin = plugin
        self.zmq_endpoint: str = zmq_endpoint
        self.sender_node_id: str = sender_node_id
        
        # Self-correction error management
        self.error_count = 0
        self.max_error_count = 5
        self.error_watchdog_thread = None

        # ZeroMQ setup
        self.zmq_context = zmq.Context()
        self.zmq_socket: SyncSocket = self.zmq_context.socket(zmq.PUB)

        # File handling
        self.offset_store_path: Path = Path(offset_file_name_with_path)
        self.gossip_store_path: Optional[Path] = None
        self.current_offset: int = 0
        self.file_handle: Optional[BinaryIO] = None
        self.save_interval: float = save_interval

        # Monitoring
        self.running = False
        self.monitor_thread: Optional[threading.Thread] = None
        self.initialized = threading.Event()  # Event to signal when initialization is complete


    def _publish_to_zmq(self, topic: str, payload: Union[ParsedGossipDict, ParsedCoreLightningGossipDict]) -> None:
        """Publish a message to the ZMQ socket."""
        try:
            # First frame: topic
            self.zmq_socket.send_string(topic, zmq.SNDMORE)

            # Check JSON serializability
            if not self._is_json_serializable(payload):
                self.plugin.log("Payload is not JSON serializable!", level="error")
                self.plugin.log(f"Payload: {payload}", level="warn")
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
        
    def _is_valid_header(self, flags: int, msg_len: int, timestamp: int) -> bool:
        """Validate if header values seem reasonable."""
        # Basic sanity checks
        if msg_len < 0 or msg_len > 65535:  # Max reasonable message size
            return False
        if timestamp < 0 or timestamp > 2**32:  # Reasonable timestamp range
            return False
        # Flags should be reasonable (check specific flag bits if known)
        if flags < 0 or flags > 255:
            return False
        return True

    def _find_valid_starting_position(self) -> bool:
        """Find a valid message boundary to start reading from."""
        if not self.file_handle:
            return False
            
        # Start from beginning (after version byte) and scan forward
        self.file_handle.seek(1)
        self.current_offset = 1
        
        while self.current_offset + HEADER_SIZE < self.file_size:
            if self._validate_current_position():
                self.plugin.log(f"Found valid starting position at offset {self.current_offset}", level="info")
                return True
            
            # Move forward and try again
            self.current_offset += 1
            self.file_handle.seek(self.current_offset)
            
        return False

    def _validate_current_position(self) -> bool:
        """Check if the current file position allows reading a valid header."""
        if not self.file_handle:
            return False

        try:
            file_size = self.gossip_store_path.stat().st_size if self.gossip_store_path else 0
            
            # Check scenario 1: Offset is 1, implying fresh start or error recovery
            if self.current_offset == 1:
                self.plugin.log("Offset is at start position 1", level="info")
                return True

            # Check scenario 2: Offset is between 1 and file_size, resume from last valid position
            elif 1 < self.current_offset < file_size:
                self.plugin.log("Resuming from a previous valid position", level="info")
                self.file_handle.seek(self.current_offset)
                return True

            # Check scenario 3: Offset is equal to file size, indicating no new data since stop
            elif self.current_offset == file_size:
                self.plugin.log("Offset equals file size, waiting for new data", level="info")
                self.file_handle.seek(self.current_offset)  # Set file handle for continued monitoring
                return True

            # Unexpected offset value, log and reset
            self.plugin.log(f"Unexpected offset value: {self.current_offset}", level="error")
            self.error_count += 1
            return False

        except Exception as e:
            self.plugin.log(f"Exception in validating current position: {e}", level="error")
            self.error_count += 1
            return False

    def _parse_gossip(
        self, msg_type: int, msg_name: str, raw_hex: str
    ) -> Optional[Union[ParsedGossipDict, ParsedCoreLightningGossipDict]]:
        """Parse a message using lnhistoryclient parser."""
        try:
            parser_fn = parser_factory.get_parser_by_message_type(msg_type)
            if not parser_fn:
                self.plugin.log(f"No parser function found for msg_type: {msg_type}", level="warn")
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
            
            self.error_count = 0

            if hasattr(parsed, "to_dict"):
                self.plugin.log(f"Parsed message: {parsed.to_dict()} with offset: {self.current_offset}", level="info")
                return parsed.to_dict()
            else:
                return vars(parsed)

        except Exception as e:
            self.plugin.log(f"Error parsing {msg_name} payload: {e}", level="error")
            self.plugin.log(f"Message data in hex: {raw_hex[:1000]}...", level="error")
            self.error_count += 1
            return None
        
    def _resolve_gossip_store_path(self) -> None:
        """Determine the path to the gossip_store file."""
        try:
            info = self.plugin.rpc.getinfo()
            lightning_dir = Path(info["lightning-dir"])
            self.gossip_store_path = lightning_dir / "gossip_store"
            self.plugin.log(f"Resolved gossip store path: {self.gossip_store_path}", level="info")
        except Exception as e:
            self.plugin.log(f"Failed to resolve gossip store path: {e}", level="error")

    def setup_zmq(self) -> None:
        """Bind the ZMQ socket to the specified endpoint."""
        try:
            self.zmq_socket.bind(self.zmq_endpoint)
            self.plugin.log(f"ZMQ publisher bound to {self.zmq_endpoint}", level="info")
        except zmq.error.ZMQError as e:
            self.plugin.log(f"Error binding ZMQ socket: {e}", level="error")
            raise


    def open_gossip_store(self) -> bool:
        """Open the gossip_store file and validate its version."""
        try:
            if not self.gossip_store_path or not self.gossip_store_path.exists():
                self.plugin.log("Gossip store file does not exist", level="error")
                return False
                
            self.file_size = self.gossip_store_path.stat().st_size
            self.file_handle = cast(BinaryIO, open(self.gossip_store_path, "rb"))

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
            # Load and validate offset
            offset = self.load_offset()
                
            self.file_handle.seek(offset)
            self.current_offset = offset
            self.plugin.log(f"Seeked to offset {offset}", level="info")

            # Validate current position by attempting to read
            if not self._validate_current_position():
                self.plugin.log("Invalid position detected, attempting to find valid starting point", level="warn")
                if not self._find_valid_starting_position():
                    self.plugin.log("Could not find valid starting position", level="error")
                    return False

            return True

        except Exception as e:
            self.plugin.log(f"Error opening gossip_store: {e}", level="error")
            if self.file_handle:
                self.file_handle.close()
            return False

    # === Management of message reading  ===

    def read_header(self) -> Optional[Tuple[int, int, int, int]]:
        """Read and parse gossip_store header with enhanced validation."""
        if not self.file_handle:
            return None

        try:                
            header_data = self.file_handle.read(HEADER_SIZE)
            if len(header_data) == 0:
                # Current offset is exactly the length of the gossip store and live monitoring has cought up
                return None

            elif len(header_data) < HEADER_SIZE:
                self.plugin.log(f"Header size of {len(header_data)} is too short.")
                self.error_count += 1
                return None

            flags, msg_len, crc, timestamp = struct.unpack(HEADER_FORMAT, header_data)
            
            # Validate header before updating offset
            if not self._is_valid_header(flags, msg_len, timestamp):
                self.plugin.log(f"Invalid header at offset {self.current_offset}: flags={flags}, len={msg_len}, ts={timestamp}", level="warn")
                self.error_count += 1
                return None
                
            self.current_offset += HEADER_SIZE
            self.error_count = 0
            return flags, msg_len, crc, timestamp

        except Exception as e:
            self.plugin.log(f"Error reading header at offset {self.current_offset}: {e}", level="warn")
            self.error_count += 1
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

        msg_type = get_message_type_by_bytes(msg_data)
        msg_name = GOSSIP_TYPE_NAMES.get(msg_type, f"UNKNOWN_{msg_type}")
        raw_hex = msg_data.hex()

        metadata: PluginEventMetadata = {
            "type": msg_type,
            "name": msg_name,
            "timestamp": int(time.time()),
            "sender_node_id": self.sender_node_id,
            "length": len(msg_data) - 2,                # Subtract 2 Bytes message type 
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
            self.plugin.log(f"Skipped publishing unknown message type {msg_type} ({msg_name})", level="warn")

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

        #
        # === INITIALIZATION PHASE === (run only once)
        #
        while self.running and not self.initialized.is_set():
            if not self.gossip_store_path:
                self._resolve_gossip_store_path()
                if not self.gossip_store_path:
                    time.sleep(DEFAULT_POLL_INTERVAL)
                    continue

            if not self.file_handle and not self.open_gossip_store():
                time.sleep(DEFAULT_POLL_INTERVAL)
                continue

            # Initialization is complete here:
            self.initialized.set()
            self.plugin.log(f"Initialization complete, start monitoring the {self.gossip_store_path} file", level="info")

            # Start the save-offset-thread now that everything is ready
            self.save_thread = threading.Thread(target=self.save_offset_periodically, daemon=True)
            self.save_thread.start()
            self.plugin.log("OffsetSaving thread started", level="info")

        #
        # === LIVE MONITORING PHASE ===
        #
        while self.running:
            try:
                header: Optional[Tuple[int, int, int, int]] = self.read_header()
                if not header:
                    # Possibly EOF -> sleep a bit and try again
                    time.sleep(DEFAULT_POLL_INTERVAL)
                    continue

                flags, msg_len, crc, timestamp = header
                msg_data: Optional[bytes] = self.read_message(msg_len)
                if not msg_data:
                    time.sleep(DEFAULT_POLL_INTERVAL)
                    continue

                if not self.process_message(msg_data, timestamp):
                    break

            except Exception as e:
                self.plugin.log(f"Error in monitor loop: {e}", level="error")
                if self.file_handle:
                    self.file_handle.close()
                time.sleep(DEFAULT_POLL_INTERVAL)


    # === Offset management ===

    def load_offset(self) -> int:
        """Load the last known offset from state file with validation."""
        if not self.offset_store_path.exists():
            self.plugin.log("No offset file found, starting from beginning", level="info")
            return 1
            
        try:
            with open(self.offset_store_path, "r") as f:
                data = json.load(f)
                offset = data.get("offset", 1)
                
                # Validate offset against current file size
                if self.gossip_store_path and self.gossip_store_path.exists():
                    file_size = self.gossip_store_path.stat().st_size
                    if offset > file_size:
                        self.plugin.log(f"Stored offset {offset} > file size {file_size}, resetting to beginning", level="warn")
                        return 1
                    elif offset < 1:
                        self.plugin.log(f"Invalid stored offset {offset}, resetting to beginning", level="warn")
                        return 1
                
                self.plugin.log(f"Loaded offset: {offset}", level="info")
                return offset
                
        except Exception as e:
            self.plugin.log(f"Failed to read offset file: {e}", level="error")
            return 1

    def save_offset(self) -> None:
        """Persist the current offset to the configured path."""
        self.plugin.log(f"Trying to save current offset {self.current_offset} to file {self.offset_store_path}.", level="info")
        try:
            with open(self.offset_store_path, "w") as f:
                json.dump({"offset": self.current_offset}, f)
            self.plugin.log(f"Offset {self.current_offset} saved to {self.offset_store_path}", level="info")
        except Exception as e:
            self.plugin.log(f"Failed to save offset to {self.offset_store_path}: {e}", level="error")

    def save_offset_periodically(self):
        """Periodically save the offset to a file."""
        self.initialized.wait()  # Wait until initialization is complete
        while self.running:
            self.save_offset()
            time.sleep(self.save_interval)

    def error_watchdog(self):
        """Checks the error count and stops the plugin if threshold is reached."""
        while self.running:
            if self.error_count >= self.max_error_count:
                self.plugin.log(f"Got {self.error_count} consecutive errors. The offset is likely off. Initiating stopping of plugin.", level="error")
                self.stop()
                break
            time.sleep(1)


    # === Start of plugin ===

    def start(self) -> None:
        """Start the monitoring thread."""
        self.running = True

        # Start monitor thread
        self.monitor_thread = threading.Thread(target=self.monitor_loop, daemon=True)
        self.monitor_thread.start()
        self.plugin.log("GossipPublisher monitoring thread started", level="info")

        # Start watchdog thread
        self.error_watchdog_thread = threading.Thread(target=self.error_watchdog, daemon=True)
        self.error_watchdog_thread.start()

        
    # === Stop of plugin ===

    def stop(self) -> None:
        """Stop the monitoring thread and clean up resources."""
        self.running = False

        if self.monitor_thread and self.monitor_thread.is_alive():
            self.monitor_thread.join(timeout=2.0)
            self.plugin.log("Monitor thread stopped", level="info")
        
        if self.save_thread and self.save_thread.is_alive():
            self.save_thread.join(timeout=2.0)
            self.plugin.log("Save thread stopped", level="info")
        
        # Close file
        if self.file_handle:
            self.file_handle.close()

        # Close ZMQ
        self.zmq_socket.close()
        self.zmq_context.term()
        self.plugin.log("ZMQ resources cleaned up", level="info")


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

# Initialize plugin
plugin = Plugin()

plugin.add_option("zmq-port", "5675", "Port to bind ZMQ PUB socket")
plugin.add_option("zmq-host", "127.0.0.1", "Host to bind ZMQ PUB socket")
plugin.add_option("sender-node-id", "", "Optional override for sender_node_id")
plugin.add_option("save-interval", "60", "Interval in seconds to save the offset regularly")
plugin.add_option("offset-file-name-with-path", "gossip_offset.json", "File to save the current offset in the gossip_store file")

@plugin.init()
def init(options: Dict[str, Any], configuration: Dict[str, Any], plugin: Plugin) -> None:
    """Initialize the plugin."""
    plugin.log("Gossip ZMQ Publisher initializing", level="info")

    # Get configuration
    zmq_port: int = plugin.get_option("zmq-port") or DEFAULT_ZMQ_PORT
    zmq_host: str = plugin.get_option("zmq-host") or DEFAULT_ZMQ_HOST
    sender_node_id: str = plugin.get_option("sender-node-id") or str(resolve_sender_node_id(plugin))

    zmq_endpoint = f"tcp://{zmq_host}:{zmq_port}"

    save_interval: float = float(plugin.get_option("save-interval")) or SAVE_INTERVAL
    offset_file_name_with_path: Path = Path(plugin.get_option("offset-file-name-with-path")) or OFFSET_FILE_NAME_WITH_PATH

    # Create and start the gossip publisher
    plugin.gossip_monitor = GossipPublisher(plugin, zmq_endpoint, sender_node_id, save_interval, offset_file_name_with_path)
    plugin.gossip_monitor.setup_zmq()
    plugin.gossip_monitor.start()

    plugin.log(f"Gossip ZMQ Publisher started, publishing to {zmq_endpoint}", level="info")
    plugin.log("Use `lightning-cli gpz-status` to get a status update of the plugin.", level="info")
    plugin.log("Use `lightning-cli -k plugin subcommand=start plugin=<path-to-plugin> <option-name>=<value>` to configure the plugin.", level="info")


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
