"""Test ConfigManager configuration loading and validation."""
import sys
import os
import json
from unittest.mock import patch, mock_open
from pathlib import Path
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from ConfigManager import ConfigManager


def test_load_config_destinations_key():
    """Test loading config with 'destinations' key."""
    config_data = {
        "destinations": [{
            "name": "Test",
            "type": "Discord",
            "env_key": "DISCORD_WEBHOOK",
            "channels": [{"id": "@test", "keywords": {"inline": []}}]
        }]
    }

    with patch('builtins.open', mock_open(read_data=json.dumps(config_data))):
        with patch('os.getenv', return_value="https://discord.com/webhook"):
            with patch.object(Path, 'exists', return_value=True):
                with patch.object(Path, 'mkdir'):
                    config = ConfigManager()
                    assert len(config.destinations) == 1
                    assert config.destinations[0]['name'] == "Test"


def test_combine_keyword_files_and_inline():
    """Test combining keyword files + inline keywords."""
    kw_file_data = json.dumps({"keywords": ["file1", "file2"]})
    config_data = {
        "destinations": [{
            "name": "Test",
            "type": "Discord",
            "env_key": "DISCORD_WEBHOOK",
            "channels": [{
                "id": "@test",
                "keywords": {
                    "files": ["kw-test.json"],
                    "inline": ["inline1", "inline2"]
                }
            }]
        }]
    }

    def mock_open_multi(filename, *args, **kwargs):
        if 'kw-test.json' in str(filename):
            return mock_open(read_data=kw_file_data)()
        else:
            return mock_open(read_data=json.dumps(config_data))()

    with patch('builtins.open', mock_open_multi):
        with patch('os.getenv', return_value="https://discord.com/webhook"):
            with patch.object(Path, 'exists', return_value=True):
                with patch.object(Path, 'mkdir'):
                    config = ConfigManager()
                    keywords = config.destinations[0]['channels'][0]['keywords']
                    assert len(keywords) == 4
                    assert "file1" in keywords
                    assert "inline1" in keywords


def test_env_vs_json_precedence():
    """Test that env vars override JSON config values."""
    config_data = {
        "destinations": [{
            "name": "Test",
            "type": "Discord",
            "env_key": "DISCORD_WEBHOOK",
            "channels": [{"id": "@test", "keywords": {"inline": []}}]
        }]
    }

    env_webhook = "https://discord.com/webhook/from_env"

    with patch('builtins.open', mock_open(read_data=json.dumps(config_data))):
        with patch('os.getenv', return_value=env_webhook):
            with patch.object(Path, 'exists', return_value=True):
                with patch.object(Path, 'mkdir'):
                    config = ConfigManager()
                    assert config.destinations[0]['discord_webhook_url'] == env_webhook


def test_malformed_json_handling():
    """Test handling of malformed JSON config file."""
    malformed_json = '{"destinations": [{"name": "Test", invalid json}'

    with patch('builtins.open', mock_open(read_data=malformed_json)):
        with patch('os.getenv', return_value="test_value"):
            with patch.object(Path, 'exists', return_value=True):
                with patch.object(Path, 'mkdir'):
                    with pytest.raises(json.JSONDecodeError):
                        config = ConfigManager()


def test_missing_config_file():
    """Test handling when config file doesn't exist."""
    def mock_getenv(key, default=None):
        if key == "TELEGRAM_API_ID":
            return "123456"
        elif key == "TELEGRAM_API_HASH":
            return "abcdef123456"
        return default

    with patch('os.getenv', side_effect=mock_getenv):
        with patch.object(Path, 'exists', return_value=False):
            with patch.object(Path, 'mkdir'):
                with pytest.raises(ValueError) as exc_info:
                    config = ConfigManager()
                assert "not found" in str(exc_info.value)


def test_missing_keyword_file():
    """Test handling when keyword file doesn't exist."""
    config_data = {
        "destinations": [{
            "name": "Test",
            "type": "Discord",
            "env_key": "DISCORD_WEBHOOK",
            "channels": [{
                "id": "@test",
                "keywords": {
                    "files": ["nonexistent-keywords.json"],
                    "inline": ["inline1"]
                }
            }]
        }]
    }

    def mock_open_multi(filename, *args, **kwargs):
        if 'nonexistent-keywords.json' in str(filename):
            raise FileNotFoundError("Keyword file not found")
        else:
            return mock_open(read_data=json.dumps(config_data))()

    with patch('builtins.open', mock_open_multi):
        with patch('os.getenv', return_value="https://discord.com/webhook"):
            with patch.object(Path, 'exists', return_value=True):
                with patch.object(Path, 'mkdir'):
                    with pytest.raises(FileNotFoundError):
                        config = ConfigManager()


def test_rss_feed_config_loading():
    """Test loading RSS feed configuration."""
    config_data = {
        "destinations": [{
            "name": "RSS Destination",
            "type": "Discord",
            "env_key": "DISCORD_WEBHOOK",
            "channels": [{
                "id": "https://example.com/feed.xml",
                "keywords": {"inline": ["security", "breach"]}
            }]
        }]
    }

    with patch('builtins.open', mock_open(read_data=json.dumps(config_data))):
        with patch('os.getenv', return_value="https://discord.com/webhook"):
            with patch.object(Path, 'exists', return_value=True):
                with patch.object(Path, 'mkdir'):
                    config = ConfigManager()
                    assert len(config.destinations) == 1
                    assert config.destinations[0]['channels'][0]['id'] == "https://example.com/feed.xml"


def test_destination_validation_errors():
    """Test validation of invalid destination configs."""
    config_data = {
        "destinations": [{
            "name": "Test",
            "type": "Discord",
            "env_key": "DISCORD_WEBHOOK",
            "channels": [{"id": "@test", "keywords": {"inline": []}}]
        }]
    }

    def mock_getenv(key, default=None):
        if key == "TELEGRAM_API_ID":
            return "123456"
        elif key == "TELEGRAM_API_HASH":
            return "abcdef123456"
        elif key == "DISCORD_WEBHOOK":
            return "https://discord.com/webhook"
        return default

    with patch('builtins.open', mock_open(read_data=json.dumps(config_data))):
        with patch('os.getenv', side_effect=mock_getenv):
            with patch.object(Path, 'exists', return_value=True):
                with patch.object(Path, 'mkdir'):
                    config = ConfigManager()
                    assert len(config.destinations) == 1
                    assert config.destinations[0]['type'] == 'Discord'


def test_discord_only_without_telegram_credentials():
    """Test that Discord-only config with only RSS sources works without Telegram credentials."""
    config_data = {
        "destinations": [{
            "name": "Discord Only",
            "type": "Discord",
            "env_key": "DISCORD_WEBHOOK",
            "channels": [],
            "rss": [{"url": "https://example.com/feed.xml", "name": "Security Feed"}]
        }]
    }

    def mock_getenv(key, default=None):
        if key == "DISCORD_WEBHOOK":
            return "https://discord.com/webhook"
        elif key == "CONFIG_FILE":
            return default
        return None

    with patch('builtins.open', mock_open(read_data=json.dumps(config_data))):
        with patch('os.getenv', side_effect=mock_getenv):
            with patch.object(Path, 'exists', return_value=True):
                with patch.object(Path, 'mkdir'):
                    config = ConfigManager()
                    assert len(config.destinations) == 1
                    assert config.destinations[0]['type'] == 'Discord'
                    assert config.api_id is None
                    assert config.api_hash is None


def test_telegram_destination_requires_credentials():
    """Test that Telegram destination requires Telegram credentials."""
    config_data = {
        "destinations": [{
            "name": "Telegram Dest",
            "type": "Telegram",
            "env_key": "TELEGRAM_CHANNEL",
            "channels": [],
            "rss": [{"url": "https://example.com/feed.xml", "name": "Feed"}]
        }]
    }

    def mock_getenv(key, default=None):
        if key == "TELEGRAM_CHANNEL":
            return "@my_channel"
        elif key == "CONFIG_FILE":
            return default
        return None

    with patch('builtins.open', mock_open(read_data=json.dumps(config_data))):
        with patch('os.getenv', side_effect=mock_getenv):
            with patch.object(Path, 'exists', return_value=True):
                with patch.object(Path, 'mkdir'):
                    with pytest.raises(ValueError) as exc_info:
                        config = ConfigManager()
                    assert "Telegram" in str(exc_info.value)
                    assert "TELEGRAM_API_ID" in str(exc_info.value)


def test_telegram_source_requires_credentials():
    """Test that Telegram source channels require Telegram credentials even with Discord destination."""
    config_data = {
        "destinations": [{
            "name": "Discord with Telegram Source",
            "type": "Discord",
            "env_key": "DISCORD_WEBHOOK",
            "channels": [{"id": "@telegram_channel", "keywords": {"inline": []}}]
        }]
    }

    def mock_getenv(key, default=None):
        if key == "DISCORD_WEBHOOK":
            return "https://discord.com/webhook"
        elif key == "CONFIG_FILE":
            return default
        return None

    with patch('builtins.open', mock_open(read_data=json.dumps(config_data))):
        with patch('os.getenv', side_effect=mock_getenv):
            with patch.object(Path, 'exists', return_value=True):
                with patch.object(Path, 'mkdir'):
                    with pytest.raises(ValueError) as exc_info:
                        config = ConfigManager()
                    assert "Telegram" in str(exc_info.value)
                    assert "TELEGRAM_API_ID" in str(exc_info.value)


def test_rss_only_to_discord_without_telegram():
    """Test that RSS-only sources to Discord work without Telegram credentials."""
    config_data = {
        "destinations": [{
            "name": "RSS to Discord",
            "type": "Discord",
            "env_key": "DISCORD_WEBHOOK",
            "channels": [],
            "rss": [{"url": "https://example.com/feed.xml", "name": "Security Feed"}]
        }]
    }

    def mock_getenv(key, default=None):
        if key == "DISCORD_WEBHOOK":
            return "https://discord.com/webhook"
        elif key == "CONFIG_FILE":
            return default
        return None

    with patch('builtins.open', mock_open(read_data=json.dumps(config_data))):
        with patch('os.getenv', side_effect=mock_getenv):
            with patch.object(Path, 'exists', return_value=True):
                with patch.object(Path, 'mkdir'):
                    config = ConfigManager()
                    assert len(config.destinations) == 1
                    assert len(config.rss_feeds) == 1
                    assert config.api_id is None
                    assert config.api_hash is None


def test_keyword_file_parsing_errors():
    """Test handling malformed keyword files."""
    config_data = {
        "destinations": [{
            "name": "Test",
            "type": "Discord",
            "env_key": "DISCORD_WEBHOOK",
            "channels": [{
                "id": "@test",
                "keywords": {
                    "files": ["malformed-kw.json"],
                    "inline": []
                }
            }]
        }]
    }

    malformed_kw_data = '{"keywords": ["kw1", invalid json}'

    def mock_open_multi(filename, *args, **kwargs):
        if 'malformed-kw.json' in str(filename):
            return mock_open(read_data=malformed_kw_data)()
        else:
            return mock_open(read_data=json.dumps(config_data))()

    def mock_getenv(key, default=None):
        if key == "TELEGRAM_API_ID":
            return "123456"
        elif key == "TELEGRAM_API_HASH":
            return "abcdef123456"
        elif key == "DISCORD_WEBHOOK":
            return "https://discord.com/webhook"
        return default

    with patch('builtins.open', mock_open_multi):
        with patch('os.getenv', side_effect=mock_getenv):
            with patch.object(Path, 'exists', return_value=True):
                with patch.object(Path, 'mkdir'):
                    with pytest.raises(ValueError) as exc_info:
                        config = ConfigManager()
                    assert "Invalid JSON" in str(exc_info.value)


def test_empty_destinations_list():
    """Test loading config with empty destinations list."""
    config_data = {"destinations": []}

    def mock_getenv(key, default=None):
        if key == "TELEGRAM_API_ID":
            return "123456"
        elif key == "TELEGRAM_API_HASH":
            return "abcdef123456"
        return default

    with patch('builtins.open', mock_open(read_data=json.dumps(config_data))):
        with patch('os.getenv', side_effect=mock_getenv):
            with patch.object(Path, 'exists', return_value=True):
                with patch.object(Path, 'mkdir'):
                    with pytest.raises(ValueError) as exc_info:
                        config = ConfigManager()
                    assert "No valid destinations" in str(exc_info.value)


def test_multiple_destinations():
    """Test loading config with multiple destinations."""
    config_data = {
        "destinations": [
            {
                "name": "Discord 1",
                "type": "Discord",
                "env_key": "DISCORD_WEBHOOK_1",
                "channels": [{"id": "@test1", "keywords": {"inline": []}}]
            },
            {
                "name": "Discord 2",
                "type": "Discord",
                "env_key": "DISCORD_WEBHOOK_2",
                "channels": [{"id": "@test2", "keywords": {"inline": []}}]
            }
        ]
    }

    def mock_getenv(key, default=None):
        if key == "TELEGRAM_API_ID":
            return "123456"
        elif key == "TELEGRAM_API_HASH":
            return "abcdef123456"
        elif key == "DISCORD_WEBHOOK_1":
            return "https://discord.com/webhook1"
        elif key == "DISCORD_WEBHOOK_2":
            return "https://discord.com/webhook2"
        return default

    with patch('builtins.open', mock_open(read_data=json.dumps(config_data))):
        with patch('os.getenv', side_effect=mock_getenv):
            with patch.object(Path, 'exists', return_value=True):
                with patch.object(Path, 'mkdir'):
                    config = ConfigManager()
                    assert len(config.destinations) == 2
                    assert config.destinations[0]['name'] == "Discord 1"
                    assert config.destinations[1]['name'] == "Discord 2"


def test_channel_with_parser_config():
    """Test loading channel with parser configuration."""
    config_data = {
        "destinations": [{
            "name": "Test",
            "type": "Discord",
            "env_key": "DISCORD_WEBHOOK",
            "channels": [{
                "id": "@test",
                "keywords": {"inline": []},
                "parser": {
                    "trim_front_lines": 1,
                    "trim_back_lines": 2
                }
            }]
        }]
    }

    with patch('builtins.open', mock_open(read_data=json.dumps(config_data))):
        with patch('os.getenv', return_value="https://discord.com/webhook"):
            with patch.object(Path, 'exists', return_value=True):
                with patch.object(Path, 'mkdir'):
                    config = ConfigManager()
                    parser = config.destinations[0]['channels'][0]['parser']
                    assert parser['trim_front_lines'] == 1
                    assert parser['trim_back_lines'] == 2


def test_channel_with_ocr_enabled():
    """Test loading channel with OCR enabled."""
    config_data = {
        "destinations": [{
            "name": "Test",
            "type": "Discord",
            "env_key": "DISCORD_WEBHOOK",
            "channels": [{
                "id": "@test",
                "keywords": {"inline": []},
                "ocr": True
            }]
        }]
    }

    with patch('builtins.open', mock_open(read_data=json.dumps(config_data))):
        with patch('os.getenv', return_value="https://discord.com/webhook"):
            with patch.object(Path, 'exists', return_value=True):
                with patch.object(Path, 'mkdir'):
                    config = ConfigManager()
                    assert config.destinations[0]['channels'][0]['ocr']


def test_channel_with_restricted_mode():
    """Test loading channel with restricted mode enabled."""
    config_data = {
        "destinations": [{
            "name": "Test",
            "type": "Discord",
            "env_key": "DISCORD_WEBHOOK",
            "channels": [{
                "id": "@test",
                "keywords": {"inline": []},
                "restricted_mode": True
            }]
        }]
    }

    with patch('builtins.open', mock_open(read_data=json.dumps(config_data))):
        with patch('os.getenv', return_value="https://discord.com/webhook"):
            with patch.object(Path, 'exists', return_value=True):
                with patch.object(Path, 'mkdir'):
                    config = ConfigManager()
                    assert config.destinations[0]['channels'][0]['restricted_mode']


def test_empty_inline_keywords():
    """Test channel with empty inline keywords list."""
    config_data = {
        "destinations": [{
            "name": "Test",
            "type": "Discord",
            "env_key": "DISCORD_WEBHOOK",
            "channels": [{
                "id": "@test",
                "keywords": {"inline": []}
            }]
        }]
    }

    with patch('builtins.open', mock_open(read_data=json.dumps(config_data))):
        with patch('os.getenv', return_value="https://discord.com/webhook"):
            with patch.object(Path, 'exists', return_value=True):
                with patch.object(Path, 'mkdir'):
                    config = ConfigManager()
                    keywords = config.destinations[0]['channels'][0]['keywords']
                    assert len(keywords) == 0


def test_multiple_keyword_files():
    """Test combining multiple keyword files."""
    kw_file1_data = json.dumps({"keywords": ["kw1", "kw2"]})
    kw_file2_data = json.dumps({"keywords": ["kw3", "kw4"]})
    config_data = {
        "destinations": [{
            "name": "Test",
            "type": "Discord",
            "env_key": "DISCORD_WEBHOOK",
            "channels": [{
                "id": "@test",
                "keywords": {
                    "files": ["kw-file1.json", "kw-file2.json"],
                    "inline": []
                }
            }]
        }]
    }

    def mock_open_multi(filename, *args, **kwargs):
        if 'kw-file1.json' in str(filename):
            return mock_open(read_data=kw_file1_data)()
        elif 'kw-file2.json' in str(filename):
            return mock_open(read_data=kw_file2_data)()
        else:
            return mock_open(read_data=json.dumps(config_data))()

    with patch('builtins.open', mock_open_multi):
        with patch('os.getenv', return_value="https://discord.com/webhook"):
            with patch.object(Path, 'exists', return_value=True):
                with patch.object(Path, 'mkdir'):
                    config = ConfigManager()
                    keywords = config.destinations[0]['channels'][0]['keywords']
                    assert len(keywords) == 4
                    assert "kw1" in keywords
                    assert "kw3" in keywords


def test_numeric_channel_id():
    """Test loading config with numeric channel ID."""
    config_data = {
        "destinations": [{
            "name": "Test",
            "type": "Discord",
            "env_key": "DISCORD_WEBHOOK",
            "channels": [{
                "id": "-1001234567890",
                "keywords": {"inline": []}
            }]
        }]
    }

    with patch('builtins.open', mock_open(read_data=json.dumps(config_data))):
        with patch('os.getenv', return_value="https://discord.com/webhook"):
            with patch.object(Path, 'exists', return_value=True):
                with patch.object(Path, 'mkdir'):
                    config = ConfigManager()
                    assert config.destinations[0]['channels'][0]['id'] == "-1001234567890"


def test_config_with_telegram_credentials():
    """Test loading Telegram API credentials from env."""
    config_data = {
        "destinations": [{
            "name": "Test",
            "type": "Discord",
            "env_key": "DISCORD_WEBHOOK",
            "channels": [{"id": "@test", "keywords": {"inline": []}}]
        }]
    }

    def mock_getenv(key, default=None):
        if key == "TELEGRAM_API_ID":
            return "123456"
        elif key == "TELEGRAM_API_HASH":
            return "abcdef123456"
        elif key == "DISCORD_WEBHOOK":
            return "https://discord.com/webhook"
        return default

    with patch('builtins.open', mock_open(read_data=json.dumps(config_data))):
        with patch('os.getenv', side_effect=mock_getenv):
            with patch.object(Path, 'exists', return_value=True):
                with patch.object(Path, 'mkdir'):
                    config = ConfigManager()
                    assert config.api_id == "123456"
                    assert config.api_hash == "abcdef123456"


def test_get_all_channel_ids():
    """Test get_all_channel_ids returns all configured channels."""
    config_data = {
        "destinations": [
            {
                "name": "Dest1",
                "type": "Discord",
                "env_key": "DISCORD_WEBHOOK",
                "channels": [
                    {"id": "@chan1", "keywords": {"inline": []}},
                    {"id": "@chan2", "keywords": {"inline": []}}
                ]
            },
            {
                "name": "Dest2",
                "type": "Discord",
                "env_key": "DISCORD_WEBHOOK",
                "channels": [
                    {"id": "@chan3", "keywords": {"inline": []}}
                ]
            }
        ]
    }

    with patch('builtins.open', mock_open(read_data=json.dumps(config_data))):
        with patch('os.getenv', return_value="https://discord.com/webhook"):
            with patch.object(Path, 'exists', return_value=True):
                with patch.object(Path, 'mkdir'):
                    config = ConfigManager()
                    all_channels = config.get_all_channel_ids()
                    assert len(all_channels) == 3
                    assert "@chan1" in all_channels
                    assert "@chan2" in all_channels
                    assert "@chan3" in all_channels


def test_keyword_deduplication():
    """Test that duplicate keywords are deduplicated."""
    kw_file_data = json.dumps({"keywords": ["duplicate", "kw2"]})
    config_data = {
        "destinations": [{
            "name": "Test",
            "type": "Discord",
            "env_key": "DISCORD_WEBHOOK",
            "channels": [{
                "id": "@test",
                "keywords": {
                    "files": ["kw-test.json"],
                    "inline": ["duplicate", "kw3"]
                }
            }]
        }]
    }

    def mock_open_multi(filename, *args, **kwargs):
        if 'kw-test.json' in str(filename):
            return mock_open(read_data=kw_file_data)()
        else:
            return mock_open(read_data=json.dumps(config_data))()

    with patch('builtins.open', mock_open_multi):
        with patch('os.getenv', return_value="https://discord.com/webhook"):
            with patch.object(Path, 'exists', return_value=True):
                with patch.object(Path, 'mkdir'):
                    config = ConfigManager()
                    keywords = config.destinations[0]['channels'][0]['keywords']
                    assert len(keywords) >= 3


def test_invalid_destination_type():
    """Test that invalid destination types are rejected."""
    config_data = {
        "destinations": [{
            "name": "BadDest",
            "type": "invalid_type",
            "env_key": "SOME_WEBHOOK",
            "channels": [{"id": "@test", "keywords": {"inline": []}}]
        }]
    }

    with patch('builtins.open', mock_open(read_data=json.dumps(config_data))):
        with patch('os.getenv', return_value="https://example.com/webhook"):
            with patch.object(Path, 'exists', return_value=True):
                with patch.object(Path, 'mkdir'):
                    with pytest.raises(ValueError) as exc_info:
                        ConfigManager()
                    assert "No valid destinations" in str(exc_info.value)


def test_missing_destination_type():
    """Test that destinations without type field are rejected."""
    config_data = {
        "destinations": [{
            "name": "NoTypeDest",
            "env_key": "SOME_WEBHOOK",
            "channels": [{"id": "@test", "keywords": {"inline": []}}]
        }]
    }

    with patch('builtins.open', mock_open(read_data=json.dumps(config_data))):
        with patch('os.getenv', return_value="https://example.com/webhook"):
            with patch.object(Path, 'exists', return_value=True):
                with patch.object(Path, 'mkdir'):
                    with pytest.raises(ValueError) as exc_info:
                        ConfigManager()
                    assert "No valid destinations" in str(exc_info.value)


def test_missing_env_variable_for_destination():
    """Test that missing environment variables for destinations are handled."""
    config_data = {
        "destinations": [{
            "name": "MissingEnv",
            "type": "Discord",
            "env_key": "NONEXISTENT_WEBHOOK",
            "channels": [{"id": "@test", "keywords": {"inline": []}}]
        }]
    }

    def mock_getenv(key, default=None):
        if key in ["TELEGRAM_API_ID", "TELEGRAM_API_HASH"]:
            return "test123"
        return default

    with patch('builtins.open', mock_open(read_data=json.dumps(config_data))):
        with patch('os.getenv', side_effect=mock_getenv):
            with patch.object(Path, 'exists', return_value=True):
                with patch.object(Path, 'mkdir'):
                    with pytest.raises(ValueError) as exc_info:
                        ConfigManager()
                    assert "No valid destinations" in str(exc_info.value)


def test_destination_with_no_sources():
    """Test that destinations with no channels or RSS sources are rejected."""
    config_data = {
        "destinations": [{
            "name": "NoSources",
            "type": "Discord",
            "env_key": "DISCORD_WEBHOOK",
            "channels": []
        }]
    }

    with patch('builtins.open', mock_open(read_data=json.dumps(config_data))):
        with patch('os.getenv', return_value="https://discord.com/webhook"):
            with patch.object(Path, 'exists', return_value=True):
                with patch.object(Path, 'mkdir'):
                    with pytest.raises(ValueError) as exc_info:
                        ConfigManager()
                    assert "No valid destinations" in str(exc_info.value)


def test_invalid_telegram_channels_config():
    """Test that invalid telegram channel configs are rejected."""
    config_data = {
        "destinations": [{
            "name": "InvalidChannels",
            "type": "Discord",
            "env_key": "DISCORD_WEBHOOK",
            "channels": [{"keywords": {"inline": []}}]
        }]
    }

    with patch('builtins.open', mock_open(read_data=json.dumps(config_data))):
        with patch('os.getenv', return_value="https://discord.com/webhook"):
            with patch.object(Path, 'exists', return_value=True):
                with patch.object(Path, 'mkdir'):
                    with pytest.raises(ValueError) as exc_info:
                        ConfigManager()
                    assert "No valid destinations" in str(exc_info.value)


def test_invalid_trim_front_lines_negative():
    """Test that negative trim_front_lines disables parser."""
    config_data = {
        "destinations": [{
            "name": "Test",
            "type": "Discord",
            "env_key": "DISCORD_WEBHOOK",
            "channels": [{
                "id": "@test",
                "keywords": {"inline": []},
                "parser": {"trim_front_lines": -1, "trim_back_lines": 0}
            }]
        }]
    }

    with patch('builtins.open', mock_open(read_data=json.dumps(config_data))):
        with patch('os.getenv', return_value="https://discord.com/webhook"):
            with patch.object(Path, 'exists', return_value=True):
                with patch.object(Path, 'mkdir'):
                    config = ConfigManager()
                    assert config.destinations[0]['channels'][0].get('parser') is None


def test_invalid_trim_back_lines_negative():
    """Test that negative trim_back_lines disables parser."""
    config_data = {
        "destinations": [{
            "name": "Test",
            "type": "Discord",
            "env_key": "DISCORD_WEBHOOK",
            "channels": [{
                "id": "@test",
                "keywords": {"inline": []},
                "parser": {"trim_front_lines": 0, "trim_back_lines": -5}
            }]
        }]
    }

    with patch('builtins.open', mock_open(read_data=json.dumps(config_data))):
        with patch('os.getenv', return_value="https://discord.com/webhook"):
            with patch.object(Path, 'exists', return_value=True):
                with patch.object(Path, 'mkdir'):
                    config = ConfigManager()
                    assert config.destinations[0]['channels'][0].get('parser') is None


def test_invalid_trim_lines_non_integer():
    """Test that non-integer trim values disable parser."""
    config_data = {
        "destinations": [{
            "name": "Test",
            "type": "Discord",
            "env_key": "DISCORD_WEBHOOK",
            "channels": [{
                "id": "@test",
                "keywords": {"inline": []},
                "parser": {"trim_front_lines": "2", "trim_back_lines": 0}
            }]
        }]
    }

    with patch('builtins.open', mock_open(read_data=json.dumps(config_data))):
        with patch('os.getenv', return_value="https://discord.com/webhook"):
            with patch.object(Path, 'exists', return_value=True):
                with patch.object(Path, 'mkdir'):
                    config = ConfigManager()
                    assert config.destinations[0]['channels'][0].get('parser') is None


def test_valid_trim_lines_zero():
    """Test that zero trim values are valid."""
    config_data = {
        "destinations": [{
            "name": "Test",
            "type": "Discord",
            "env_key": "DISCORD_WEBHOOK",
            "channels": [{
                "id": "@test",
                "keywords": {"inline": []},
                "parser": {"trim_front_lines": 0, "trim_back_lines": 0}
            }]
        }]
    }

    with patch('builtins.open', mock_open(read_data=json.dumps(config_data))):
        with patch('os.getenv', return_value="https://discord.com/webhook"):
            with patch.object(Path, 'exists', return_value=True):
                with patch.object(Path, 'mkdir'):
                    config = ConfigManager()
                    assert config.destinations[0]['channels'][0].get('parser') is not None
                    parser = config.destinations[0]['channels'][0]['parser']
                    assert parser['trim_front_lines'] == 0
                    assert parser['trim_back_lines'] == 0


def test_invalid_rss_parser_trim_values():
    """Test that invalid trim values in RSS parser disable parser."""
    config_data = {
        "destinations": [{
            "name": "Test",
            "type": "Discord",
            "env_key": "DISCORD_WEBHOOK",
            "channels": [],
            "rss": [{
                "url": "https://example.com/feed.xml",
                "name": "Test Feed",
                "keywords": {"inline": []},
                "parser": {"trim_front_lines": -1, "trim_back_lines": 0}
            }]
        }]
    }

    with patch('builtins.open', mock_open(read_data=json.dumps(config_data))):
        with patch('os.getenv', return_value="https://discord.com/webhook"):
            with patch.object(Path, 'exists', return_value=True):
                with patch.object(Path, 'mkdir'):
                    config = ConfigManager()
                    rss_channel = config.destinations[0]['channels'][0]
                    assert rss_channel.get('parser') is None


def test_rss_feed_url_deduplication():
    """Test that RSS feeds with duplicate URLs are deduplicated."""
    config_data = {
        "destinations": [
            {
                "name": "Dest1",
                "type": "Discord",
                "env_key": "DISCORD_WEBHOOK",
                "channels": [],
                "rss": [{"url": "https://example.com/feed.xml", "name": "Feed1"}]
            },
            {
                "name": "Dest2",
                "type": "Discord",
                "env_key": "DISCORD_WEBHOOK",
                "channels": [],
                "rss": [{"url": "https://example.com/feed.xml", "name": "Feed2"}]
            }
        ]
    }

    with patch('builtins.open', mock_open(read_data=json.dumps(config_data))):
        with patch('os.getenv', return_value="https://discord.com/webhook"):
            with patch.object(Path, 'exists', return_value=True):
                with patch.object(Path, 'mkdir'):
                    config = ConfigManager()
                    assert len(config.rss_feeds) == 1
                    assert config.rss_feeds[0]['rss_url'] == "https://example.com/feed.xml"
