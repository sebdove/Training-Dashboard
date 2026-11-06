# Training Dashboard

A personal training dashboard for whatever you're training towards: a T100, an Ironman 70.3, a marathon or any other event. You name your goal event in **Settings**, and the name appears across the dashboard. It pulls your data live from **Garmin Connect** (built and tested with a Fenix 8) and combines it with your own season plan, a countdown to your event, FTP tests and training-device readings.

It runs as a small server on your own computer. Open it in a browser, or install it as an app from the browser.

![The training overview, shown with example data](docs/screenshot-overview.png)

## What it shows

- **Training overview**
  - Your goal event's name and distances, days to go, the current training phase and days to its test day.
  - This week's hours.
  - VO2 max, resting HR, HRV and sleep.
  - A clickable season plan: colour-coded phase squares, each with a focus description.
  - Race-distance readiness: your longest swim, bike and run against your event's distances.
  - Weekly hours by sport, discipline split and weekly distance.
  - 90- and 30-day fitness trends.
  - Scheduled workouts and your 10 latest activities.
- **Resting HR and intensity**
  - 30-day resting heart rate.
  - Garmin's load focus (aerobic low, aerobic high and anaerobic, against your target ranges).
  - Acute and chronic load.
  - Aerobic and anaerobic training effect for each session.
- **Devices and FTP**
  - FTP history with W/kg, plus Garmin's own FTP estimate.
  - A log of readings from in-training devices: weight sensors, bike sensors, Wahoo.
  - The devices on your Garmin account.
- **Settings**
  - Edit your race and season phases.
  - Log FTP tests and device readings.
  - Refresh from Garmin.

Phase colours are set automatically from words in a phase's name:

| Word in name | Colour |
|---|---|
| strength | raspberry |
| power | orange |
| power endurance | gold |
| endurance | green |
| capacity | blue |
| mock (or "race sim") | plum |

There's a light and a dark mode; it starts in the one your computer uses.

## Download the app (easiest)

Go to this repository's **[Releases](../../releases/latest)** page and download the file for your computer:

| Computer | Download | Then |
|---|---|---|
| Windows 10 or 11 | `Training-Dashboard-Windows.zip` | Unzip it and double-click **Training-Dashboard.exe** |
| Mac with Apple silicon (M1 or later) | `Training-Dashboard-macOS.zip` | Unzip it, right-click **Training-Dashboard** and choose **Open** |
| Linux | `Training-Dashboard-Linux.tar.gz` | Extract it and run `./Training-Dashboard` |

The first time it opens, a window asks for your Garmin email, password and MFA code if you use one. Your password goes only to Garmin and isn't saved. The dashboard then opens in your browser. Keep that window open while you use it, and close it to stop.

Your data and Garmin sign-in are kept in a **TrainingDashboard** folder in your home folder. To sign in again, run the app with `--login`, or delete `TrainingDashboard/.garminconnect`.

**"Unknown publisher" warnings:** the app isn't code-signed, so Windows may show "Windows protected your PC". Choose **More info → Run anyway**. On a Mac, use right-click → **Open** the first time. Only download it from this repository's Releases page.

### For the repository owner: publishing the downloads

The downloads are built automatically by GitHub Actions (`.github/workflows/release.yml`):

1. Push this project to GitHub.
2. Go to **Releases → Draft a new release**, create a tag such as `v1.0.0`, and click **Publish release**.
3. About 10 minutes later, the Windows, macOS and Linux files appear on that release.

To try a build without releasing, open **Actions → Build downloadable app → Run workflow**. The files appear under that run's **Artifacts**.

To build one yourself, use `pip install -r requirements.txt pyinstaller` and then `pyinstaller training.spec`. The app is in `dist/`.

## For coaches: keep your athletes' dashboards in step with you

You can manage your athletes' **race and season phases** from your own copy. Any change you make reaches their dashboards on its own, within about 10 minutes. Each athlete's Garmin data, FTP tests and device log stay private to them.

**Set it up once per athlete:**

1. In your dashboard, go to **Settings** and set up that athlete's race and phases. Phases can include names, dates, focus descriptions and TBC statuses.
2. Under **Coach plan**, enter your name and an optional note, such as "Test week: go hard on Thursday", then click **Export plan for athletes**. This downloads a `training-plan.json` file.
3. Put the file online at a fixed link. The simplest place is your GitHub repository:
   1. Open the repository and choose **Add file → Upload files**.
   2. Upload it as `plans/<athlete-name>.json`.
   3. Open the file on GitHub and click **Raw**. The address in your browser is the link.
4. Send that link to the athlete. They paste it into **Settings → Coach plan link** and click **Use this plan**.

**Change their plan later:** edit it in your dashboard, export it again, and upload it over the same file in `plans/`, keeping the same name. Their dashboard updates on its own. The note you add appears as a green banner at the top of their dashboard.

While a coach plan is in use, the athlete's race and phase editors are locked and show who set them. They can click **Stop using a coach plan** at any time to go back to their own.

> Raw links only work for a **public** repository, so anyone browsing the repository can see the files in `plans/`. Plans hold only phase names, dates and notes, but keep anything private out of them. For more privacy, use any `https://` link that returns the file, such as an unlisted file on your own website. A separate public repository just for plans also works.

## Updates to the app

When you publish a new release, as described above, everyone using the downloadable app sees a yellow banner at the top of their dashboard: **"A new version is available - Download it"**. Each person downloads and replaces the app file. Their data and Garmin sign-in are kept, because they live in the `TrainingDashboard` folder, not in the app.

## Before you start: how the Garmin connection works

Garmin doesn't offer a public API for personal data. This app uses the open-source [`garminconnect`](https://github.com/cyberjunky/python-garminconnect) library, which signs in to Garmin Connect the way the Garmin website does.

- You sign in **once**, on your own computer. The app then stores Garmin's login **tokens** (not your password) in `.garminconnect/`.
- Treat that folder like a password. It's in `.gitignore`, so never commit it or share it.
- This approach is unofficial and can break if Garmin changes its sign-in. If it does, update the library with `pip install -U garminconnect`.
- Use it with your own account only.

## Run from source (for developers)

You need **Python 3.10 or newer**.

```bash
git clone https://github.com/<you>/training-dashboard.git
cd training-dashboard
python -m venv .venv
# Windows:  .venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate
pip install -r requirements.txt

python server/app.py --login   # one time: your Garmin email, password and MFA code if you use one
python server/app.py           # start the dashboard
```

Then open **http://127.0.0.1:8100**.

### Install it as an app

- **Chrome or Edge:** open the dashboard, then choose **Install Training Dashboard** from the address bar or the ⋮ menu. It gets its own window and a desktop or Start-menu icon.
- **Safari on iPhone or iPad:** use Share → **Add to Home Screen**. This works only when the server can be reached from the phone; see "Use it from other devices".

The server needs to be running for new data to load. To start it automatically:

- **Windows:** add `python server\app.py` to Task Scheduler at log-on.
- **macOS or Linux:** use a launchd job or a systemd service.

## First steps in the app

1. **Settings → Your goal event:** enter what you're training for (for example "London T100" or "Manchester Marathon"), the date and the distances. Leave a distance at 0 for sports your event doesn't include.
2. **Settings → Season phases:** add one row per phase with name, start date, end date, focus and an optional status such as "TBC". The repo ships with an example plan; replace it with yours.
3. **Settings → Log an FTP test / Log a device reading:** add results as you get them.

Your own data is saved in `data/*.json` and isn't committed to git.

## Use it from other devices (optional)

By default the server only listens on your own computer. To open it from your phone on the same network:

```bash
T100_APP_TOKEN="a-long-random-string" python server/app.py --host 0.0.0.0
```

Then on the phone:

1. Go to `http://<your-computer's-IP>:8100`.
2. Open **Settings** and paste the same string into **App token**.

The server refuses to listen beyond your computer without a token. If you put it on the internet, run it behind HTTPS, for example with Caddy, Cloudflare Tunnel or Tailscale.

## Docker

```bash
docker compose build
docker compose run --rm t100 python server/app.py --login   # one time
docker compose up -d
```

Edit `T100_APP_TOKEN` in `docker-compose.yml` first, then enter the same token in the app's **Settings** tab. Your tokens and data are saved in `./data`.

## Configuration

| Variable | Default | What it does |
|---|---|---|
| `T100_HOST` / `T100_PORT` | `127.0.0.1` / `8100` | Where the server listens |
| `T100_APP_TOKEN` | *(none)* | Token required on every data request; needed when listening beyond localhost |
| `T100_DATA_DIR` | `./data` | Where your race, phases, FTP tests and device log are saved |
| `GARMINTOKENS` | `./.garminconnect` | Where Garmin login tokens are saved |
| `T100_CACHE_SECONDS` | `900` | How long Garmin answers are cached |
| `T100_COACH_SECONDS` | `600` | How often a coach plan link is re-read |
| `GARMIN_EMAIL` / `GARMIN_PASSWORD` | *(none)* | Optional; used to sign in again if the tokens expire |

## Project layout

```
server/app.py        Flask server: Garmin sign-in, data endpoints, your saved data, serves the app
server/version.py    Version and repository, filled in automatically by each release build
server/launcher.py   Entry point for the downloadable app (sign-in prompt, opens the browser)
training.spec            PyInstaller build file for the downloadable app
.github/workflows/release.yml   Builds the Windows, macOS and Linux downloads on each release
web/index.html       The dashboard (markup, styles and drawing code)
web/dash-shim.js     Loads each table from the server and redraws the page when data changes
web/settings.js      The Settings tab
web/sw.js, web/manifest.webmanifest, web/icons/   Installable-app files
web/fonts/           Montserrat (SIL Open Font License)
web/d3.min.js        d3 v7 (ISC licence)
data/*.example.json  Example race and season plan
```

## Troubleshooting

- **"Not signed in to Garmin"**: run `python server/app.py --login` again.
- **A card says "Failed to load"**: open the browser console to see the error, or check the server window. Garmin sometimes rate-limits; wait a few minutes and use **Settings → Refresh from Garmin**.
- **Numbers look out of date**: sync your watch with the Garmin Connect app, then refresh. Answers are cached for 15 minutes.

## Licence

MIT for this project's code. Montserrat is under the SIL Open Font License, d3 under ISC, and `garminconnect` under MIT. This project isn't affiliated with or endorsed by Garmin.
