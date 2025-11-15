#!/usr/bin/env python3
"""Quick test to check if Slack destination is loaded properly"""
import sys
sys.path.insert(0, 'src')

from ConfigManager import ConfigManager
from AppTypes import APP_TYPE_SLACK

cm = ConfigManager()
slack_dests = [d for d in cm.destinations if d.get('type') == APP_TYPE_SLACK]

print(f"Total destinations: {len(cm.destinations)}")
print(f"Slack destinations: {len(slack_dests)}")
print()

for dest in slack_dests:
    print(f"Destination: {dest['name']}")
    print(f"  Type: {dest.get('type')}")
    print(f"  Has slack_webhook_url: {'slack_webhook_url' in dest}")
    if 'slack_webhook_url' in dest:
        url = dest['slack_webhook_url']
        print(f"  Webhook URL: {url[:50]}..." if url else "  Webhook URL: None")
    print(f"  Channels: {len(dest.get('channels', []))}")
    print()
