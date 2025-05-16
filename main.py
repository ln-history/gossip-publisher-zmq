#!/Users/fabiankraus/Programming/lightning/custom-plugins/gossip-publisher-zmq/.venv/bin/python
"""
Gossip-Publisher-ZMQ
A Core Lightning Plugin to publish collected gossip via ZeroMQ

This plugin monitors the Core Lightning gossip_store file and 
forwards all gossip messages to a ZeroMQ PUB socket.
"""

import os
import time
import json
import struct
import threading
from pathlib import Path
from typing import Dict, Any, Optional, Tuple

import zmq
from pyln.client import Plugin

from parser.parser_factory import get_parser

# Message types as defined in BOLT #7
MSG_TYPE_CHANNEL_ANNOUNCEMENT = 256
MSG_TYPE_NODE_ANNOUNCEMENT = 257
MSG_TYPE_CHANNEL_UPDATE = 258

# Internal Core Lightning gossip message types
MSG_TYPE_CHANNEL_AMOUNT = 4101
MSG_TYPE_PRIVATE_UPDATE = 4102
MSG_TYPE_DELETE_CHAN = 4103
MSG_TYPE_PRIVATE_CHANNEL = 4104
MSG_TYPE_ENDED = 4105
MSG_TYPE_CHAN_DYING = 4106

# Flag constants
FLAG_DELETED = 0x8000
FLAG_PUSH = 0x4000
FLAG_DYING = 0x0800

# Header format
HEADER_FORMAT = ">HHII"  # flags(2) + len(2) + crc(4) + timestamp(4)
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)

plugin = Plugin()

class GossipMonitor:
    def __init__(self, plugin, zmq_endpoint: str):
        self.plugin = plugin
        self.zmq_endpoint = zmq_endpoint
        self.zmq_context = zmq.Context()
        self.zmq_socket = self.zmq_context.socket(zmq.PUB)
        self.running = False
        self.gossip_store_path = None
        self.current_offset = 0
        self.file_handle = None
        self.monitor_thread = None
    
    def setup_zmq(self):
        try:
            self.zmq_socket.bind(self.zmq_endpoint)
            self.plugin.log(f"ZMQ publisher bound to {self.zmq_endpoint}")
        except zmq.error.ZMQError as e:
            self.plugin.log(f"Error binding ZMQ socket: {e}", level="error")
            raise
    
    def start(self):
        self.running = True
        self.monitor_thread = threading.Thread(target=self.monitor_loop)
        self.monitor_thread.daemon = True
        self.monitor_thread.start()
    
    def stop(self):
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
            self.file_handle = open(self.gossip_store_path, 'rb')
            
            # Read and verify version
            version_byte = self.file_handle.read(1)
            if not version_byte:
                self.plugin.log("Empty gossip_store file", level="warn")
                return False
            
            version = version_byte[0]
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
        """Read the message body."""
        try:
            message_data = self.file_handle.read(msg_len)
            if len(message_data) < msg_len:
                return None
            
            self.current_offset += msg_len
            return message_data
        except Exception as e:
            self.plugin.log(f"Error reading message: {e}", level="debug")
            return None
    
    def process_message(self, flags: int, msg_data: bytes, timestamp: int):
        """Process and forward a gossip message."""
        if not msg_data or len(msg_data) < 2:
            return
        
        # Extract message type (big-endian 16-bit integer)
        msg_type = struct.unpack(">H", msg_data[:2])[0]
        
        # Skip deleted messages
        if flags & FLAG_DELETED:
            return
        
        # Create message info object
        msg_info = {
            "type": msg_type,
            "flags": flags,
            "timestamp": timestamp,
            "is_push": bool(flags & FLAG_PUSH),
            "is_dying": bool(flags & FLAG_DYING),
            "length": len(msg_data) - 2  # Exclude the type field
        }
        
        # Add message-specific data
        if msg_type == MSG_TYPE_CHANNEL_ANNOUNCEMENT:
            msg_info["name"] = "channel_announcement"
        elif msg_type == MSG_TYPE_NODE_ANNOUNCEMENT:
            msg_info["name"] = "node_announcement"
        elif msg_type == MSG_TYPE_CHANNEL_UPDATE:
            msg_info["name"] = "channel_update"
        elif msg_type == MSG_TYPE_CHANNEL_AMOUNT:
            msg_info["name"] = "channel_amount"
            if len(msg_data) >= 10:  # 2 bytes type + 8 bytes amount
                satoshis = struct.unpack(">Q", msg_data[2:10])[0]
                msg_info["satoshis"] = satoshis
        elif msg_type == MSG_TYPE_PRIVATE_UPDATE:
            msg_info["name"] = "private_update"
        elif msg_type == MSG_TYPE_DELETE_CHAN:
            msg_info["name"] = "delete_channel"
            if len(msg_data) >= 10:  # 2 bytes type + 8 bytes scid
                scid = struct.unpack(">Q", msg_data[2:10])[0]
                msg_info["scid"] = scid
        elif msg_type == MSG_TYPE_PRIVATE_CHANNEL:
            msg_info["name"] = "private_channel"
        elif msg_type == MSG_TYPE_ENDED:
            msg_info["name"] = "store_ended"
            if len(msg_data) >= 10:  # 2 bytes type + 8 bytes offset
                offset = struct.unpack(">Q", msg_data[2:10])[0]
                msg_info["equivalent_offset"] = offset
        elif msg_type == MSG_TYPE_CHAN_DYING:
            msg_info["name"] = "channel_dying"
            if len(msg_data) >= 14:  # 2 bytes type + 8 bytes scid + 4 bytes blockheight
                scid = struct.unpack(">Q", msg_data[2:10])[0]
                blockheight = struct.unpack(">I", msg_data[10:14])[0]
                msg_info["scid"] = scid
                msg_info["blockheight"] = blockheight
        else:
            msg_info["name"] = f"unknown_{msg_type}"
        
        # Send message type as topic and full message data + metadata
        try:
            # Topic is the message type name
            self.zmq_socket.send_string(msg_info["name"], zmq.SNDMORE)
                
            # Use the appropriate parser
            parsed_dict = None
            parser = get_parser(msg_info["name"])
            if parser:
                self.plugin.log(f"Using parser {parser}", level="debug")
                try:
                    parsed_payload = parser(msg_data[2:])  # skip 2-byte message type
                    parsed_dict = parsed_payload.to_dict()
                except Exception as parse_error:
                    self.plugin.log(f"Error parsing {msg_info['name']} payload: {parse_error}", level="error")

            payload = {
                "metadata": msg_info,
                "raw_hex": msg_data.hex(),
                "parsed": parsed_dict  # parsed can be None if no parser or error
            }

            self.zmq_socket.send_json(payload)
            
            self.plugin.log(f"Published {msg_info['name']} message", level="debug")
        except Exception as e:
            self.plugin.log(f"Error publishing message: {e}", level="error")
    
    def handle_ended_message(self):
        """Handle the gossip_store_ended message by reopening the file."""
        self.plugin.log("Detected gossip_store_ended, reopening file", level="info")
        if self.file_handle:
            self.file_handle.close()
            self.file_handle = None
        
        time.sleep(1)  # Wait a bit for the new file to be ready
        return self.open_gossip_store()
    
    def monitor_loop(self):
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
                    
                    # Process the message
                    self.process_message(flags, msg_data, timestamp)
                    
                    # If this is a "store_ended" message, reopen the file
                    if len(msg_data) >= 2:
                        msg_type = struct.unpack(">H", msg_data[:2])[0]
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


@plugin.init()
def init(options, configuration, plugin):
    plugin.log("Gossip ZMQ Publisher initializing")
    
    # Manually retrieve the ZMQ endpoint from options or use the default
    zmq_endpoint = options.get("gossip-zmq-endpoint", "tcp://127.0.0.1:5675")
    
    # Create and start the gossip monitor
    plugin.gossip_monitor = GossipMonitor(plugin, zmq_endpoint)
    plugin.gossip_monitor.setup_zmq()
    plugin.gossip_monitor.start()
    
    plugin.log(f"Gossip ZMQ Publisher started, publishing to {zmq_endpoint}")


@plugin.method("status")
def status():
    """Return status information about the gossip ZMQ publisher."""
    return {
        "running": plugin.gossip_monitor.running if hasattr(plugin, "gossip_monitor") else False,
        "zmq_endpoint": plugin.gossip_monitor.zmq_endpoint if hasattr(plugin, "gossip_monitor") else None,
        "gossip_store_path": str(plugin.gossip_monitor.gossip_store_path) if hasattr(plugin, "gossip_monitor") and plugin.gossip_monitor else None
    }


# Run the plugin
if __name__ == "__main__":
    plugin.run()