"""Tests for Discover module - Channel discovery functionality."""
import json
import asyncio
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch, AsyncMock
import pytest

from Discover import (
    _get_channel_identifier,
    _load_existing_config,
    _calculate_diff,
    _print_diff_output,
    _save_discovered_config,
    discover_channels
)


def test_returns_username_when_available():
    """Test returns @username format when available."""
    entity = Mock()
    entity.username = "test_channel"

    result = _get_channel_identifier(entity, 12345)

    assert result == "@test_channel"


def test_returns_numeric_id_when_no_username():
    """Test returns numeric ID when no username."""
    entity = Mock()
    entity.username = None

    result = _get_channel_identifier(entity, -1001234567890)

    assert result == "-1001234567890"


def test_returns_numeric_id_when_username_empty_string():
    """Test returns numeric ID when username is empty string."""
    entity = Mock()
    entity.username = ""

    result = _get_channel_identifier(entity, 999)

    assert result == "999"


def test_handles_entity_without_username_attribute():
    """Test handles entity lacking username attribute."""
    entity = Mock(spec=[])

    result = _get_channel_identifier(entity, 12345)

    assert result == "12345"


def test_loads_valid_config_successfully():
    """Test loads valid config successfully."""
    with tempfile.TemporaryDirectory() as tmpdir:
        config_dir = Path(tmpdir)
        config_path = config_dir / "config.json"

        test_config = {
            "destinations": [
                {
                    "name": "Feed1",
                    "channels": [
                        {"id": "@channel1", "keywords": {}},
                        {"id": "-1001234", "keywords": {}}
                    ]
                },
                {
                    "name": "Feed2",
                    "channels": [
                        {"id": "@channel2", "keywords": {}}
                    ]
                }
            ]
        }

        with open(config_path, 'w') as f:
            json.dump(test_config, f)

        channel_ids, channel_details = _load_existing_config(config_dir)

        assert channel_ids == {"@channel1", "-1001234", "@channel2"}
        assert len(channel_details) == 3


def test_returns_empty_set_when_no_config_exists():
    """Test returns empty set when no config exists."""
    with tempfile.TemporaryDirectory() as tmpdir:
        config_dir = Path(tmpdir)

        channel_ids, channel_details = _load_existing_config(config_dir)

        assert channel_ids == set()
        assert channel_details == {}


def test_filters_out_http_urls():
    """Test filters out HTTP URLs from config."""
    with tempfile.TemporaryDirectory() as tmpdir:
        config_dir = Path(tmpdir)
        config_path = config_dir / "config.json"

        test_config = {
            "destinations": [
                {
                    "name": "Feed",
                    "channels": [
                        {"id": "@channel1", "keywords": {}},
                        {"id": "https://example.com/rss", "keywords": {}},
                        {"id": "http://feed.com", "keywords": {}}
                    ]
                }
            ]
        }

        with open(config_path, 'w') as f:
            json.dump(test_config, f)

        channel_ids, _ = _load_existing_config(config_dir)

        assert channel_ids == {"@channel1"}


def test_handles_invalid_json():
    """Test handles malformed JSON config."""
    with tempfile.TemporaryDirectory() as tmpdir:
        config_dir = Path(tmpdir)
        config_path = config_dir / "config.json"

        with open(config_path, 'w') as f:
            f.write("{ invalid json syntax")

        channel_ids, channel_details = _load_existing_config(config_dir)

        assert channel_ids is None
        assert channel_details is None


def test_handles_custom_config_filename():
    """Test handles custom config filename."""
    with tempfile.TemporaryDirectory() as tmpdir:
        config_dir = Path(tmpdir)
        custom_path = config_dir / "custom_config.json"

        test_config = {
            "destinations": [
                {"name": "Feed", "channels": [{"id": "@test", "keywords": {}}]}
            ]
        }

        with open(custom_path, 'w') as f:
            json.dump(test_config, f)

        channel_ids, _ = _load_existing_config(config_dir, "custom_config.json")

        assert channel_ids == {"@test"}


def test_identifies_new_channels():
    """Test identifies new channels not in existing config."""
    discovered = [
        {"name": "New Channel 1", "type": "Channel", "info": {"id": "@new1"}},
        {"name": "New Channel 2", "type": "Channel", "info": {"id": "@new2"}},
        {"name": "Existing Channel", "type": "Channel", "info": {"id": "@existing"}},
    ]
    existing_ids = {"@existing"}

    new_channels, removed_ids = _calculate_diff(discovered, existing_ids)

    assert len(new_channels) == 2
    assert new_channels[0]["info"]["id"] == "@new1"
    assert new_channels[1]["info"]["id"] == "@new2"


def test_identifies_removed_channels():
    """Test identifies removed channels."""
    discovered = [
        {"name": "Channel 1", "type": "Channel", "info": {"id": "@channel1"}},
    ]
    existing_ids = {"@channel1", "@removed1", "@removed2"}

    new_channels, removed_ids = _calculate_diff(discovered, existing_ids)

    assert removed_ids == {"@removed1", "@removed2"}


def test_no_changes_returns_empty_results():
    """Test no changes returns empty results."""
    discovered = [
        {"name": "Channel 1", "type": "Channel", "info": {"id": "@ch1"}},
        {"name": "Channel 2", "type": "Channel", "info": {"id": "@ch2"}},
    ]
    existing_ids = {"@ch1", "@ch2"}

    new_channels, removed_ids = _calculate_diff(discovered, existing_ids)

    assert len(new_channels) == 0
    assert len(removed_ids) == 0


def test_returns_false_when_no_changes():
    """Test returns False when no changes detected."""
    new_channels = []
    removed_ids = set()
    existing_ids = {"@ch1", "@ch2"}
    all_channels = [
        {"name": "Ch1", "type": "Channel", "info": {"id": "@ch1"}},
        {"name": "Ch2", "type": "Channel", "info": {"id": "@ch2"}},
    ]

    result = _print_diff_output(new_channels, removed_ids, existing_ids, all_channels)

    assert not result


def test_returns_true_when_new_channels_exist():
    """Test returns True when new channels discovered."""
    new_channels = [
        {"name": "New Channel", "type": "Channel", "info": {"id": "@new"}}
    ]
    removed_ids = set()
    existing_ids = {"@old"}
    all_channels = new_channels + [{"name": "Old", "type": "Channel", "info": {"id": "@old"}}]

    result = _print_diff_output(new_channels, removed_ids, existing_ids, all_channels)

    assert result


def test_returns_true_when_removed_channels_exist():
    """Test returns True when removed channels detected."""
    new_channels = []
    removed_ids = {"@removed1", "@removed2"}
    existing_ids = {"@removed1", "@removed2", "@still_here"}
    all_channels = [{"name": "Still Here", "type": "Channel", "info": {"id": "@still_here"}}]

    result = _print_diff_output(new_channels, removed_ids, existing_ids, all_channels)

    assert result


def test_prints_summary_with_counts():
    """Test prints summary with correct counts."""
    new_channels = [
        {"name": "New1", "type": "Channel", "info": {"id": "@new1"}},
        {"name": "New2", "type": "Supergroup", "info": {"id": "@new2"}},
    ]
    removed_ids = {"@removed"}
    existing_ids = {"@existing", "@removed"}
    all_channels = new_channels + [{"name": "Existing", "type": "Channel", "info": {"id": "@existing"}}]

    result = _print_diff_output(new_channels, removed_ids, existing_ids, all_channels)

    assert result


def test_saves_config_to_json_file():
    """Test saves config to JSON file."""
    channels = [
        {
            "name": "Channel 1",
            "type": "Channel",
            "info": {"id": "@channel1", "keywords": {}, "ocr": False}
        },
        {
            "name": "Channel 2",
            "type": "Supergroup",
            "info": {"id": "-1001234", "keywords": {}, "ocr": False}
        }
    ]

    with tempfile.TemporaryDirectory() as tmpdir:
        config_dir = Path(tmpdir)

        _save_discovered_config(channels, config_dir)

        config_path = config_dir / "config_discovered.json"
        assert config_path.exists()

        with open(config_path, 'r') as f:
            saved_config = json.load(f)

        assert "destinations" in saved_config
        assert len(saved_config["destinations"]) == 1
        assert saved_config["destinations"][0]["name"] == "Auto-Generated Feed"
        assert saved_config["destinations"][0]["type"] == "Discord"
        assert len(saved_config["destinations"][0]["channels"]) == 2

        assert saved_config["destinations"][0]["channels"][0]["id"] == "@channel1"
        assert saved_config["destinations"][0]["channels"][1]["id"] == "-1001234"


def test_discover_channels_basic_mode():
    """Test discover_channels basic mode."""
    with patch('ConfigManager.ConfigManager') as MockConfigManager, \
         patch('telethon.TelegramClient') as MockTelegramClient:

        mock_config = MockConfigManager.return_value
        mock_config.config_dir = Path("/tmp/test_config")
        mock_config.api_id = "12345"
        mock_config.api_hash = "test_hash"

        mock_client = AsyncMock()
        MockTelegramClient.return_value = mock_client

        mock_dialog1 = Mock()
        mock_dialog1.id = 123
        mock_dialog1.entity = Mock()
        mock_dialog1.entity.username = "test_channel"
        mock_dialog1.entity.title = "Test Channel"
        mock_dialog1.entity.broadcast = True
        mock_dialog1.entity.megagroup = False

        from telethon.tl.types import Channel
        mock_dialog1.entity.__class__ = Channel

        mock_client.get_dialogs.return_value = [mock_dialog1]

        asyncio.run(discover_channels(diff_mode=False, generate_config=False))

        mock_client.start.assert_called_once()
        mock_client.disconnect.assert_called_once()
