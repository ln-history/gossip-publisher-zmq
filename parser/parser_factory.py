from typing import Callable, Dict

from . import channel_announcement_parser
from . import channel_update_parser
from . import node_announcement_parser

from .internal import channel_amount_parser
from .internal import private_channel_announcement_parser
from .internal import private_channel_update_parser
from .internal import delete_channel_parser
from .internal import gossip_store_ended_parser
from .internal import channel_dying_parser

# Define a mapping from topic names to parser functions
PARSER_MAP: Dict[str, Callable[[bytes], object]] = {
    "channel_announcement": channel_announcement_parser.parse,
    "channel_update": channel_update_parser.parse,
    "node_announcement": node_announcement_parser.parse,
    "channel_amount": channel_amount_parser.parse,
    "gossip_store_private_channel": private_channel_announcement_parser.parse,
    "gossip_store_private_update": private_channel_update_parser.parse,
    "delete_channel": delete_channel_parser.parse,
    "gossip_store_ended": gossip_store_ended_parser.parse,
    "channel_dying": channel_dying_parser.parse
}

def get_parser(message_type: str) -> Callable[[bytes], object]:
    """
    Returns the parser function for the given message type.

    Raises:
        ValueError: if the message type is not supported.
    """
    try:
        return PARSER_MAP[message_type]
    except KeyError:
        raise ValueError(f"No parser found for message type: '{message_type}'")
