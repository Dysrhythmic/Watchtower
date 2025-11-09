"""
Discover - For the "discover" subcommand

This module provides functionality for assisting in configuring Telegram
channels since many live and die so quickly.

Features:
- List all accessible Telegram channels, groups, etc.
- Compare discovered channels with existing config (--diff mode)
- Auto-generate config file from discovered channels (--generate flag)

Subcommand Usage:
    python3 src/Watchtower.py discover
        List all accessible channels

    python3 src/Watchtower.py discover -h
        Display help menu

    python3 src/Watchtower.py discover --diff
        Show channels not in existing config and vice versa

    python3 src/Watchtower.py discover --generate
        Generate config_discovered.json file

    python3 src/Watchtower.py discover --diff --generate
        Show diff and generate config file
"""
import json
from pathlib import Path
from LoggerSetup import setup_logger
from AppTypes import APP_TYPE_DISCORD

_logger = setup_logger(__name__)


def _get_entity_type_and_name(telegram_entity):
    """Extract entity type and name from Telegram entity.

    Used by discover subcommand to categorize Telegram entities.

    Args:
        telegram_entity: Telethon entity (Channel, Chat, or User)

    Returns:
        tuple[str, str]: (entity_type, entity_name)
            entity_type: "Channel", "Supergroup", "Group", "Bot", or "User"
            entity_name: Display name (title, username, or full name)
    """
    from telethon.tl.types import Channel, Chat, User

    entity_type = "Unknown"
    entity_name = "Unknown"

    if isinstance(telegram_entity, Channel):
        if telegram_entity.broadcast:
            entity_type = "Channel"
        elif telegram_entity.megagroup:
            entity_type = "Supergroup"
        else:
            entity_type = "Group"
        entity_name = telegram_entity.title
    elif isinstance(telegram_entity, Chat):
        entity_type = "Group"
        entity_name = telegram_entity.title
    elif isinstance(telegram_entity, User):
        if telegram_entity.bot:
            entity_type = "Bot"
        else:
            entity_type = "User"

        if telegram_entity.username:
            entity_name = f"@{telegram_entity.username}"
        elif telegram_entity.first_name:
            entity_name = telegram_entity.first_name
            if telegram_entity.last_name:
                entity_name += f" {telegram_entity.last_name}"
        else:
            entity_name = f"User{telegram_entity.id}"

    return entity_type, entity_name


def _get_channel_identifier(telegram_entity, dialog_id):
    """Get channel identifier (username or numeric ID).

    Used by discover subcommand to generate config entries.

    Args:
        telegram_entity: Telethon entity
        dialog_id: Numeric dialog ID from Telegram

    Returns:
        str: "@username" if available, otherwise numeric ID
    """
    if hasattr(telegram_entity, 'username') and telegram_entity.username:
        return f"@{telegram_entity.username}"
    return str(dialog_id)


def _load_existing_config(config_dir: Path, config_filename='config.json'):
    """Load existing config and return set of channel IDs.

    Used by discover --diff to compare discovered channels with existing config.

    Args:
        config_dir: Path to config directory
        config_filename: Name of config file (defaults to 'config.json')

    Returns:
        tuple: (existing_channel_ids set, existing_channel_details dict)
               Returns (None, None) on error
    """
    config_path = config_dir / config_filename

    if not config_path.exists():
        _logger.info(f"[Discover] No existing config found at {config_path}")
        return set(), {}

    _logger.info(f"[Discover] Loading existing config: {config_path}")
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            existing_config = json.load(f)

        existing_channel_ids = set()
        existing_channel_details = {}

        destination_list = existing_config.get('destinations', [])

        for destination in destination_list:
            for channel in destination.get('channels', []):
                ch_id = channel.get('id')
                if ch_id and not ch_id.startswith('http'):
                    existing_channel_ids.add(ch_id)
                    existing_channel_details[ch_id] = ch_id

        _logger.info(f"[Discover] Found {len(existing_channel_ids)} existing channels in config")
        return existing_channel_ids, existing_channel_details
    except Exception as e:
        _logger.error(f"[Discover] Error loading config: {e}")
        return None, None


def _calculate_diff(channels, existing_channel_ids):
    """Calculate new and removed channels.

    Compares discovered channels with existing config to identify changes.

    Args:
        channels: List of discovered channel dicts
        existing_channel_ids: Set of channel IDs from existing config

    Returns:
        tuple: (new_channels list, removed_channel_ids set)
    """
    discovered_ids = set(ch['info']['id'] for ch in channels)
    new_channels = [ch for ch in channels if ch['info']['id'] not in existing_channel_ids]
    removed_channel_ids = existing_channel_ids - discovered_ids
    return new_channels, removed_channel_ids


def _print_diff_output(new_channels, removed_channel_ids, existing_channel_ids, all_channels):
    """Print diff mode output showing configuration changes.

    Displays formatted diff showing new and removed channels with summary statistics.
    """
    has_changes = len(new_channels) > 0 or len(removed_channel_ids) > 0

    if not has_changes:
        _logger.info("")
        _logger.info("=" * 70)
        _logger.info("NO CHANGES DETECTED")
        _logger.info("=" * 70)
        _logger.info(f"  All {len(existing_channel_ids)} configured channels are accessible.")
        _logger.info(f"  No new channels discovered.")
        _logger.info("=" * 70)
        _logger.info("")
        return False

    _logger.info("")
    _logger.info("=" * 70)
    _logger.info("CONFIGURATION DIFF")
    _logger.info("=" * 70)

    if removed_channel_ids:
        _logger.info("")
        _logger.info("Removed/Inaccessible (in config but not accessible):")
        for ch_id in sorted(removed_channel_ids):
            _logger.info(f"  - {ch_id}")

    if new_channels:
        _logger.info("")
        _logger.info("New Channels (accessible but not in config):")
        for ch in new_channels:
            _logger.info(f"  + {ch['name']:40} [{ch['type']:10}] {ch['info']['id']}")

    type_counts = {}
    for ch in new_channels:
        entity_type = ch.get('type', 'Unknown')
        type_counts[entity_type] = type_counts.get(entity_type, 0) + 1

    _logger.info("")
    _logger.info("=" * 70)
    _logger.info("SUMMARY")
    _logger.info("=" * 70)
    _logger.info(f"  In config: {len(existing_channel_ids):3}  |  Discovered: {len(all_channels):3}  |  New (+): {len(new_channels):3}  |  Removed (-): {len(removed_channel_ids):3}")

    if new_channels:
        type_summary = ", ".join([f"{et}s: {count}" for et, count in sorted(type_counts.items())])
        _logger.info(f"  New by type: {type_summary}")

    _logger.info("=" * 70)
    _logger.info("")
    return True


def _save_discovered_config(channels, config_dir: Path):
    """Save discovered channels to config file.

    Generates a config with the new 'destinations' format.
    To configure Telegram as a destination, change:
    - type: "discord" -> "telegram"
    - env_key: Use an env variable containing the Telegram channel ID (e.g., "@channel" or "-1001234567890")
    """
    config = {
        "destinations": [
            {
                "name": "Auto-Generated Feed",
                "type": APP_TYPE_DISCORD,
                "env_key": "DISCORD_WEBHOOK_URL",
                "channels": [ch["info"] for ch in channels]
            }
        ]
    }

    config_path = config_dir / "config_discovered.json"
    with open(config_path, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

    _logger.info(f"[Discover] Configuration saved to {config_path}")
    _logger.info(f"[Discover] Note: To send to Telegram instead, change type to 'telegram' and set env_key to a Telegram channel ID")


async def discover_channels(diff_mode=False, generate_config=False):
    """Discover all accessible Telegram channels and optionally generate a config file.

    Args:
        diff_mode: If True, show only new channels not in existing config
        generate_config: If True, generate config_discovered.json file
    """
    from telethon import TelegramClient
    from telethon.tl.types import Channel, Chat, User
    from ConfigManager import ConfigManager

    # Use ConfigManager in minimal mode to access env vars and paths
    # This allows discover to work even if the JSON config isn't generated yet
    config = ConfigManager(load_full_config=False)
    config_dir = config.config_dir
    api_id = config.api_id
    api_hash = config.api_hash
    config_filename = config.config_file

    if not api_id or not api_hash:
        _logger.error("[Discover] Missing TELEGRAM_API_ID or TELEGRAM_API_HASH in .env file")
        return

    _logger.info("[Discover] Connecting to Telegram...")
    session_path = str(config_dir / "watchtower_session.session")
    client = TelegramClient(session_path, api_id, api_hash)

    await client.start()
    _logger.info("[Discover] Connected to Telegram")

    _logger.info("[Discover] Fetching all dialogs (channels, groups, bots, users):")
    dialogs = await client.get_dialogs()

    channels = []
    for dialog in dialogs:
        telegram_entity = dialog.entity

        if isinstance(telegram_entity, (Channel, Chat, User)):
            entity_type, entity_name = _get_entity_type_and_name(telegram_entity)
            channel_id = _get_channel_identifier(telegram_entity, dialog.id)

            channel_info = {
                "id": channel_id,
                "keywords": {"files": [], "inline": []},
                "restricted_mode": False,
                "parser": {"trim_front_lines": 0, "trim_back_lines": 0},
                "ocr": False
            }

            channels.append({
                "name": entity_name,
                "type": entity_type,
                "info": channel_info
            })

            _logger.info(f"  Found: {entity_name:40} [{entity_type:10}] ({channel_id})")

    await client.disconnect()

    if not channels:
        _logger.warning("[Discover] No dialogs found!")
        return

    if diff_mode:
        existing_channel_ids, existing_channel_details = _load_existing_config(config_dir, config_filename)
        if existing_channel_ids is None:
            return

        new_channels, removed_channel_ids = _calculate_diff(channels, existing_channel_ids)
        has_changes = _print_diff_output(new_channels, removed_channel_ids, existing_channel_ids, channels)
        if not has_changes:
            return
    else:
        type_counts = {}
        for ch in channels:
            entity_type = ch.get('type', 'Unknown')
            type_counts[entity_type] = type_counts.get(entity_type, 0) + 1

        _logger.info(f"[Discover] Found {len(channels)} total dialogs:")
        for entity_type, count in sorted(type_counts.items()):
            _logger.info(f"  {entity_type}: {count}")

    # Only generate config file if --generate flag was provided
    if generate_config:
        _save_discovered_config(channels, config_dir)
