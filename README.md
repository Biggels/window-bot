# window-bot

Small Python service for a Raspberry Pi that polls current outdoor weather and sends a Discord notification when conditions switch between "open the windows" and "close the windows."

## How it works

- Polls Open-Meteo for current temperature and relative humidity.
- Uses configurable open ranges for temperature and humidity.
- Applies hysteresis margins so small swings near the threshold do not spam notifications.
- Persists the last known state to disk so a restart does not resend the same alert.
- Sends a Discord webhook only when the state actually changes.

## Config

Start from [config.example.toml](/home/biggels/projects/window-bot/config.example.toml), copy it to an untracked `config.toml`, and adjust:

- `latitude` and `longitude` for your home
- `temp_open_min` / `temp_open_max`
- `humidity_open_min` / `humidity_open_max`
- `temp_hysteresis_margin` / `humidity_hysteresis_margin`
- optional `discord_mention` if you want the webhook message to ping a user or role

Temperature thresholds use the configured `temperature_unit` (`fahrenheit` or `celsius`). Humidity values are percentages.

The Discord webhook should normally come from the `WINDOW_BOT_DISCORD_WEBHOOK_URL` environment variable, not from the config file. `discord_webhook_url` is still supported as a fallback for private configs, but the recommended local procedure is to keep the secret in a `.env` file and let `uv` load it:

```bash
cp config.example.toml config.toml
cp .env.example .env
```

Then put the real webhook in `.env` and run against `config.toml`, not the checked-in example file.

If you only allow Discord push notifications for mentions, set `discord_mention` in `config.toml` to a real Discord mention such as:

```toml
discord_mention = "<@123456789012345678>"
```

For a role mention, use `<@&ROLE_ID>`. For `@here` or `@everyone`, use those literal strings.

## Local usage

Create and sync the project environment with `uv`:

```bash
uv sync
```

Run a single poll for testing:

```bash
uv run --env-file .env window-bot run --config config.toml --once --log-level DEBUG
```

Run continuously:

```bash
uv run --env-file .env window-bot run --config config.toml
```

`uv run --help` confirms support for `--env-file <ENV_FILE>` and `--no-env-file`. Use `--env-file .env` explicitly so the secret-loading behavior is obvious.

## Raspberry Pi deployment

- Copy the project to the Pi.
- Install it with `python3 -m pip install -e .` or package it however you prefer.
- Put your config at `/etc/window-bot/config.toml`.
- Put the webhook in `/etc/window-bot/window-bot.env` using [window-bot.env.example](/home/biggels/projects/window-bot/contrib/window-bot.env.example) as the template, then `chmod 600 /etc/window-bot/window-bot.env`.
- Install the sample unit from [contrib/window-bot.service](/home/biggels/projects/window-bot/contrib/window-bot.service) and adjust paths if needed.
- Enable the service with `sudo systemctl enable --now window-bot`.

If you ever paste a real webhook into a tracked file or shell history, rotate it in Discord and replace it with a new one.

## Tests

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
```
