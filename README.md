# Watchtower

<img src="./watchtower.png" alt="Watchtower Logo" width="200" height="200" />

A Cyber Threat Intelligence app for monitoring feeds, extracting text from images using OCR, filtering messages by keywords, parsing message content, and forwarding matches to other platforms. It currently supports the following sources and destinations:

Sources:
- Telegram channels (OCR supported)
- RSS feeds (OCR not supported)

Destinations:
- Discord webhooks
- Telegram channels

## Features
- Logs metadata from the latest Telegram message for each channel on startup to prove connectivity
- Forwards all new messages to the provided Discord webhook(s) or Telegram channel(s)
- Automatically splits long messages into chunks: 2000 characters for Discord, 4096 for Telegram messages, 1024 for Telegram media captions
- Includes attached media and reply context in messages
- Telegram channels can be set in `restricted_mode` to only forward safe text files and block all other media (images, videos, executables, etc.)
- For each destination, all channels have their own keyword filtering and other configuration for the most flexible routing control
- Enhanced message parser with two modes: trim lines from ends or keep only first N lines
- OCR integration for Telegram messages to run keyword filters against extracted text
- Attachment keyword checking for safe text-based files (enabled by default, validates both extension and MIME type)
- Configuration validation with duplicate destination detection and helpful warnings about default values
- RSS feed monitoring support
- Comprehensive test suite with 309 tests covering unit and integration scenarios
- Telegram polling every 5 minutes to catch messages missed during downtime or event handler failures
- Message retry queue with exponential backoff (5s, 10s, 20s) for failed deliveries
- Rate limit handling for both Discord and Telegram with pre-emptive waiting
- Graceful shutdown with cleanup of temporary files and metrics persistence
- Lightweight for compatibility running on devices with limited storage capacity such as a Raspberry Pi

## Requirements
- Python 3.9+
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
   python3 src/Watchtower.py monitor --sources all
   python3 src/Watchtower.py monitor --sources telegram
   python3 src/Watchtower.py monitor --sources rss
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

Text-based attachments can be checked for keywords in addition to message text and OCR. This feature is **enabled by default** and uses the same safe file type list as `restricted_mode` to prevent processing malicious files.

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
- `.sql` - SQL scripts

**Configuration Files:**
- `.ini` - INI files
- `.conf`, `.cfg` - Generic config files
- `.env` - Environment variables
- `.toml` - TOML config

**Security:** Both file extension AND MIME type are validated in an attempt to prevent spoofed malicious files.

### Configuration

**Enabled by default (no configuration needed):**
```json
{
  "channels": [{
    "id": "@channel",
    "keywords": ["malware", "exploit"]
  }]
}
```

**Explicitly disable if needed:**
```json
{
  "channels": [{
    "id": "@channel",
    "keywords": ["malware"],
    "check_attachments": false
  }]
}
```

### Behavior

- **Enabled by default**: No configuration needed, works out of the box
- **Complete file checking**: Entire file is read and checked for keywords (no partial reads)
- **Large file support**: Supports 3GB+ text files from Telegram (entire file is checked)
- **Security validation**: Both extension AND MIME type are checked (prevents spoofing)
- **Smart filtering**: Malicious file types (source code, binaries, configs with secrets) are automatically blocked
- **Encoding resilient**: Invalid UTF-8 characters are gracefully handled
- **Combined search**: Attachment text is added to message text + OCR for comprehensive keyword matching
- **Shared with restricted_mode**: Uses the same safe file type list for consistency
- **File size limits**: Discord destinations support up to 25MB attachments, Telegram destinations support up to 2GB attachments

### Example Use Cases

**Monitor threat intelligence channels sharing IOC dumps:**
```json
{
  "keywords": ["malicious", "C2", "backdoor"]
}
```

**Check JSON API responses shared in dev channels:**
```json
{
  "keywords": ["error", "failed", "exception"]
}
```

**Scan log files for specific events:**
```json
{
  "keywords": ["authentication failed", "access denied", "suspicious"]
}
```

## Security
- Keep your `.env` and `watchtower_session.session` files private.
- Both extension and MIME type checks provide defense-in-depth against malicious files, but determined attackers may still be able to spoof these values.
- Attachment checking and `restricted_mode` use the same safe file type list to ensure consistency.

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
- Logged every 5 minutes per RSS feed

**Missed Message Detection**
```
[TelegramHandler] Missed message detected: Channel Name msg_id=12346
[TelegramHandler] Processed 5 missed messages from Channel Name
```
- Appears when polling finds messages that were missed during downtime
- Polls every 5 minutes for each Telegram channel
- All missed messages are processed

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
[Watchtower] Final metrics for this session:
{
  "messages_received_telegram": 35361,
  "total_msgs_no_destination": 35326,
  "telegram_missed_messages_caught": 6934,
  "messages_received_rss": 9,
  "messages_sent_telegram": 41,
  "messages_sent_discord": 33,
  "total_msgs_routed_success": 44,
  "ocr_processed": 34,
  "ocr_msgs_sent": 3,
  "seconds_ran": 52002
}
```

**Metric Definitions:**
- `messages_received_telegram`: Total messages received from all Telegram channels
- `messages_received_rss`: Total entries received from all RSS feeds
- `telegram_missed_messages_caught`: Messages recovered via polling that were missed by event handlers
- `total_msgs_routed_success`: Messages successfully forwarded to at least one destination
- `total_msgs_no_destination`: Messages that did not match any destination keywords
- `messages_sent_discord`: Total messages successfully sent to Discord webhooks
- `messages_sent_telegram`: Total messages successfully sent to Telegram channels
- `ocr_processed`: Number of images processed through OCR
- `ocr_msgs_sent`: Messages with OCR text that were successfully forwarded
- `seconds_ran`: Total application runtime in seconds

**Note:** Metrics are automatically saved to `tmp/metrics.json` every 60 seconds during operation and on shutdown. This periodic save reduces disk I/O while ensuring metrics are preserved regularly.

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

The test suite includes **309 tests** covering:

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
- **Note:** All RSS feeds are polled every 300 seconds (5 minutes)
- **Age Filter:** RSS entries older than 2 days are automatically ignored to prevent message floods after extended downtime

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
          "ocr": true
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
