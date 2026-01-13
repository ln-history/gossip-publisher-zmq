#!/usr/bin/env python3

"""
gossip-publisher-zmq is a Core Lightning Plugin to publish collected gossip messages via ZeroMQ

This plugin monitors the Core Lightning gossip_store file, parses all gossip messages into a human readable format 
and forwards the result to a ZeroMQ PUB socket.
"""

import errno
import json
import struct
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, BinaryIO, Optional, Tuple, Union

import zmq
from crc32c import crc32c
from lnhistoryclient.constants import (
    CORE_LIGHTNING_TYPES, GOSSIP_TYPE_NAMES, HEADER_FORMAT, 
    LIGHTNING_TYPES, MSG_TYPE_GOSSIP_STORE_ENDED, MSG_TYPE_DELETE_CHANNEL
)
from lnhistoryclient.model.types import ParsedGossipDict, PluginEvent, PluginEventMetadata
from lnhistoryclient.model.core_lightning_internal.types import ParsedCoreLightningGossipDict, PluginCoreLightningEvent
from lnhistoryclient.model.core_lightning_internal.GossipStoreEnded import GossipStoreEndedDict
from lnhistoryclient.parser import parser_factory
from lnhistoryclient.parser.core_lightning_internal.parser import parse_delete_channel 
from lnhistoryclient.parser.common import get_message_type_by_bytes, strip_known_message_type, varint_encode
from pyln.client import Plugin

from config import DEFAULT_SENDER_NODE_ID, DEFAULT_ZMQ_HOST, DEFAULT_ZMQ_PORT, POLL_INTERVAL, START_AT_BYTE

HEADER_SIZE = struct.calcsize(HEADER_FORMAT)


class GossipPublisher:
    """Monitors the gossip_store file and publishes messages to ZMQ."""

    def __init__(self, plugin: Plugin, zmq_endpoint: str, sender_node_id: str) -> None:
        self.plugin = plugin
        self.zmq_endpoint = zmq_endpoint
        self.sender_node_id = sender_node_id
        
        # ZeroMQ setup
        self.zmq_context = zmq.Context()
        self.zmq_socket = self.zmq_context.socket(zmq.PUB)
        self.zmq_socket.setsockopt(zmq.LINGER, 1000)
        
        # File handling
        self.gossip_store_path: Optional[Path] = None
        self.file_handle: Optional[BinaryIO] = None
        
        # Monitoring
        self.running = False
        self.monitor_thread: Optional[threading.Thread] = None
        
        # Performance data
        self.last_100_messages = deque(maxlen=100)

    def setup_zmq(self) -> None:
        """Bind the ZMQ socket to the specified endpoint."""
        try:
            self.zmq_socket.bind(self.zmq_endpoint)
            self.plugin.log(f"ZMQ publisher bound to {self.zmq_endpoint}")
        except zmq.error.ZMQError as e:
            msg = f"ZMQ address already in use: {self.zmq_endpoint}. Is another instance running?" if e.errno == errno.EADDRINUSE else f"Error binding ZMQ socket: {e}"
            self.plugin.log(msg, level="error")
            self.stop()

    def _publish_to_zmq(self, topic: str, payload: Union[ParsedGossipDict, ParsedCoreLightningGossipDict]) -> None:
        """Publish a message to the ZMQ socket."""
        try:
            self.zmq_socket.send_string(topic, zmq.SNDMORE)
            self.zmq_socket.send_string(json.dumps(payload))
        except Exception as e:
            self.plugin.log(f"Error publishing message: {e}", level="error")

    def _parse_gossip(self, msg_type: int, msg_name: str, raw_hex: str) -> Optional[Union[ParsedGossipDict, ParsedCoreLightningGossipDict]]:
        """Parse a message using lnhistoryclient parser."""
        try:
            if msg_type == MSG_TYPE_DELETE_CHANNEL:
                payload_bytes = bytes.fromhex(raw_hex)
                
                parsed_obj = parse_delete_channel(payload_bytes)
                
                return parsed_obj.to_dict()

            parser_fn = parser_factory.get_parser_by_message_type(msg_type)
            if not parser_fn:
                self.plugin.log(f"No parser function found for msg_type: {msg_type}", level="debug")
                return None
            
            parsed = parser_fn(bytes.fromhex(raw_hex))
            return parsed.to_dict() if hasattr(parsed, "to_dict") else vars(parsed)
        except Exception as e:
            self.plugin.log(f"Error parsing {msg_name} payload: {e}", level="error")
            self.plugin.log(f"Message payload in hex: {raw_hex[:1000]}... at offset {self.file_handle.tell()}", level="error")
            return None

    def _resolve_gossip_store_path(self) -> None:
        """Determine the path to the gossip_store file."""
        try:
            info = self.plugin.rpc.getinfo()
            self.gossip_store_path = Path(info["lightning-dir"]) / "gossip_store"
            self.plugin.log(f"Resolved gossip store path: {self.gossip_store_path}")
        except Exception as e:
            self.plugin.log(f"Failed to resolve gossip store path: {e}", level="error")

    def _open_gossip_store(self) -> bool:
        """Open the gossip_store file and validate version."""
        try:
            if not self.gossip_store_path or not self.gossip_store_path.exists():
                self.plugin.log("Gossip store file does not exist", level="error")
                return False

            self.file_handle = open(self.gossip_store_path, "rb")
            
            # Version check is mandatory at byte 0
            self.file_handle.seek(0)
            version_byte = self.file_handle.read(1)
            
            if not version_byte:
                self.plugin.log("Failed to read gossip_store version byte (empty file?)", level="error")
                return False

            version = version_byte[0]
            major_version = (version >> 5) & 0x07
            
            if major_version != 0:
                self.plugin.log(f"Unsupported gossip_store major version: {major_version}", level="error")
                return False
                
            return True

        except Exception as e:
            self.plugin.log(f"Error opening gossip_store: {e}", level="error")
            if self.file_handle:
                self.file_handle.close()
                self.file_handle = None
            return False

    def _read_header(self) -> Optional[Tuple[int, int, int, int]]:
        """Read and parse gossip_store header with CRC validation."""
        if not self.file_handle:
            return None

        try:
            start = self.file_handle.tell()
            header_data = self.file_handle.read(HEADER_SIZE)
            
            if len(header_data) < HEADER_SIZE:
                self.file_handle.seek(start) 
                return None

            flags, msg_len, crc, timestamp = struct.unpack(HEADER_FORMAT, header_data)
            
            # Sanity check
            if msg_len > 10 * 1024 * 1024: 
                self.plugin.log(f"Insane message length detected: {msg_len} at offset {start}", level="warn")
                return None

            payload = self.file_handle.read(msg_len)

            if len(payload) < msg_len:
                self.file_handle.seek(start)
                return None

            computed_crc = crc32c(payload, timestamp) & 0xFFFFFFFF
            if computed_crc != crc:
                self.plugin.log(f"CRC mismatch at offset {start}: expected {crc}, got {computed_crc}", level="warn")
                return None

            return flags, msg_len, crc, timestamp

        except Exception as e:
            self.plugin.log(f"Exception while reading header: {e}", level="error")
            return None

    def monitor_loop(self, start_at_byte: int) -> None:
        """Main monitoring loop."""
        
        # === SEEKING PHASE ===
        try:
            if start_at_byte == -1:
                self.file_handle.seek(0, 2)
                self.plugin.log(f"Seeked to END of gossip_store at offset {self.file_handle.tell()}")
            elif start_at_byte > 1:
                self.file_handle.seek(start_at_byte)
                self.plugin.log(f"Seeked to offset {start_at_byte}")
            else:
                self.file_handle.seek(1)
                self.plugin.log("Starting from beginning of gossip_store")

        except Exception as e:
            self.plugin.log(f"Error seeking file: {e}", level="error")
            return

        success_counter = 0

        # === LIVE MONITORING PHASE ===
        while self.running:
            try:
                time.sleep(0.01)

                header = self._read_header()
                
                if not header:
                    time.sleep(POLL_INTERVAL)
                    continue

                flags, msg_len, crc, timestamp = header

                # 0x8000 = GOSSIP_STORE_DELETED_BIT
                # If deleted, we are already at the end of the message (because _read_header read it).
                # We simply skip processing.
                if flags & 0x8000:
                    continue
                
                # Rewind to read payload again (safest approach)
                # Since _read_header consumed the payload, we go back to read it for parsing.
                self.file_handle.seek(-msg_len, 1)

                payload_data = self.file_handle.read(msg_len)
                
                if len(payload_data) != msg_len:
                    self.plugin.log(f"Sync lost. Expected {msg_len} bytes, got {len(payload_data)}", level="error")
                    
                    # Stop completely (let Watchdog restart us)
                    self.running = False
                    return

                msg_type = get_message_type_by_bytes(payload_data)
                
                if msg_type in LIGHTNING_TYPES or msg_type in CORE_LIGHTNING_TYPES:
                    msg_name = GOSSIP_TYPE_NAMES.get(msg_type, f"UNKNOWN_{msg_type}")
                    raw_hex = (varint_encode(msg_len) + payload_data).hex()
                    parsed = self._parse_gossip(msg_type, msg_name, strip_known_message_type(payload_data).hex())

                    if parsed:
                        metadata: PluginEventMetadata = {
                            "type": msg_type,
                            "name": msg_name,
                            "timestamp": int(time.time()),
                            "sender_node_id": self.sender_node_id,
                            "length": len(payload_data),
                        }
                        
                        payload: Union[PluginEvent, PluginCoreLightningEvent] = {
                            "metadata": metadata,
                            "raw_hex": raw_hex,
                            "parsed": parsed,
                        }
                        self._publish_to_zmq(msg_name, payload)
                        
                        self.last_100_messages.append({
                            "type": msg_type,
                            "timestamp": time.time(),
                            "payload": parsed
                        })
                        success_counter += 1

                if success_counter > 0 and success_counter % 5000 == 0:
                    self.plugin.log(f"Processed {success_counter} messages. Current offset: {self.file_handle.tell()}")

                # Handle Gossip Store Rotation
                if msg_type == MSG_TYPE_GOSSIP_STORE_ENDED:
                    self.plugin.log("Gossip store ended. Handling rotation...", level="warn")
                    
                    stripped_hex = strip_known_message_type(payload_data).hex()
                    parsed_result: GossipStoreEndedDict = self._parse_gossip(msg_type, msg_name, stripped_hex)
                    
                    # Extract the offset safely
                    equivalent_offset = 1
                    if parsed_result and "equivalent_offset" in parsed_result:
                        equivalent_offset = parsed_result["equivalent_offset"]
                        self.plugin.log(f"Next store file starts equivalent at offset: {equivalent_offset}")
                    else:
                        self.plugin.log("Could not parse equivalent_offset. Defaulting to 1 (Re-reading all).", level="warn")

                    # Close the old file handle
                    self.file_handle.close()
                    self.file_handle = None
                    
                    # Retry loop to open the new file (Wait for Core-Lightning to perform the swap)
                    max_retries = 10
                    for i in range(max_retries):
                        time.sleep(10*POLL_INTERVAL) 
                        if self._open_gossip_store():
                            break
                        self.plugin.log(f"Waiting for new gossip_store... ({i+1}/{max_retries})")
                    
                    if not self.file_handle:
                        self.plugin.log("Critical: Could not open new gossip_store after rotation.", level="error")
                        self.running = False
                        return

                    # Seek to the calculated offset
                    try:
                        seek_target = max(1, equivalent_offset)
                        self.file_handle.seek(seek_target)
                        self.plugin.log(f"Resumed reading new store at offset {seek_target}")
                    except Exception as e:
                        self.plugin.log(f"Seek failed: {e}. Resetting to start.", level="error")
                        self.file_handle.seek(1)

            except Exception as e:
                self.plugin.log(f"CRITICAL PLUGIN ERROR: {e}", level="error")
                self.plugin.log(f"Restarting monitor loop in {POLL_INTERVAL} seconds...", level="error")
                time.sleep(POLL_INTERVAL)

    def start(self, start_at_byte: int) -> None:
        """Start the monitoring thread."""
        self.running = True
        try:
            if not self.gossip_store_path:
                self._resolve_gossip_store_path()

            if not self._open_gossip_store():
                self.plugin.log("Critical: Could not open gossip store.", level="error")
                self.stop()
                return

            # === VALIDATION LOGIC ===
            if start_at_byte > 1:
                self.plugin.log(f"Validating start offset {start_at_byte}...")
                try:
                    self.file_handle.seek(start_at_byte)
                    if not self._read_header():
                        self.plugin.log(f"Invalid start-at-byte {start_at_byte}: Could not read valid header. Defaulting to LIVE mode (-1).", level="error")
                        start_at_byte = -1
                    else:
                        self.plugin.log(f"Offset {start_at_byte} is valid.")
                        # Rewind is handled by monitor_loop seeking again, or we can just leave it. 
                        # To be safe and cleaner, we reset here or let monitor_loop handle it.
                        # Since monitor_loop calls seek(), passing the valid start_at_byte is enough.
                except Exception as e:
                    self.plugin.log(f"Error during validation of offset {start_at_byte}: {e}. Defaulting to LIVE mode (-1).", level="error")
                    start_at_byte = -1

            self.monitor_thread = threading.Thread(target=self.monitor_loop, daemon=True, args=(start_at_byte,))
            self.monitor_thread.start()
            self.plugin.log("GossipPublisher monitoring thread started")
        except Exception as e:
            self.plugin.log(f"Failed to start monitoring thread: {e}", level="error")

    def stop(self) -> None:
        """Stop the monitoring thread."""
        self.running = False
        if self.file_handle:
            self.file_handle.close()
        self.zmq_context.term()


def resolve_sender_node_id(plugin: Plugin) -> Optional[str]:
    """Attempt to get sender_node_id from RPC, fallback to env variable."""
    try:
        info = plugin.rpc.call("getinfo")
        sender_node_id = str(info["id"])
        plugin.log(f"Retrieved node_id via getinfo: {sender_node_id}")
        return sender_node_id
    except Exception as e:
        plugin.log(f"Failed to retrieve node_id from getinfo: {e}", level="warn")

    fallback_node_id = DEFAULT_SENDER_NODE_ID
    if fallback_node_id:
        plugin.log(f"Using DEFAULT_SENDER_NODE_ID from environment: {fallback_node_id}")
    else:
        plugin.log("No DEFAULT_SENDER_NODE_ID found via RPC or environment", level="warn")

    return fallback_node_id or None


# Initialize plugin
plugin = Plugin()

plugin.add_option("zmq-port", "5675", "Port to bind ZMQ PUB socket", "int")
plugin.add_option("zmq-host", "127.0.0.1", "Host to bind ZMQ PUB socket")
plugin.add_option("sender-node-id", "", "Optional override for sender_node_id")
plugin.add_option("start-at-byte", -1, "Byte offset. -1 = Live (End), 0 or 1 = Replay All.", "int")


@plugin.init()
def init(options: dict[str, Any], configuration: dict[str, Any], plugin: Plugin) -> None:
    """Initialize the plugin."""
    plugin.log("Gossip ZMQ Publisher initializing")

    zmq_port = int(plugin.get_option("zmq-port") or DEFAULT_ZMQ_PORT)
    zmq_host = plugin.get_option("zmq-host") or DEFAULT_ZMQ_HOST
    sender_node_id = plugin.get_option("sender-node-id") or str(resolve_sender_node_id(plugin))
    start_byte = plugin.get_option("start-at-byte") or START_AT_BYTE or 1

    zmq_endpoint = f"tcp://{zmq_host}:{zmq_port}"

    plugin.gossip_monitor = GossipPublisher(plugin, zmq_endpoint, sender_node_id)
    plugin.gossip_monitor.setup_zmq()
    plugin.gossip_monitor.start(start_byte)

    plugin.log(f"Gossip ZMQ Publisher started, publishing to {zmq_endpoint}")
    plugin.log("Use `lightning-cli gpz-status` to get a status update of the plugin.")
    plugin.log("Use `lightning-cli last-msgs` to get a list of the last 100 parsed gossip messages")
    plugin.log("Use `lightning-cli -k plugin subcommand=start plugin=<path-to-plugin> <option-name>=<value>` to configure the plugin.")


@plugin.method("gpz-status")
def status() -> dict[str, Any]:
    """Return status information about the gossip ZMQ publisher."""
    gossip_monitor = getattr(plugin, "gossip_monitor", None)

    return {
        "running": gossip_monitor.running if gossip_monitor else False,
        "zmq_endpoint": gossip_monitor.zmq_endpoint if gossip_monitor else None,
        "sender_node_id": gossip_monitor.sender_node_id if gossip_monitor else None,
        "gossip_store_path": str(gossip_monitor.gossip_store_path) if gossip_monitor and gossip_monitor.gossip_store_path else None,
        "offset_of_gossip_store": str(gossip_monitor.file_handle.tell()) if gossip_monitor and gossip_monitor.file_handle else 0,
        "last_10_processed_messages": list(gossip_monitor.last_100_messages)[:10] if gossip_monitor else [],
    }

@plugin.method("gpz-is-running")
def is_running() -> bool:
    """Returns true if the gossip monitor is active, false otherwise."""
    gossip_monitor = getattr(plugin, "gossip_monitor", None)
    return gossip_monitor.running if gossip_monitor else False

@plugin.method("gpz-last-msgs")
def get_last_messages() -> list[dict[str, Any]]:
    """Return the last 100 processed messages."""
    gossip_monitor = getattr(plugin, "gossip_monitor", None)
    return list(gossip_monitor.last_100_messages) if gossip_monitor else []


if __name__ == "__main__":
    plugin.run()