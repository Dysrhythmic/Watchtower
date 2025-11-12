# Watchtower

<img src="./watchtower.png" alt="Watchtower Logo" width="200" height="200" />

Watchtower is an automated message routing and monitoring platform designed for CTI workflows. It monitors multiple sources at once, filters messages based on configurable keywords applied to message content and attachments (including OCR for images), and routes them to the designated destinations.

Current Sources:
- Telegram channels
- RSS feeds

Current Destinations:
- Telegram channels
- Discord webhooks

## Key Features
- Real-time monitoring of Telegram channels along with periodic polling to ensure no messages are missed
- Periodic polling of RSS/Atom feeds along with retroactively forwarding posts up to 2 days old
- Automatically splits long messages into chunks while attempting to maintain original formatting
- Includes attached media and reply context in messages
- Telegram channels can be set in `restricted_mode` to only forward safe text files and block all other media (images, videos, executables, etc.)
- For each destination, all channels have their own keyword filtering and other configuration for the most flexible routing control
- Message parser for trimming unwanted lines (e.g. signatures, ads, long descriptions, etc.) off messages before forwarding to the destination
- Rate limit handling with pre-emptive waiting
- Message retry queue with exponential backoff for failed deliveries
- OCR integration for Telegram messages to run keyword filters against text extracted from image attachments
- Attachment keyword checking for most text-based files
- Locally saved metrics for reviewing a summary of the session

## Requirements
- Python 3.9+
- Telegram API credentials ([get them here](https://my.telegram.org/apps))
- Discord webhook URL(s) (edit channel -> integrations -> webhooks)
- Telethon
- feedparser
- (Optional) EasyOCR for OCR-based filtering

See `requirements.txt` for version info.

## Setup
1. **Clone or download this repository**

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Create a `.env` file** in the `config/` directory based on the provided `env_example.txt` file

4. **Create a configuration file**. You can automatically generate one that defaults to forwarding all messages for all connected Telegram channels by using:
   ```bash
   python3 src/Watchtower.py discover --generate
   ```
   See the last section for examples of different configurations.

5. **Run Watchtower using subcommands:**
   The `monitor` subcommand examples:
   ```bash
   python3 src/Watchtower.py monitor --sources all
   python3 src/Watchtower.py monitor --sources telegram
   python3 src/Watchtower.py monitor --sources rss
   ```

   The `discover` subcommand:
   ```bash
   # Generate config from all accessible Telegram channels
   python3 src/Watchtower.py discover --generate

   # Compare discovered channels against existing config
   python3 src/Watchtower.py discover --diff
   ```

## Keyword Filtering

Keywords control which messages are forwarded to destinations. Messages are matched case-insensitively against both message text and text-based attachments. If OCR is enabled it will also extracted text form images to match against.

### Keyword Configuration Format
Keywords use a dictionary format with two optional keys:

```json
"keywords": {
  "files": ["kw-general.json", "kw-work.json"],
  "inline": ["custom-keyword", "specific-term"]
}
```

- **`files`** (optional): Array of keyword file names
- **`inline`** (optional): Array of keyword strings defined immediately afterwards
- If `keywords` is omitted or `null`, all messages from that channel are forwarded
- Both keys can be used at the same time, e.g.:

```json
"keywords": {
  "files": ["hackertools-wordlist.json"],
  "inline": ["project phoenix"]
}
```

### Keyword Files
Keyword files are JSON files stored in the `config/` directory (e.g., `Watchtower/config/kw-general.json`) with the following format:

```json
{
  "keywords": ["keyword1", "keyword2", "keyword3"]
}
```

### Notes
- Keywords are loaded once at application startup
- To reload changed keyword files, restart the application
- The same keyword file can be referenced by multiple channels/destinations
- Duplicate keywords (across files and inline) are allowed and don't affect matching
- The same channel can have different keyword filters for different destinations

### Attachment Keyword Checking
Text-based attachments can be checked for keywords in addition to message text and OCR. This feature is enabled by default and uses the same safe file type list as `restricted_mode` to prevent processing potentially malicious files. The list of allowed file types can be seen in `AllowedFileTypes.py`. Example with it disabled:
```json
{
  "channels": [{
    "id": "@channel",
    "keywords": ["malware"],
    "check_attachments": false
  }]
}
```

## Message Parser

The `parser` field allows you to modify message text before forwarding. Two parsing modes are available (mutually exclusive):

### Keep Only First N Lines
Keeps only the first N lines of a message and discards the rest. Useful for RSS feeds like the ones from YouTube channels where you may only want the title and link without long summaries. Example that keeps only the first 2 lines:

```json
{
  "parser": {
    "keep_first_lines": 2
  }
}
```

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

### Notes
- `keep_first_lines` and trim options cannot be used together
- All values must be non-negative integers
- Set to omit the `parser` field or set trim values to `0` for no parsing

## Security
- Keep your `.env` and `watchtower_session.session` files private.
- Both extension and MIME type checks provide some protection against malicious files being downloaded and read, but it is possible to spoof these values.
- Attachment checking and `restricted_mode` use the same safe file type list (i.e., `AllowedFileTypes.py`).

## Testing

All tests are designed to run offline without requiring API credentials or network access.

### Running Tests

**Install test dependencies:**
```bash
pip install pytest pytest-cov pytest-asyncio
```

**Run all tests:**
```bash
python3 -m pytest tests/
```

### Test Coverage

**Generate coverage report:**
```bash
python3 -m pytest tests/ --cov=src
```

**Generate coverage report including the missing statement line numbers:**
```bash
python3 -m pytest tests/ --cov=src --cov-report=term-missing
```

**Generate HTML coverage report:**
```bash
python3 -m pytest tests/ --cov=src --cov-report=html
```

## Troubleshooting
- If you change your Telegram account or channels, delete `watchtower_session.session` and restart.
- Make sure your Telegram account can access all the channels you want to monitor.
- Check the CLI logs for debug info (errors appear in red, warnings in yellow).
- Verify that your Discord webhook URLs are correct and the webhooks are active.
- Ensure channel IDs in your JSON config match the actual Telegram channel identifiers.
- For private Telegram channels, use the numeric chat ID (e.g., `-1001234567890`), not the invite link.

## Configuration Examples
All configuration is managed in `config/config.json` by default.

The configuration structure is destination-based. Each destination (e.g., Discord webhook or Telegram channel) routes messages from multiple sources:
- **Telegram channels** - defined in the `channels` array
- **RSS feeds** - defined in the `rss` array

Both source types route to the same destination with independent keyword filtering and other configuration rules.

### Example 1: Telegram -> Discord
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
          "ocr": true,
          "check_attachments": true
        }
      ]
    }
  ]
}
```
- Monitors Telegram channel `@example` (numeric IDs also work, e.g., `-1001234567890`)
- Forwards messages containing keywords `ransomware`, ` PoC `, or `My Company Brand Here`
- Text from image attachments is extracted with OCR and also checked against the same keywords
- Text-based attachments are also searched for keywords
- The spaces around ` PoC ` reduce false positives by preventing partial word matches (e.g., won't match `pocket` like `PoC` would)
- Matches are always case-insensitive
- Forwards to the Discord webhook URL stored in the `.env` file as `DISCORD_WEBHOOK_WORK`

### Example 2: Telegram -> Telegram
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
          "ocr": false,
          "check_attachments": false
        }
      ]
    }
  ]
}
```
- Forwards all messages from Telegram channel `-1001234567890`
- Sends to the Telegram channel ID stored in `.env` as `TELEGRAM_DEST_CHANNEL` (e.g., `@my_channel` or `-1009876543210`)
- Restricted mode filters to allow only specific filetypes
- Parser removes the last 2 lines from each message before forwarding
- Attachments are not checked for keywords

### Example 3: RSS -> Discord
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
          "parser": {"trim_front_lines": 0, "trim_back_lines": 0},
        }
      ]
    }
  ]
}
```
- Subscribes to `https://example.com/feed.xml` and polls it every 300 seconds (5 minutes)
- Forwards only feed items containing `vulnerability` or `CVE`
- Sends to the Discord webhook URL stored in `.env` as `DISCORD_WEBHOOK_FEEDS`
- Posts are not trimmed

### Example 4: Mixed Sources -> Multiple Destinations
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
          "ocr": false,
          "check_attachments": true
        }
      ]
    }
  ]
}
```
- **Discord destination**: Monitors Telegram channel `@vxunderground` and an RSS feed
  - Telegram channel:
    - Forwards messages with `malware` or `ransomware` keywords in their content or attachments
    - Checks OCR-extracted text and entire text-based attachments for keywords
    - Trims 1 line from front and 2 lines from end
  - RSS feed:
    - Forwards all posts
    - Keeps only first 2 lines of each entrpost
  - Sends to Discord webhook URL in `.env` as `DISCORD_WEBHOOK_ALERTS`
- **Telegram destination**: Monitors Telegram channel `@CTIUpdates`
  - Only forwards messages containing `breach` in their content or attachments
  - Trims 1 line from the beginning of each message
  - Sends to Telegram channel ID stored in `.env` as `TELEGRAM_BACKUP_CHANNEL` (e.g., `@my_backup_channel` or `-1003291374656`)


### Example 5: RSS Feed Reuse with Different Filters

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
- The RSS feed `https://example.com/feed.xml` is polled once every 300 seconds
- **Discord destination** receives only items containing `CVE`, `0-day`, or `exploit`
- **Telegram destination** receives all items with the last line trimmed
