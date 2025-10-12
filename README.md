# Telecord

<img src="./telecord.png" alt="Telecord Logo" width="200" height="200" />

A simple Python app to forward messages from Telegram channels to Discord channels using Telethon and Discord webhooks.

## Features
- Logs metadata from the latest Telegram message for each channel on startup to prove connectivity
- Forwards all new messages to the provided Discord webhook(s)
- Automatically splits long messages into 2000-character chunks for Discord
- Includes attached media and reply context in messages
- Telegram channels can be set in `restricted_mode` to only forward text type media to avoid potential malicious/explicit media from being downloaded and sent
- Allows multiple webhooks with channel specific routing
- Keyword filtering per channel per webhook for flexible message routing based on content
- Routing configuration controlled with a JSON file for easy use
- Remove indicated number of lines from beginning (use positive numbers) or end (use negative numbers) of messages with the `parser` field in the configuration

## Requirements
- Python 3.8+
- Telegram API credentials ([get them here](https://my.telegram.org/apps))
- Discord webhook URL(s) (edit channel -> integrations -> webhooks)

## Setup
1. **Clone or download this repository**
2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```
3. **Create a `.env` file** in the project directory based on the provided `config_example.txt` file

4. **Create a configuration file** based on one of the provided `webhook_config_ex_n.json` files. See `config_example.txt` for more details.

5. **Run the bot:**
   ```bash
   python telecord.py
   ```
   - On first run, you will be prompted to log in to Telegram (phone number and code) to create your Telethon session.
   - The session will be saved in `telecord_session.session` for future runs.

## Keyword Filtering
- Keywords are case-insensitive
- If no keywords are specified for a channel, all messages from that channel are sent
- If keywords are specified, only messages containing at least one keyword are sent
- The same channel can have different keyword filters for different webhooks

## Security
- Keep your `.env` and `telecord_session.session` files private.

## Troubleshooting
- If you change your Telegram account or channels, delete `telecord_session.session` and restart the bot.
- Make sure your Telegram account can access all the channels you want to monitor.
- Check the CLI logs for errors if messages are not being forwarded.
- Verify that your Discord webhook URLs are correct and the webhooks are active.
- Ensure channel IDs in your JSON config match the actual Telegram channel identifiers.

## Example Output
<img width="625" height="669" alt="image" src="https://github.com/user-attachments/assets/fe1f2d60-ae6d-4003-8e40-d57523313c0e" />
