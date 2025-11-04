# Watchtower

<img src="./watchtower.png" alt="Watchtower Logo" width="200" height="200" />

A Cyber Threat Intelligence app for monitoring feeds, running images through OCR, applying customizable filters and parsing to the messages and OCR output, and forwarding the result to other platforms. It currently supports the following sources and destinations:

Sources:
- Telegram channels (OCR supported)
- RSS feeds (OCR not supported)

Destinations:
- Discord webhooks
- Telegram channels

## Features
- Logs metadata from the latest Telegram message for each channel on startup to prove connectivity
- Forwards all new messages to the provided Discord webhook(s) or Telegram channel(s)
- Automatically splits long messages into 2000-character chunks (Discord character limit)
- Includes attached media and reply context in messages
- Telegram channels can be set in `restricted_mode` to only forward text type media to avoid potential malicious/explicit media from being downloaded and sent
- For each destination, all channels have their own keyword filtering and other configuration for the most flexible routing control
- Remove indicated number of lines from beginning and/or end of messages with the `parser` field in the configuration
- OCR integration for Telegram messages to run keyword filters against extracted text
- RSS feed monitoring support
- Lightweight for compatibility running on devices with limit storage capacity such as a Raspberry Pi

## Requirements
- Python 3.8+
- Telegram API credentials ([get them here](https://my.telegram.org/apps))
- Discord webhook URL(s) (edit channel -> integrations -> webhooks)
- (Optional) EasyOCR for OCR-based filtering

## Setup
1. **Clone or download this repository**

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Create a `.env` file** in the project directory based on the provided `env_example.txt` file

4. **Create a configuration file** based on the configuration examples at the end of this README. You can automatically generate one that defaults to forwarding all messages for all connected Telegram channels by using `python3 src/Watchtower.py discover`.

5. **Run the bot using subcommands:**

   The `monitor` subcommand examples:
   ```bash
   python3 src/watchtower.py monitor --sources all
   python3 src/watchtower.py monitor --sources telegram
   python3 src/watchtower.py monitor --sources rss
   ```

   The `discover` subcommand:
   ```bash
   # Generate config from all accessible Telegram channels
   python3 src/Watchtower.py discover

   # Compare discovered channels against existing config (shows diff)
   python3 src/Watchtower.py discover --diff
   ```

   The `--diff` option:
   - Compares discovered Telegram channels against your existing configuration
   - Shows new channels accessible to your account but not yet in config (marked with `+`)
   - Shows channels in config that are no longer accessible (marked with `-`)
   - Useful for auditing your configuration and finding new channels to add

## Keyword Filtering

Keywords control which messages are forwarded to destinations. Messages are matched case-insensitively against both message text and OCR-extracted text (if OCR is enabled).

### Keyword Configuration Format

Keywords use a dictionary format with two optional keys:

```json
"keywords": {
  "files": ["kw-general.json", "kw-work.json"],
  "inline": ["custom-keyword", "specific-term"]
}
```

- **`files`** (optional): Array of keyword file names in the `config/` directory
- **`inline`** (optional): Array of keyword strings defined directly in the config
- Both keys are optional, but at least one should be present for filtering
- If `keywords` is omitted or `null`, **all messages** from that channel are forwarded

### Keyword Files

Keyword files are JSON files stored in the `config/` directory with the following format:

```json
{
  "keywords": ["keyword1", "keyword2", "keyword3"]
}
```

**Example:** `config/kw-general.json`
```json
{
  "keywords": ["ransomware", "vulnerability", "CVE", "exploit"]
}
```

### Examples

**Load keywords from a single file:**
```json
"keywords": {
  "files": ["kw-general.json"]
}
```

**Load keywords from multiple files:**
```json
"keywords": {
  "files": ["kw-general.json", "kw-work.json"]
}
```

**Use inline keywords only:**
```json
"keywords": {
  "inline": ["my-company-name", "project-phoenix"]
}
```

**Combine file-based and inline keywords:**
```json
"keywords": {
  "files": ["kw-general.json"],
  "inline": ["company-specific-term"]
}
```

**Forward all messages (no filtering):**
```json
"keywords": null
```
or simply omit the `keywords` field.

### Notes
- Keywords are loaded once at application startup
- To reload changed keyword files, restart the application
- The same keyword file can be referenced by multiple channels/destinations
- Duplicate keywords (across files and inline) are allowed and don't affect matching
- The same channel can have different keyword filters for different destinations


## Message Parser
The `parser` field allows you to remove lines from the beginning and/or end of messages before forwarding:

```json
"parser": {
  "trim_front_lines": 1,
  "trim_back_lines": 2
}
```
This removes the first line and last 2 lines from each message.

- Both values must be non-negative integers
- Set either value to `0` to skip trimming from that end
- The `parser` field is optional and can be omitted entirely for no parsing

## Security
- Keep your `.env` and `watchtower_session.session` files private.
- While both MIME types and file extensions are checked in restricted mode, these values could easily be spoofed to bypass the filter if desired.

## Telegram Channel Configuration

### Public Channels
Public channels can be referenced by their username (with `@` prefix):
- **As a source**: `"channels": [{"id": "@example", ...}]`
- **As a destination**: Set your `.env` variable to `@my_backup_channel`

### Private Channels
Private channels (those with invite links like `https://t.me/+ewIIWdHcmfM5ZjAx`) must be referenced by their numeric chat ID, not the invite link.

**To find the numeric ID for a private channel:**

1. Join the private channel in your Telegram client using the invite link
2. Run Watchtower's discover command to list all accessible channels:
   ```bash
   python3 src/Watchtower.py discover
   ```
3. Find your private channel in the output - it will show the numeric ID (e.g., `-1001234567890`)
4. Use this numeric ID in your configuration:
   - **As a source**: `"channels": [{"id": "-1001234567890", ...}]`
   - **As a destination**: Set your `.env` variable to `-1003291374656`

**Note:** Your Telegram account must remain a member of the private channel for monitoring to work. If you leave the channel, you'll need to rejoin using the invite link.

## Troubleshooting
- If you change your Telegram account or channels, delete `watchtower_session.session` and restart.
- Make sure your Telegram account can access all the channels you want to monitor.
- Check the CLI logs for debug info.
- Verify that your Discord webhook URLs are correct and the webhooks are active.
- Ensure channel IDs in your JSON config match the actual Telegram channel identifiers.
- For private Telegram channels, use the numeric chat ID (e.g., `-1001234567890`), not the invite link.

## Configuration Examples
All configuration is managed in `config/config.json`.

The configuration structure is destination-based. Each destination (Discord webhook or Telegram channel) routes messages from multiple sources:
- **Telegram channels** - defined in the `channels` array
- **RSS feeds** - defined in the `rss` array

Both source types route to the same destination with independent keyword filtering and parsing rules.

**Note:** The top-level key can be either `"destinations"` (recommended) or `"webhooks"` (legacy). Both work identically.

#### Example 1: Telegram -> Discord
```json
{
  "destinations": [
    {
      "name": "Work Feed",
      "type": "discord",
      "env_key": "DISCORD_WEBHOOK_WORK",
      "channels": [
        {
          "id": "@example",
          "keywords": ["ransomware", " PoC ", "My Company Brand Here"],
          "restricted_mode": false,
          "ocr": true
        }
      ]
    }
  ]
}
```
- Monitors Telegram channel `@example` (numeric IDs also work, e.g., `-1001234567890`)
- Forwards messages containing keywords (or OCR-detected text) `ransomware`, ` PoC `, or `My Company Brand Here`
- The spaces around ` PoC ` reduce false positives by preventing partial word matches (e.g., won't match "pocket")
- Matches are always case-insensitive
- Forwards to the Discord webhook URL stored in the `.env` file as `DISCORD_WEBHOOK_WORK`
- `type` defaults to "discord" if omitted when `env_key` contains a webhook URL

#### Example 2: Telegram -> Telegram
```json
{
  "destinations": [
    {
      "name": "TG Forwarder",
      "type": "telegram",
      "env_key": "TELEGRAM_DEST_CHANNEL",
      "channels": [
        {
          "id": "-1001234567890",
          "keywords": [],
          "restricted_mode": true,
          "parser": {"trim_front_lines": 0, "trim_back_lines": 2},
          "ocr": false
        }
      ]
    }
  ]
}
```
- Forwards all messages from Telegram channel `-1001234567890`
- Sends to the Telegram channel ID stored in `.env` as `TELEGRAM_DEST_CHANNEL` (e.g., `@my_channel` or `-1009876543210`)
- Restricted mode filters to allow only specific safe filetypes
- Parser removes the last 2 lines from each message before forwarding
- `type: "telegram"` is required when routing to Telegram

#### Example 3: RSS -> Discord
```json
{
  "destinations": [
    {
      "name": "Feed Monitor",
      "type": "discord",
      "env_key": "DISCORD_WEBHOOK_FEEDS",
      "rss": [
        {
          "url": "https://example.com/feed.xml",
          "name": "Security News Feed",
          "keywords": ["vulnerability", "CVE"],
        }
      ]
    }
  ]
}
```
- Subscribes to `https://example.com/feed.xml` and polls it every 300 seconds (5 minutes)
- Forwards only feed items containing `vulnerability` or `CVE`
- Sends to the Discord webhook URL stored in `.env` as `DISCORD_WEBHOOK_FEEDS`
- **Note:** All RSS feeds are polled every 300 seconds (5 minutes) - this interval is not configurable

#### Example 4: Mixed Sources -> Multiple Destinations
```json
{
  "destinations": [
    {
      "name": "Mixed Feeds",
      "type": "discord",
      "env_key": "DISCORD_WEBHOOK_ALERTS",
      "channels": [
        {
          "id": "@vxunderground",
          "keywords": ["malware", "cat"],
          "restricted_mode": false,
          "parser": {"trim_front_lines": 1, "trim_back_lines": 2},
          "ocr": true
        }
      ],
      "rss": [
        {
          "url": "https://example.com/rss",
          "name": "Example RSS Feed",
          "keywords": [],
        }
      ]
    },
    {
      "name": "TG Backup",
      "type": "telegram",
      "env_key": "TELEGRAM_BACKUP_CHANNEL",
      "channels": [
        {
          "id": "@CTIUpdates",
          "keywords": ["breach"],
          "restricted_mode": false,
          "parser": {"trim_front_lines": 1, "trim_back_lines": 0},
          "ocr": false
        }
      ]
    }
  ]
}
```
- **Discord destination**: Monitors Telegram channel `@vxunderground` and RSS feed `https://example.com/rss`
  - Forwards everything from the RSS feed
  - For the Telegram channel, only forwards messages with `malware` or `cat` (including OCR-detected text)
  - Trims 1 line from the front and 2 lines from the end of VXUG messages
  - Sends to Discord webhook URL stored in `.env` as `DISCORD_WEBHOOK_ALERTS`
- **Telegram destination**: Monitors Telegram channel `@CTIUpdates`
  - Only forwards messages containing `breach`
  - Trims 1 line from the beginning of each message
  - Sends to Telegram channel ID stored in `.env` as `TELEGRAM_BACKUP_CHANNEL` (e.g., `@my_backup_channel` or `-1003291374656`)


#### Example 5: RSS Feed Reuse with Different Filters

Same RSS feed routed to multiple destinations with different keyword filters:

```json
{
  "destinations": [
    {
      "name": "Security Alerts",
      "type": "discord",
      "env_key": "DISCORD_WEBHOOK_SECURITY",
      "rss": [
        {
          "url": "https://example.com/feed.xml",
          "name": "Security Feed",
          "keywords": ["CVE", "0-day", "exploit"],
        }
      ]
    },
    {
      "name": "All News",
      "type": "telegram",
      "env_key": "TELEGRAM_NEWS_CHANNEL",
      "rss": [
        {
          "url": "https://example.com/feed.xml",
          "name": "Security Feed",
          "keywords": [],
          "parser": {"trim_front_lines": 0, "trim_back_lines": 1}
        }
      ]
    }
  ]
}
```
- The RSS feed `https://example.com/feed.xml` is polled **once** every 300 seconds
- **Discord destination** receives only items containing `CVE`, `0-day`, or `exploit`
- **Telegram destination** receives all items with the first line trimmed
- This demonstrates RSS feed deduplication: same feed, different filters per destination

## Example Output
<img width="607" height="187" alt="2025-10-27_18-50" src="https://github.com/user-attachments/assets/f4c80b89-0b92-485b-975e-66687ba33b6e" />
