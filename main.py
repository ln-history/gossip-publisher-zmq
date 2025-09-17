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

import errno
import json
import struct
import threading
import time
from pathlib import Path
from threading import Thread
from typing import Any, BinaryIO, Dict, Optional, Tuple, Union, cast

import zmq
from crc32c import crc32c
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
from lnhistoryclient.parser.common import get_message_type_by_bytes, strip_known_message_type, varint_encode
from pyln.client import Plugin
from zmq import SyncSocket

from config import DEFAULT_SENDER_NODE_ID, DEFAULT_ZMQ_HOST, DEFAULT_ZMQ_PORT, POLL_INTERVAL, START_AT_BYTE

# Constants
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)


class GossipPublisher:
    """Monitors the gossip_store file and publishes messages to ZMQ."""

    def __init__(self, plugin: Plugin, zmq_endpoint: str, sender_node_id: str) -> None:
        """Initialize the publisher with plugin instance and configuration."""
        self.plugin: Plugin = plugin
        self.zmq_endpoint: str = zmq_endpoint
        self.sender_node_id: str = sender_node_id

        # ZeroMQ setup
        self.zmq_context = zmq.Context()
        self.zmq_socket: SyncSocket = self.zmq_context.socket(zmq.PUB)
        self.zmq_socket.setsockopt(zmq.LINGER, 1000)

        # File handling
        self.gossip_store_path: Optional[Path] = None
        self.file_handle: Optional[BinaryIO] = None

        # Monitoring
        self.running: bool = False
        self.monitor_thread: Optional[Thread] = None
        self.initialized = threading.Event()  # Event to signal when initialization is complete

    def setup_zmq(self) -> None:
        """Bind the ZMQ socket to the specified endpoint."""
        try:
            self.zmq_socket.bind(self.zmq_endpoint)
            self.plugin.log(f"ZMQ publisher bound to {self.zmq_endpoint}", level="info")
        except zmq.error.ZMQError as e:
            if e.errno == errno.EADDRINUSE:
                self.plugin.log(
                    f"ZMQ address already in use: {self.zmq_endpoint}. " "Is another instance running?", level="error"
                )
            else:
                self.plugin.log(f"Error binding ZMQ socket: {e}", level="error")

            self.running = False

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

            if hasattr(parsed, "to_dict"):
                return parsed.to_dict()
            else:
                return vars(parsed)

        except Exception as e:
            self.plugin.log(f"Error parsing {msg_name} payload: {e}", level="error")
            self.plugin.log(f"Message data in hex: {raw_hex[:1000]}...", level="error")
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

    def _open_gossip_store(self) -> bool:
        """Open the gossip_store file, validate its version and check if any gossip messages exist."""
        try:
            if not self.gossip_store_path or not self.gossip_store_path.exists():
                self.plugin.log("Gossip store file does not exist", level="error")
                return False

            self.file_size = self.gossip_store_path.stat().st_size
            if self.file_size < 1:
                self.plugin.log(f"Empty gossip_store file at {self.gossip_store_path}", level="error")
                return False

            self.file_handle = cast(BinaryIO, open(self.gossip_store_path, "rb"))

            # Read version byte
            version_byte = self.file_handle.read(1)
            if not version_byte:
                self.plugin.log("Failed to read gossip_store version byte", level="error")
                return False

            version = version_byte[0]
            major_version = (version >> 5) & 0x07
            minor_version = version & 0x1F

            if major_version != 0:
                self.plugin.log(f"Unsupported gossip_store major version: {major_version}", level="error")
                return False

            self.plugin.log(
                f"Opened gossip_store file, version {major_version}.{minor_version}",
                level="info",
            )

            # Seek to offset 1 (after version byte) to position file handle there
            self.file_handle.seek(1)
            self.plugin.log(f"Positioned file_handle at offset {self.file_handle.tell()}", level="info")
            return True

        except Exception as e:
            self.plugin.log(f"Error opening gossip_store: {e}", level="error")
            if self.file_handle:
                self.file_handle.close()
                self.file_handle = None
            return False

    # === Management of message reading  ===

    def _read_header(self) -> Optional[Tuple[int, int, int, int]]:
        """Read and parse gossip_store header with enhanced validation."""

        if not self.file_handle:
            self.plugin.log("Could not read header, due to missing file_handle", level="error")
            self.running = False
            return None

        try:
            start = self.file_handle.tell()

            header_data = self.file_handle.read(HEADER_SIZE)
            if len(header_data) < HEADER_SIZE:
                # EOF or incomplete header
                return None

            flags, msg_len, crc, timestamp = struct.unpack(HEADER_FORMAT, header_data)

            # Verify if the read values are correct via CRC32C, see: https://docs.corelightning.org/docs/contribute-to-core-lightning#the-record-header
            payload: bytes = self.file_handle.read(msg_len)

            if len(payload) < msg_len:
                self.plugin.log(
                    f"Likely incomplete message (EOF): During length check of payload with length = {len(payload)} but needs to be {msg_len}",
                    level="warn",
                )
                self.file_handle.seek(start)
                return None

            computed_crc = crc32c(payload, timestamp) & 0xFFFFFFFF
            if computed_crc != crc:
                self.plugin.log(
                    f"CRC32C mismatch at offset {self.file_handle.tell()}, started from {start}: expected {crc}, got {computed_crc}",
                    level="warn",
                )
                self.file_handle.seek(start)
                return None

            # CRC correct -> move file pointer back to start of payload so live loop can read it
            self.file_handle.seek(start + HEADER_SIZE)
            return flags, msg_len, crc, timestamp

        except Exception as e:
            self.plugin.log(f"Exception while reading header at offset {self.file_handle.tell()}: {e}", level="error")
            return None

    def _read_payload(self, msg_len: int) -> Optional[bytes]:
        """Read message payload of specified length from file."""
        if not self.file_handle:
            self.plugin.log("File handle is None, cannot read message", level="error")
            return None

        try:
            start: int = self.file_handle.tell()
            message_payload: bytes = self.file_handle.read(msg_len)
            if not message_payload or len(message_payload) < msg_len:
                # incomplete message (likely EOF), restore file pointer and return None
                self.file_handle.seek(start)
                return None

            return message_payload

        except Exception as e:
            try:
                self.file_handle.seek(start)
            except Exception:
                pass
            self.plugin.log(f"Exception while reading message at offset {start}: {e}", level="error")
            return None

    def _process_message(self, msg_data: bytes) -> bool:
        """Process and publish a gossip message. Return False if processing should stop."""
        if not msg_data or len(msg_data) < 2:
            return True

        # Adding the length of the raw gossip as varint decode to the raw_hex
        msg_len = len(msg_data)
        msg_len_varint_encoded = varint_encode(msg_len)

        msg_type = get_message_type_by_bytes(msg_data)
        msg_name = GOSSIP_TYPE_NAMES.get(msg_type, f"UNKNOWN_{msg_type}")
        raw_hex = (msg_len_varint_encoded + msg_data).hex()

        metadata: PluginEventMetadata = {
            "type": msg_type,
            "name": msg_name,
            "timestamp": int(time.time()),
            "sender_node_id": self.sender_node_id,
            "length": len(msg_data) - 2,  # Subtract 2 Bytes message type
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
            return self._handle_ended_message()

        return True

    def _handle_ended_message(self) -> bool:
        """Handle the gossip_store_ended message by reopening the file."""
        self.plugin.log("Detected gossip_store_ended, reopening file", level="warn")
        if self.file_handle:
            self.file_handle.close()
            self.file_handle = None

        time.sleep(POLL_INTERVAL)  # Wait a bit for the new file to be ready
        return self._open_gossip_store()

    def _is_gossip_in_gossip_store(self) -> bool:
        # Check if there are messages beyond the version byte
        assert self.gossip_store_path is not None, "Attempted to check gossip store before path was initialized."

        if self.gossip_store_path.stat().st_size <= 1:
            self.plugin.log(
                f"No gossip messages in gossip_store file at {self.gossip_store_path}",
                level="warn",
            )
            return False
        return True

    def monitor_loop(self, start_at_byte: int) -> None:
        """Main monitoring loop that processes messages from the gossip store."""
        success_counter: int = 0

        #
        # === INITIALIZATION PHASE === (run only once)
        #

        self.plugin.log("Starting initialization...")
        header: Optional[Tuple[int, int, int, int]]
        while self.running and not self.initialized.is_set():
            if not self.gossip_store_path:
                self._resolve_gossip_store_path()
                if not self.gossip_store_path:
                    self.plugin.log(
                        "An error occured when resolving the gossip_store file path. Try restarting the plugin",
                        level="error",
                    )
                    self.running = False
                    return

            if not self.file_handle and not self._open_gossip_store():
                self.plugin.log(
                    "An error occured when opening the gossip_store. Try restarting the plugin", level="error"
                )
                self.running = False
                return

            # Keep retrying until gossip_store contains gossip messages
            while not self._is_gossip_in_gossip_store():
                self.plugin.log("Waiting for gossip to be added to gossip_store", level="info")
                time.sleep(POLL_INTERVAL)

            assert self.file_handle is not None, "File handle was not initialized before reading."

            if 1 < start_at_byte <= self.file_size:
                try:
                    self.plugin.log(f"Trying to seek to {start_at_byte} ...", level="info")
                    self.file_handle.seek(start_at_byte)

                    while True:
                        header = self._read_header()

                        if header:
                            # Found a valid header
                            self.file_handle.seek(
                                -HEADER_SIZE, 1
                            )  
                            # We need to go back the HEADER_SIZE bytes in our file
                            self.plugin.log(f"Valid header found at offset {self.file_handle.tell()}.", level="info")

                            # Initialization is complete here:
                            self.initialized.set()
                            self.plugin.log(
                                f"Initialization complete, start monitoring the {self.gossip_store_path} file at {self.file_handle.tell()}",
                                level="info",
                            )

                            break
                        else:
                            # No valid header, slide forward by 1 byte
                            self.plugin.log(
                                f"Could not parse header at offset {self.file_handle.tell()}, retrying ...",
                                level="info",
                            )

                        self.file_handle.seek(1, 1)

                        if self.file_handle.tell() >= self.file_size:
                            self.file_handle.seek(1)
                            self.plugin.log(
                                f"Reached end of {self.gossip_store_path}, seeking to 1 (full file publish).",
                                level="info",
                            )
                            break

                except Exception as e:
                    self.plugin.log(
                        f"Error seeking to byte {start_at_byte}: {e}. Retrying initialization.", level="error"
                    )

                    if self.file_handle:
                        self.file_handle.close()
                        self.file_handle = None
                        time.sleep(POLL_INTERVAL)
                        continue

            else:
                self.plugin.log(
                    f"Skipping seeking to `start-at-byte` due to value {start_at_byte} out of bounds [2, {self.file_size}]",
                    "info",
                )

                # Initialization is complete here:
                self.initialized.set()
                self.plugin.log(
                    f"Initialization complete, start monitoring the {self.gossip_store_path} file at {self.file_handle.tell()}",
                    level="info",
                )

        #
        # === LIVE MONITORING PHASE ===
        #
        while self.running:
            try:
                assert self.file_handle is not None, "File handle was not initialized before reading."

                header = self._read_header()
                if not header:
                    # Possibly EOF or invalid header -> sleep a bit and try again
                    time.sleep(POLL_INTERVAL)
                    continue

                flags, msg_len, crc, timestamp = header

                payload_data: Optional[bytes] = self._read_payload(msg_len)

                if not payload_data:
                    time.sleep(POLL_INTERVAL)
                    continue

                if not self._process_message(payload_data):
                    self.plugin.log("Could not process message", level="error")
                    break

                success_counter += 1

                if success_counter < 100 or success_counter % 1_000 == 0:
                    self.plugin.log(f"Successfully published {success_counter} messages.", level="info")
                    self.plugin.log(f"Current offset is {self.file_handle.tell()}", level="info")

            except Exception as e:
                self.plugin.log(f"Error in monitor loop: {e}", level="error")
                if self.file_handle:
                    self.file_handle.close()
                    self.file_handle = None
                    time.sleep(POLL_INTERVAL)

    # === Start of plugin ===

    def start(self, start_at_byte: int) -> None:
        """Start the monitoring thread."""
        self.running = True

        try:
            self.plugin.log("Publisher bound. Waiting 1 second for subscribers to connect...", level="info")
            time.sleep(1)

            self.monitor_thread = threading.Thread(target=self.monitor_loop, daemon=True, args=(start_at_byte,))
            self.monitor_thread.start()
            self.plugin.log("GossipPublisher monitoring thread started", level="info")

        except Exception as e:
            self.plugin.log(f"Failed to start monitoring thread: {e}", level="error")

        # Start monitor thread

    # === Stop of plugin ===

    def stop(self) -> None:
        """Stop the monitoring thread and clean up resources."""
        self.plugin.log("Initiating shutdown of gossip-publisher-zmq plugin", level="info")

        # Signal thread to stop
        self.running = False

        # Only join if called from another thread
        if self.monitor_thread and self.monitor_thread.is_alive() and threading.current_thread() != self.monitor_thread:
            self.monitor_thread.join(timeout=2.0)
            self.plugin.log("Monitor thread stopped", level="info")

        # Close file
        if self.file_handle:
            try:
                self.file_handle.close()
            except Exception as e:
                self.plugin.log(f"Error closing file handle: {e}", level="warn")
            self.file_handle = None

        # Close ZMQ
        try:
            self.zmq_socket.close(linger=0)
            self.zmq_context.term()
            self.plugin.log("ZMQ resources cleaned up", level="info")
        except Exception as e:
            self.plugin.log(f"Error cleaning ZMQ resources: {e}", level="warn")


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

plugin.add_option("zmq-port", "5675", "Port to bind ZMQ PUB socket", "int")
plugin.add_option("zmq-host", "127.0.0.1", "Host to bind ZMQ PUB socket")
plugin.add_option("sender-node-id", "", "Optional override for sender_node_id")
plugin.add_option("start-at-byte", 0, "Byte offset to start reading the gossip_store file from.", "int")


@plugin.init()
def init(options: Dict[str, Any], configuration: Dict[str, Any], plugin: Plugin) -> None:
    """Initialize the plugin."""
    plugin.log("Gossip ZMQ Publisher initializing", level="info")

    # Get configuration
    zmq_port: int = int(plugin.get_option("zmq-port") or DEFAULT_ZMQ_PORT)
    zmq_host: str = plugin.get_option("zmq-host") or DEFAULT_ZMQ_HOST
    sender_node_id: str = plugin.get_option("sender-node-id") or str(resolve_sender_node_id(plugin))
    start_byte: int = plugin.get_option("start-at-byte") or START_AT_BYTE or 1

    zmq_endpoint = f"tcp://{zmq_host}:{zmq_port}"

    # Create and start the gossip publisher
    plugin.gossip_monitor = GossipPublisher(plugin, zmq_endpoint, sender_node_id)
    plugin.gossip_monitor.setup_zmq()
    plugin.gossip_monitor.start(start_byte)

    plugin.log(f"Gossip ZMQ Publisher started, publishing to {zmq_endpoint}", level="info")
    plugin.log("Use `lightning-cli gpz-status` to get a status update of the plugin.", level="info")
    plugin.log(
        "Use `lightning-cli -k plugin subcommand=start plugin=<path-to-plugin> <option-name>=<value>` to configure the plugin.",
        level="info",
    )


@plugin.method("gpz-status")
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
        "offset_of_gossip_store": (
            gossip_publisher.file_handle.tell()
            if gossip_publisher.file_handle
            else "Missing file_handle to gossip_store -> Does the gossip_store file exist?"
        ),
        "initialized": (
            gossip_publisher.initialized.is_set()
            if gossip_publisher.initialized
            else "Initialization thread does not exist -> Try restarting the plugin."
        ),
    }


if __name__ == "__main__":
    plugin.run()
