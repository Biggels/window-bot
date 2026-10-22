# window-bot

Small Python service for a Raspberry Pi that plans when to open the windows and posts the plan to Discord:

- **5:00am** — the day's plan, e.g. `• 9:30–10:15am — air out (45 min). 79–81°F, dew point 69°F; indoor humidity peaks ~74%, under 60% by 10:30am.`
- **12:30pm** — an update, only if the forecast changed the plan.
- **5:30pm** — tonight's plan (including overnight openings) and a one-line preview of tomorrow.
- Nothing between 9pm and 5am, and it never asks you to open or close the windows then.

It doesn't try to know whether the windows are actually open; it assumes you follow the plan.

## How it decides

Outdoor relative humidity is misleading: air that is 55°F and 80% outside is only about 44% once it warms to 72°F inside. So the bot works with **dew point** (how much water is actually in the air) and a small model of the house (`src/window_bot/house.py`) that tracks, in 15-minute steps:

- **indoor temperature** — held between your heat and cool setpoints by the HVAC, drifting toward outdoors while the windows are open;
- **indoor humidity** — outdoor air brought in by ventilation, moisture from people and cooking, moisture soaked up and released by walls and furniture, and moisture the AC removes while it runs;
- **staleness** — a CO2-like measure of how much the house needs fresh air (1 = closed for a long time, 0 = outdoor air).

Each plan day (wake-up to the next wake-up), the planner (`src/window_bot/planner.py`) picks up to two openings that bring in the most fresh air, subject to:

- indoor temperature staying between 65°F and 77°F while open;
- no rain likely;
- openings adding at most **3 hours of indoor humidity above 60%** compared with keeping the house closed, never pushing it past **75%**, and not raising the day's average humidity above 60%;
- the house **drying back out** by the next afternoon, so humid airings can't pile up moisture day after day.

That is what lets it recommend a short airing on a muggy summer morning: the humidity spike is brief, and the model knows the AC will pull it back down once the day heats up.

All of these limits are configurable. The house model's constants are reasonable starting points rather than measurements of your house; an indoor temperature/humidity/CO2 sensor would let them be calibrated, and `IndoorState.from_reading` is where a reading would plug in.

## Config

Start from [config.example.toml](config.example.toml), copy it to an untracked `config.toml`, and adjust. Only `latitude` and `longitude` are required; everything else has the defaults shown in the example. Worth setting:

- `[comfort]` `heat_setpoint` / `cool_setpoint` to match your thermostat
- `[house]` `floor_area_sq_ft`
- optional `discord_mention` if you want the webhook message to ping a user or role

Temperatures use the configured `temperature_unit` (`fahrenheit` or `celsius`). Humidity values are percentages. Config files from the original threshold-based version still load; the old threshold keys are ignored with a warning.

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

Print the plan for right now (nothing is sent or saved; add `--send` to post it to Discord):

```bash
uv run --env-file .env window-bot plan --config config.toml --slot morning
```

See what it would have recommended over past weather, month by month:

```bash
uv run window-bot backtest --config config.toml --start 2026-06-01 --end 2026-09-30
```

Run the scheduler continuously:

```bash
uv run --env-file .env window-bot run --config config.toml
```

Add `--log-level DEBUG` before the command for more detail.

## Raspberry Pi deployment

Clone and run the deploy script:

```bash
git clone <YOUR_REPO_URL> window-bot
cd window-bot
./deploy.sh
```

The script:

- Syncs the repo to `/opt/window-bot`
- Creates `/etc/window-bot/config.toml` (only if missing; defaults `state_file` to `/var/lib/window-bot/window-bot-state.json`)
- Creates `/etc/window-bot/window-bot.env` (only if missing) from [contrib/window-bot.env.example](contrib/window-bot.env.example)
- Installs/updates the systemd unit from [contrib/window-bot.service](contrib/window-bot.service)

After the first install, update your settings:

- Edit `/etc/window-bot/config.toml`
- Put the webhook URL in `/etc/window-bot/window-bot.env` and keep it private (`chmod 600 /etc/window-bot/window-bot.env`)
- Restart: `sudo systemctl restart window-bot`

To deploy updates later: `git pull` then re-run `./deploy.sh`.

Logs: `journalctl -u window-bot -f`

If you ever paste a real webhook into a tracked file or shell history, rotate it in Discord and replace it with a new one.

## Tests

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
```
