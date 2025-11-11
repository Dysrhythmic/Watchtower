"""
Shared constants for allowed file types.

This module defines the unified lists of file extensions and MIME types that are
text-based and searchable for keyword matching.

Both attachment keyword checking and restricted mode use these same lists to ensure
consistent behavior. Files must match both extension and MIME type to be accepted.
"""

ALLOWED_EXTENSIONS = {
    '.txt',   # Plain text files
    '.log',   # Log files
    '.csv',   # CSV data files
    '.xml',   # XML data files
    '.json',  # JSON data files
    '.yml',   # YAML configuration (data format, not executable)
    '.yaml',  # YAML configuration (data format, not executable)
    '.md',    # Markdown documentation
    '.sql',   # SQL scripts (text-based)
    '.ini',   # INI configuration files
    '.conf',  # Generic configuration files
    '.cfg',   # Configuration files
    '.env',   # Environment variable files
    '.toml'   # TOML configuration files
}

ALLOWED_MIME_TYPES = {
    'text/plain',              # .txt, .log, .sql, .ini, .conf, .cfg, .env
    'text/csv',                # .csv
    'text/xml',                # .xml
    'application/xml',         # .xml (alternate MIME type)
    'application/json',        # .json
    'text/yaml',               # .yml, .yaml
    'application/yaml',        # .yml, .yaml (alternate MIME type)
    'application/x-yaml',      # .yml, .yaml (another alternate)
    'text/markdown',           # .md
    'text/x-markdown',         # .md (alternate MIME type)
    'application/toml',        # .toml
    'text/toml'                # .toml (alternate MIME type)
}
