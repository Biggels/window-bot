# window-bot

Small Python service for a Raspberry Pi that polls current outdoor weather and sends a Discord notification when conditions switch between "open the windows" and "close the windows."

## How it works

- Polls Open-Meteo for current temperature and relative humidity.
- Uses configurable open ranges for temperature and humidity.
- Applies hysteresis margins so small swings near the threshold do not spam notifications.
- Persists the last known state to disk so a restart does not resend the same alert.
- Sends a Discord webhook only when the state actually changes.

## Config

Start from [config.example.toml](/home/biggels/projects/window-bot/config.example.toml) and adjust:

- `latitude` and `longitude` for your home
- `temp_open_min` / `temp_open_max`
- `humidity_open_min` / `humidity_open_max`
- `temp_hysteresis_margin` / `humidity_hysteresis_margin`
- `discord_webhook_url`

Temperature thresholds use the configured `temperature_unit` (`fahrenheit` or `celsius`). Humidity values are percentages.

## Local usage

Create a virtualenv if you want one, then install the project:

```bash
python3 -m pip install -e .
```

Run a single poll for testing:

```bash
window-bot run --config config.example.toml --once --log-level DEBUG
```

Run continuously:

```bash
window-bot run --config /path/to/config.toml
```

## Raspberry Pi deployment

- Copy the project to the Pi.
- Install it with `python3 -m pip install -e .` or package it however you prefer.
- Put your config at `/etc/window-bot/config.toml`.
- Install the sample unit from [contrib/window-bot.service](/home/biggels/projects/window-bot/contrib/window-bot.service) and adjust paths if needed.
- Enable the service with `sudo systemctl enable --now window-bot`.

## Tests

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
```
