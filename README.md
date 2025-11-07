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
- Enhanced message parser with two modes: trim lines from ends or keep only first N lines
- OCR integration for Telegram messages to run keyword filters against extracted text
- Attachment keyword checking for text-based files (txt, json, csv, source code, config files, and more)
- Configuration validation with duplicate destination detection and helpful warnings about default values
- RSS feed monitoring support
- Comprehensive test suite with 282 tests covering unit and integration scenarios
- Lightweight for compatibility running on devices with limited storage capacity such as a Raspberry Pi

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

The `parser` field allows you to modify message text before forwarding. Two parsing modes are available (mutually exclusive):

### Keep Only First N Lines

Keeps only the first N lines of a message and discards the rest. Useful for RSS feeds where you only want the title and link without long summaries.

```json
{
  "parser": {
    "keep_first_lines": 2
  }
}
```

This keeps only the first 2 lines. If the message has more lines, a notice is appended: `[X more line(s) omitted by parser]`

### Trim Lines from Ends

Removes lines from the beginning and/or end of messages:

```json
{
  "parser": {
    "trim_front_lines": 1,
    "trim_back_lines": 2
  }
}
```

This removes the first line and last 2 lines from each message.

**Notes:**
- `keep_first_lines` and trim options **cannot be used together**
- All values must be non-negative integers
- Set to `0` or omit the `parser` field entirely for no parsing
- Parser validation occurs at startup with helpful error messages

## Attachment Keyword Checking

Text-based attachments can be checked for keywords in addition to message text and OCR. This is useful for analyzing text dumps, JSON files, source code, and configuration files shared in channels.

### Supported File Types

Watchtower automatically detects and processes these text-based file types:

**Text & Documentation:**
- `.txt` - Plain text files
- `.log` - Log files
- `.md` - Markdown files

**Data Formats:**
- `.json` - JSON data
- `.csv` - CSV data
- `.xml` - XML data
- `.yml`, `.yaml` - YAML configuration

**Source Code:**
- `.py` - Python
- `.js` - JavaScript
- `.java` - Java
- `.c`, `.cpp`, `.h`, `.hpp` - C/C++
- `.go` - Go
- `.rs` - Rust
- `.sh`, `.bash` - Shell scripts
- `.ps1` - PowerShell

**Configuration Files:**
- `.ini` - INI files
- `.conf`, `.cfg` - Generic config
- `.env` - Environment variables
- `.toml` - TOML config

### Configuration

**Enabled:**
```json
{
  "channels": [{
    "id": "@channel",
    "keywords": ["malware", "exploit"],
    "check_attachments": true
  }]
}
```

**Disabled (default, backward compatible):**
```json
{
  "channels": [{
    "id": "@channel",
    "keywords": ["malware"]
  }]
}
```

Omitting `check_attachments` or setting it to `false` disables the feature for that channel.

### Behavior

- **Complete file checking**: Entire file is read and checked for keywords (no partial reads)
- **Large file support**: Supports 3GB+ text files from Telegram (entire file is checked)
- **Smart filtering**: Binary files and unsupported types are automatically skipped
- **Encoding resilient**: Invalid UTF-8 characters are gracefully handled
- **Combined search**: Attachment text is added to message text + OCR for comprehensive keyword matching

### Example Use Cases

**Monitor threat intelligence channels sharing IOC dumps:**
```json
{
  "check_attachments": true,
  "keywords": ["malicious", "C2", "backdoor"]
}
```

**Check JSON API responses shared in dev channels:**
```json
{
  "check_attachments": true,
  "keywords": ["error", "failed", "exception"]
}
```

**Scan source code snippets for security issues:**
```json
{
  "check_attachments": true,
  "keywords": ["password", "api_key", "secret"]
}
```

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

## Understanding Log Output

Watchtower uses colored logging to make errors and warnings more visible:
- 🔴 **ERROR** messages appear in red
- 🟡 **WARNING** messages appear in yellow
- ⚪ **INFO** messages appear in white

### Common Log Messages

**Connection Proof (Startup)**
```
[Watchtower] CONNECTION ESTABLISHED
  Channel: Security Feed
  Latest message by: @username
  Timestamp: 2025-11-05 14:30:00
```
Appears on startup for each Telegram channel to verify connectivity. Shows the most recent message metadata.

**Telegram Message Processing**
```
[TelegramHandler] Received message tg_id=12345 from Channel Name
```
- `tg_id`: Telegram message ID (sequential integer unique within that channel)
- Logged for every message received from Telegram event handler

**RSS Feed Polling**
```
[RSSHandler] Security Feed polled; new=7; routed=3
```
- `new=7`: Number of new RSS entries found since last poll
- `routed=3`: Number of entries that matched keywords and were forwarded
- Logged every 5 minutes (300 seconds) per RSS feed

**Missed Message Detection**
```
[TelegramHandler] Missed message detected: Channel Name msg_id=12346
[TelegramHandler] Processed 5 missed messages from Channel Name
```
- Appears when polling finds messages that were missed during downtime
- Polls every 5 minutes (300 seconds) for each Telegram channel
- All missed messages are processed, not just the most recent

**Telegram Logs**
```
[TelegramHandler] Created log for Channel Name: msg_id=12345
[Watchtower] Cleared 3 telegram log file(s)
```
- Created on startup during connection proofs
- Cleared on shutdown (not persistent across restarts)
- Stored in `tmp/telegramlog/` with sanitized channel IDs as filenames

### Metrics Summary (Shutdown)
```
[Watchtower] Final metrics: {
  "telegram_missed_messages": 12,
  "messages_routed": 145,
  "time_ran": 3600
}
```
- `telegram_missed_messages`: Total messages found via polling that were previously missed
- `messages_routed`: Total messages successfully forwarded to at least one destination
- `time_ran`: Application runtime in seconds

## Testing

### Running Tests

Run all tests:
```bash
python3 -m unittest discover tests/
```

Run specific test file:
```bash
python3 -m unittest tests/test_telegram_handler.py
```

Run specific test class:
```bash
python3 -m unittest tests.test_telegram_handler.TestTelegramLogFunctionality
```

### Test Coverage

The test suite includes **282 tests** covering:

- **Configuration** (654 lines): Loading, validation, keyword resolution, parser validation
- **Telegram Handler** (1215 lines): Message formatting, restricted mode, URL defanging, log files
- **Discord Handler** (313 lines): Webhook sending, message chunking, rate limits
- **Message Router** (934 lines): Keyword matching, destination routing, attachment checking, parsing
- **RSS Handler** (569 lines): Feed parsing, deduplication, timestamp tracking
- **OCR Handler** (269 lines): Text extraction from images
- **Message Queue** (370 lines): Retry logic, exponential backoff
- **Metrics** (397 lines): Counter tracking, persistence
- **Integration Tests** (2536 lines): End-to-end flows including:
  - Telegram → Discord/Telegram pipelines
  - RSS → Discord/Telegram flows
  - Queue retry processing with multiple items
  - Media cleanup operations
  - Rate limit coordination across destinations
  - Mixed source processing

**Overall coverage: 69%** across 1,480 statements in the src/ directory.

Modules with highest coverage:
- MessageData.py: 100%
- DiscordHandler.py: 96%
- MetricsCollector.py: 96%
- MessageRouter.py: 93%

### Test Requirements

Tests use mock objects and don't require:
- Real Telegram API credentials
- Real Discord webhooks
- Network access
- External services

All tests run offline using unittest.mock for external dependencies.

## Telegram Log Files

Watchtower creates per-channel log files to track message processing and detect missed messages.

### File Structure

```
tmp/
└── telegramlog/
    ├── 123456789.txt      # Channel with ID -100123456789
    ├── channelname.txt    # Channel with username @channelname
    └── 987654321.txt      # Another channel
```

**Filename sanitization:**
- Numeric IDs: `-100` prefix stripped (e.g., `-100123456789` → `123456789.txt`)
- Username IDs: `@` prefix stripped (e.g., `@channel` → `channel.txt`)

### File Format

Each log file contains two lines:
```
Channel Display Name
12345
```
- **Line 1**: Human-readable channel name (for manual inspection)
- **Line 2**: Last processed message ID (integer)

### Lifecycle

1. **Created**: On startup during connection proofs with latest message ID
2. **Updated**: After processing each message (both event handler and polling)
3. **Used**: Every 5 minutes during polling to detect missed messages
4. **Cleared**: On shutdown (logs are not persistent across restarts)

### Why Not Persistent?

Telegram logs are intentionally cleared on shutdown because:
- We don't want to process messages sent during extended downtime
- Prevents message floods after long outages
- Simpler than implementing age-based filtering like RSS feeds

If you restart Watchtower, it will create new logs from the current latest message and won't process any messages sent while it was offline.

## Discover Command

The `discover` command helps you find all Telegram channels accessible to your account:

```bash
python3 src/Watchtower.py discover
```

### Example Output

```
Discovered 5 accessible Telegram channels:
  @securitynews (Security News Official)
  @threatalerts (Threat Intelligence Alerts)
  -1001234567890 (Private CTI Feed)
  @vxunderground (vx-underground)
  -1009876543210 (Research Group)

Generated config file: config/config_discovered.json
```

### Using the Output

1. **Review** `config_discovered.json` to see all discovered channels
2. **Copy** channel IDs/usernames to your `config/config.json`
3. **Add** keywords, parsers, and destinations for each channel
4. **Test** with `python3 src/Watchtower.py monitor --sources telegram`

### Diff Mode

Compare discovered channels against existing config:
```bash
python3 src/Watchtower.py discover --diff
```

**Output:**
```
Channels in config but not accessible:
  - @oldchannel (may have been deleted or you lost access)

Channels accessible but not in config:
  + @newchannel (available to add)
  + -1001234567890 (Private Feed - available to add)
```

Use this to audit your configuration and find new channels to monitor.

## Troubleshooting
- If you change your Telegram account or channels, delete `watchtower_session.session` and restart.
- Make sure your Telegram account can access all the channels you want to monitor.
- Check the CLI logs for debug info (errors appear in red, warnings in yellow).
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
          "keywords": ["malware", "ransomware"],
          "restricted_mode": false,
          "parser": {"trim_front_lines": 1, "trim_back_lines": 2},
          "ocr": true,
          "check_attachments": true
        }
      ],
      "rss": [
        {
          "url": "https://example.com/rss",
          "name": "Example RSS Feed",
          "keywords": [],
          "parser": {"keep_first_lines": 2}
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
- **Discord destination**: Monitors Telegram channel `@vxunderground` and RSS feed
  - Telegram channel:
    - Forwards messages with `malware` or `ransomware` keywords
    - Checks OCR-extracted text and entire text-based attachments for keywords
    - Trims 1 line from front and 2 lines from end
  - RSS feed:
    - Forwards all entries
    - Keeps only first 2 lines (title and link, omits summary)
  - Sends to Discord webhook URL in `.env` as `DISCORD_WEBHOOK_ALERTS`
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
