# Watchtower Documentation

Comprehensive architecture documentation for the Watchtower CTI Message Routing System.

## Documentation Overview

This directory contains detailed technical documentation with Mermaid diagrams illustrating the system architecture, data flows, and component interactions.

## Quick Navigation

### 📋 [Architecture Overview](architecture-overview.md)
**Start here for a high-level understanding of the system.**

- Component diagram showing all major components and their relationships
- Data structures (MessageData, destination configuration)
- Message flow summary
- Key design patterns (dependency injection, abstract base classes, retry pattern)

**Best for**: New developers, system overview, understanding component responsibilities

---

### 🔄 [Data Flow Diagram](data-flow.md)
**Detailed message flow from source to destination.**

- End-to-end message flow (Telegram and RSS paths)
- Message queue retry flow with exponential backoff
- Key decision points (OCR trigger, restricted mode, keyword matching)
- Performance characteristics and error handling

**Best for**: Understanding message processing pipeline, debugging routing issues, optimizing performance

---

### 🏗️ [Class Diagram](class-diagram.md)
**Class structure and relationships.**

- Main class relationships with attributes and methods
- Class responsibilities and purposes
- Inheritance hierarchy (DestinationHandler → TelegramHandler/DiscordHandler)
- Composition relationships (what contains what)
- Data flow between classes

**Best for**: Code navigation, understanding class interfaces, planning new features

---

### 📊 [Message Processing Sequence](message-processing-sequence.md)
**Step-by-step sequence diagrams for message processing.**

- Telegram message processing sequence (with OCR, routing, delivery)
- RSS message processing sequence
- Retry queue processing sequence
- Timing characteristics and error handling paths

**Best for**: Debugging specific flows, understanding async operations, troubleshooting delivery issues

---

### ⚙️ [Configuration Structure](configuration-structure.md)
**Configuration file format and loading process.**

- Configuration file hierarchy (.env, config.json, keyword files)
- Complete config.json structure diagram
- Example configurations (minimal and complete)
- Configuration field reference table
- Best practices for keywords, restricted mode, parsers, OCR
- Configuration loading sequence

**Best for**: Setting up new destinations, configuring channels, keyword management

---

### 🚀 [Deployment Structure](deployment-structure.md)
**Project structure and deployment guide.**

- Project directory structure with file descriptions
- Deployment architecture diagram
- Network communications and resource requirements
- Installation and setup instructions
- Running as a service (systemd, Docker)
- Backup & recovery procedures
- Monitoring, logging, and troubleshooting

**Best for**: Deploying Watchtower, system administration, production setup

---

## Documentation Conventions

### Diagram Types

This documentation uses several types of Mermaid diagrams:

1. **Component Diagrams** (`graph TB/LR`) - Show system architecture and component relationships
2. **Flowcharts** (`flowchart TD`) - Show decision flows and processing steps
3. **Sequence Diagrams** (`sequenceDiagram`) - Show interactions over time between components
4. **Class Diagrams** (`classDiagram`) - Show object-oriented structure

### Mermaid Rendering

All diagrams are in Mermaid format and will render in:
- GitHub (native support)
- GitLab (native support)
- VS Code (with Mermaid extension)
- Online: [mermaid.live](https://mermaid.live)

### Color Coding

All diagrams use **black backgrounds with white text** for optimal readability.

Different components are highlighted using the same black/white scheme:
- Core orchestrator and critical components
- Configuration and data structures
- Routing and processing logic
- Handlers and external interfaces
- Optional/enhancement features

Note: All boxes use `fill:#000,stroke:#fff,color:#fff` for consistent dark theme styling.

## Using This Documentation

### For New Developers

**Recommended reading order**:
1. Start with [Architecture Overview](architecture-overview.md) to understand the big picture
2. Read [Data Flow Diagram](data-flow.md) to see how messages move through the system
3. Review [Class Diagram](class-diagram.md) to understand code structure
4. Refer to [Configuration Structure](configuration-structure.md) when setting up
5. Use [Deployment Structure](deployment-structure.md) for running the application

### For Debugging

**Quick reference**:
- **Message not routing**: Check [Data Flow → Key Decision Points](data-flow.md#key-decision-points)
- **Configuration errors**: See [Configuration Structure → Validation](configuration-structure.md#configuration-validation)
- **Delivery failures**: Review [Message Processing Sequence → Error Handling](message-processing-sequence.md#error-handling-paths)
- **Performance issues**: Check [Data Flow → Performance Characteristics](data-flow.md#performance-characteristics)

### For Adding Features

**Development workflow**:
1. Understand component responsibilities: [Class Diagram → Responsibilities](class-diagram.md#class-responsibilities)
2. Identify integration points: [Architecture Overview → Message Flow](architecture-overview.md#message-flow-summary)
3. Plan data flow: [Data Flow Diagram](data-flow.md)
4. Review configuration impact: [Configuration Structure](configuration-structure.md)
5. Update relevant diagrams when making changes

## Diagram Source Files

All diagrams are embedded directly in markdown files using Mermaid code blocks:

```markdown
\`\`\`mermaid
graph TB
    A --> B
\`\`\`
```

To edit diagrams:
1. Edit the markdown file directly
2. Use [mermaid.live](https://mermaid.live) for live preview
3. Commit changes with descriptive message
4. Diagrams auto-render on GitHub/GitLab

## Additional Resources

### Code Documentation
- All source files have comprehensive module docstrings
- All classes have detailed class docstrings with attributes
- All methods have docstrings with Args/Returns/Raises sections
- See `src/` directory for inline code documentation

### Test Documentation
- All test files have module docstrings explaining what they test
- Test patterns and templates included in each file
- Mock setup examples for common scenarios
- See `tests/` directory for test documentation

### External Documentation
- **Telethon**: https://docs.telethon.dev/
- **Discord Webhooks**: https://discord.com/developers/docs/resources/webhook
- **EasyOCR**: https://github.com/JaidedAI/EasyOCR
- **feedparser**: https://feedparser.readthedocs.io/

## Contributing to Documentation

When adding or modifying features:

1. **Update relevant diagrams** to reflect changes
2. **Add new diagrams** if introducing new flows or components
3. **Update configuration examples** if changing config structure
4. **Document breaking changes** clearly
5. **Keep sequence diagrams** in sync with actual code behavior

### Diagram Guidelines

- Use descriptive node labels (avoid abbreviations)
- Include comments for complex logic
- Show error paths in sequence diagrams
- Use consistent styling (colors, shapes)
- Keep diagrams focused (one concept per diagram)

## Questions?

If documentation is unclear or missing:
1. Check source code comments for implementation details
2. Review test files for usage examples
3. Open an issue for documentation improvements
4. Contribute corrections via pull request

---

**Last Updated**: 2025-01-05
**Documentation Version**: 1.0
**Code Version**: See git commit hash
