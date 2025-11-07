# Feature Implementation Plan

## Overview
This document outlines the implementation plan for three new features:
1. Configuration validation and warnings
2. Text-based attachment keyword checking
3. Enhanced parser functionality

---

## Feature 1: Configuration Validation & Warnings

### Current State
ConfigManager (lines 63-67) notes it does NOT validate:
- Duplicate destination names
- All optional field values
- Telegram channel ID formats

Current validation only covers:
- Required env vars (TELEGRAM_API_ID, TELEGRAM_API_HASH)
- Destination types ('discord' or 'telegram')
- Destination endpoints (env vars exist and non-empty)
- Keyword file formats

### Proposed Changes

#### 1.1 Duplicate Destination Detection
**Location**: `src/ConfigManager.py` - `_load_config()` method (after line 148)

**Check**: Detect destinations with duplicate names
```python
# After processing all destinations, check for duplicates
destination_names = [d['name'] for d in destinations]
duplicates = [name for name in destination_names if destination_names.count(name) > 1]
if duplicates:
    unique_duplicates = set(duplicates)
    _logger.warning(
        f"[ConfigManager] Duplicate destination names detected: {', '.join(unique_duplicates)}. "
        f"This may cause confusion in logs but will not affect functionality."
    )
```

#### 1.2 Missing Optional Fields with Defaults
**Location**: `src/ConfigManager.py` - `_process_telegram_channel_sources()` method (around line 283)

**Checks**:
- `restricted_mode` defaults to `False`
- `ocr` defaults to `False`
- `parser` defaults to `None`
- `keywords` defaults to `[]` (forwards all)

**Implementation**:
```python
def _validate_channel_defaults(self, channel: Dict, destination_name: str, channel_id: str) -> None:
    """Log info about optional fields using default values."""

    if 'restricted_mode' not in channel:
        _logger.info(
            f"[ConfigManager] {destination_name} -> {channel_id}: "
            f"'restricted_mode' not set, defaulting to False (no restrictions)"
        )

    if 'ocr' not in channel:
        _logger.info(
            f"[ConfigManager] {destination_name} -> {channel_id}: "
            f"'ocr' not set, defaulting to False (no OCR processing)"
        )

    if 'parser' not in channel:
        _logger.info(
            f"[ConfigManager] {destination_name} -> {channel_id}: "
            f"'parser' not set, defaulting to None (no text parsing)"
        )

    keywords = channel.get('keywords', [])
    if not keywords:
        _logger.warning(
            f"[ConfigManager] {destination_name} -> {channel_id}: "
            f"'keywords' empty or not set - ALL messages from this source will be forwarded"
        )
```

#### 1.3 Source Configuration Summary
**Location**: `src/ConfigManager.py` - end of `__init__()` (after line 115)

**Output**: Summary log showing configuration overview
```python
# After _load_config completes
_logger.info(f"[ConfigManager] Configuration loaded: {len(self.destinations)} destinations, {len(self.rss_feeds)} RSS feeds")

for dest in self.destinations:
    telegram_sources = [ch for ch in dest['channels'] if ch.get('source_type') == SOURCE_TYPE_TELEGRAM]
    rss_sources = [ch for ch in dest['channels'] if ch.get('source_type') == SOURCE_TYPE_RSS]
    _logger.info(
        f"[ConfigManager]   - {dest['name']} ({dest['type']}): "
        f"{len(telegram_sources)} Telegram sources, {len(rss_sources)} RSS sources"
    )
```

#### 1.4 Validation Log Level
- **INFO**: Default values being used (non-critical)
- **WARNING**: Empty keywords (forwards all), duplicate names
- **ERROR**: Missing required fields, invalid types (existing)

---

## Feature 2: Text-Based Attachment Keyword Checking

### Current State
- Keyword matching only checks `message_data.text` and `message_data.ocr_raw` (MessageRouter.py:167-178)
- Media files are downloaded to `attachments_dir` (TelegramHandler.py:647)
- Media types detected: Photo, Document, Other (TelegramHandler.py:544-549)

### Proposed Changes

#### 2.1 Supported File Types
**Primary** (user suggested):
- `.txt` - Plain text files
- `.json` - JSON data
- `.csv` - CSV data

**Additional candidates** (please confirm):
- `.log` - Log files (common in threat intel)
- `.md` - Markdown files
- `.xml` - XML data
- `.yml`/`.yaml` - YAML configuration files
- Source code: `.py`, `.js`, `.java`, `.c`, `.cpp`, `.go`, `.rs` (if monitoring code repos)

**Recommendation**: Start with txt, json, csv, log, md (most common in CTI workflows)

#### 2.2 File Size Limits
**Concern**: Large files could cause performance issues

**Proposed limits**:
- Max file size: **5 MB** for keyword checking
- Max content read: **1 MB** (read first 1MB only)

**Rationale**:
- 5MB covers most text files in CTI context
- 1MB read limit prevents memory issues with large logs
- Users can adjust via constant if needed

#### 2.3 Implementation

**2.3.1 Add attachment text extraction method**

**Location**: `src/MessageRouter.py` (new method)

```python
def _extract_attachment_text(self, media_path: Optional[str]) -> Optional[str]:
    """Extract searchable text from text-based attachment files.

    Supports: .txt, .json, .csv, .log, .md

    Args:
        media_path: Path to downloaded media file

    Returns:
        Extracted text content (max 1MB), or None if not a text file or error
    """
    if not media_path:
        return None

    path = Path(media_path)
    if not path.exists():
        return None

    # Check file extension
    SUPPORTED_EXTENSIONS = {'.txt', '.json', '.csv', '.log', '.md'}
    if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        return None

    # Check file size (skip if > 5MB)
    MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB
    if path.stat().st_size > MAX_FILE_SIZE:
        _logger.info(
            f"[MessageRouter] Skipping attachment keyword check: "
            f"file too large ({path.stat().st_size / (1024*1024):.1f}MB > 5MB)"
        )
        return None

    # Read file content (max 1MB)
    MAX_READ_SIZE = 1 * 1024 * 1024  # 1MB
    try:
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read(MAX_READ_SIZE)
        return content
    except Exception as e:
        _logger.warning(f"[MessageRouter] Failed to read attachment {path.name}: {e}")
        return None
```

**2.3.2 Integrate into keyword matching**

**Location**: `src/MessageRouter.py` - `get_destinations()` method (around line 167)

**Modification**:
```python
# Current code (line 167-178):
searchable_text = message_data.text or ""

# If OCR enabled, append OCR text
if channel_config.get('ocr', False) and message_data.ocr_raw:
    searchable_text = f"{searchable_text}\n{message_data.ocr_raw}" if searchable_text else message_data.ocr_raw

# NEW: If message has media, try to extract text from attachment
if message_data.media_path:
    attachment_text = self._extract_attachment_text(message_data.media_path)
    if attachment_text:
        searchable_text = f"{searchable_text}\n{attachment_text}" if searchable_text else attachment_text
        _logger.debug(
            f"[MessageRouter] Added attachment text to keyword search "
            f"({len(attachment_text)} chars from {Path(message_data.media_path).name})"
        )

# Perform keyword matching (existing code continues)
keywords = channel_config.get('keywords')
...
```

#### 2.4 Logging
- **DEBUG**: When attachment text is extracted and added to search
- **INFO**: When file is skipped due to size limits
- **WARNING**: When file read fails

#### 2.5 Configuration
No new configuration needed. Feature works automatically for text files.

**Optional enhancement** (future):
Add `check_attachments: true/false` flag to channel config to disable if desired.

---

## Feature 3: Enhanced Parser Functionality

### Current State
Parser supports only (MessageRouter.py:184-243):
- `trim_front_lines`: Remove N lines from beginning
- `trim_back_lines`: Remove N lines from end

### Proposed Changes

#### 3.1 Keep Only First N Lines
**Use case**: RSS feeds with long summaries where you only want the headline

**Configuration**:
```json
{
  "parser": {
    "keep_first_lines": 2
  }
}
```

**Behavior**: Keep only the first 2 lines, discard everything else

#### 3.2 RSS Tag Filtering (Future Enhancement - Discuss)
**Use case**: Keep only specific RSS fields (e.g., just title and link, no summary)

**Current RSS format** (RSSHandler.py:175-188):
```
Title: <RSS entry title>
Link: <RSS entry link>
Summary: <RSS entry summary>
```

**Proposed configuration**:
```json
{
  "parser": {
    "rss_fields": ["title", "link"]  // Omit "summary"
  }
}
```

**Question for user**:
- Should this be implemented now or later?
- RSS format is currently just newline-separated text - would need to parse or tag fields
- Alternative: Use `keep_first_lines: 2` to achieve similar result?

#### 3.3 Implementation

**3.3.1 Extend parser config**

**Location**: `src/MessageRouter.py` - `parse_msg()` method (around line 202)

**Current config format**:
```python
{"trim_front_lines": N, "trim_back_lines": M}
```

**New config format** (backward compatible):
```python
{
    "trim_front_lines": N,     # Optional, default 0
    "trim_back_lines": M,      # Optional, default 0
    "keep_first_lines": X      # Optional, mutually exclusive with trim options
}
```

**Validation**: `keep_first_lines` cannot be used with `trim_front_lines` or `trim_back_lines`

**Modified parse_msg()**:
```python
def parse_msg(self, message_data: MessageData, parser_config: Optional[Dict]) -> MessageData:
    """Apply text parsing rules to message.

    Parser supports:
    - trim_front_lines + trim_back_lines: Remove lines from both ends
    - keep_first_lines: Keep only first N lines (mutually exclusive)

    Args:
        message_data: Original message
        parser_config: Parser configuration dict

    Returns:
        New MessageData with modified text
    """
    text = message_data.text or ""
    if not text:
        return message_data

    if not isinstance(parser_config, dict):
        return message_data

    # Option 1: keep_first_lines (mutually exclusive)
    if 'keep_first_lines' in parser_config:
        keep = int(parser_config.get('keep_first_lines', 0) or 0)

        # Validate mutually exclusive
        if parser_config.get('trim_front_lines') or parser_config.get('trim_back_lines'):
            _logger.warning(
                f"[MessageRouter] Invalid parser config: 'keep_first_lines' "
                f"cannot be used with 'trim_front_lines' or 'trim_back_lines'. "
                f"Using 'keep_first_lines' only."
            )

        if keep <= 0:
            _logger.warning(f"[MessageRouter] Invalid parser config: keep_first_lines must be > 0, got {keep}")
            return message_data

        lines = text.split('\n')
        new_lines = lines[:keep]

        if len(lines) > keep:
            new_text = '\n'.join(new_lines) + f"\n\n**[{len(lines) - keep} more lines omitted by parser]**"
        else:
            new_text = '\n'.join(new_lines)

        return self._create_parsed_message(message_data, new_text)

    # Option 2: trim_front_lines + trim_back_lines (existing code)
    front = int(parser_config.get('trim_front_lines', 0) or 0)
    back = int(parser_config.get('trim_back_lines', 0) or 0)

    # ... existing trim logic continues ...
```

**3.3.2 Helper method for creating parsed messages**

**Location**: `src/MessageRouter.py` (new method)

```python
def _create_parsed_message(self, original: MessageData, new_text: str) -> MessageData:
    """Create new MessageData with modified text, preserving all other fields.

    Args:
        original: Original MessageData
        new_text: Parsed text content

    Returns:
        New MessageData with modified text
    """
    return MessageData(
        source_type=original.source_type,
        channel_id=original.channel_id,
        channel_name=original.channel_name,
        username=original.username,
        timestamp=original.timestamp,
        text=new_text,
        has_media=original.has_media,
        media_type=original.media_type,
        media_path=original.media_path,
        reply_context=original.reply_context,
        original_message=original.original_message,
        ocr_enabled=original.ocr_enabled,
        ocr_raw=original.ocr_raw,
        metadata=original.metadata
    )
```

#### 3.4 Configuration Examples

**Example 1: RSS feed - keep only title and link**
```json
{
  "channels": [{
    "id": "https://feeds.example.com/security.xml",
    "keywords": ["vulnerability"],
    "parser": {
      "keep_first_lines": 2
    }
  }]
}
```

**Example 2: Telegram - remove first line (channel name) and last 2 lines (ads)**
```json
{
  "channels": [{
    "id": "@news_channel",
    "keywords": ["alert"],
    "parser": {
      "trim_front_lines": 1,
      "trim_back_lines": 2
    }
  }]
}
```

---

## Questions for Review

### Feature 2 (Attachment Checking):
1. **File types**: Approve txt, json, csv, log, md? Add others?
2. **Size limits**: 5MB file size, 1MB read limit acceptable?
3. **Automatic vs opt-in**: Should this be always-on or require config flag?

### Feature 3 (Parser):
1. **RSS tag filtering**: Implement now or postpone?
   - If now: How should fields be specified in RSS output?
   - If later: Is `keep_first_lines` sufficient for now?

2. **Parser naming**: Is `keep_first_lines` clear? Alternative: `max_lines`?

---

## Implementation Order

1. **Feature 1** (Config validation) - Lowest risk, high value
2. **Feature 3** (Parser - keep_first_lines) - Medium complexity
3. **Feature 2** (Attachment checking) - Highest complexity (file I/O, encoding handling)

---

## Testing Strategy

### Feature 1:
- Unit tests for duplicate detection
- Unit tests for default value logging
- Integration test with real config file

### Feature 2:
- Unit tests for each file type (.txt, .json, .csv, .log, .md)
- Unit tests for size limits (>5MB, >1MB read)
- Unit tests for encoding errors (binary files, invalid UTF-8)
- Integration test with actual Telegram document downloads

### Feature 3:
- Unit tests for keep_first_lines with various line counts
- Unit tests for mutual exclusivity validation
- Unit tests for edge cases (0 lines, negative values, more lines than exist)
- Integration test with RSS and Telegram messages

---

## Estimated Lines of Code

- **Feature 1**: ~80 lines (validation methods + logging)
- **Feature 2**: ~100 lines (file reading + integration)
- **Feature 3**: ~60 lines (parser extension + helper)
- **Tests**: ~300 lines (all features)

**Total**: ~540 lines
