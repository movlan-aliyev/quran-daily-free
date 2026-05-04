# Quran daily email (free, no n8n)

Sends **20 ayahs** per run: **word table** = Arabic + Latin + **English gloss** + **Turkish gloss** (Quran.com), plus **heuristic “Okuma & dilbilgisi”** reminders (tecvid/nahiv hints — verify with a teacher). Full ayah **English** + **Turkish (Diyanet)**. Not scholar **iʿrāb** or **tafsir**.

Progress is stored in `data/progress.json`.

## Quick setup (Windows)

In PowerShell, from this folder:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
.\setup_all.ps1
```

That runs `pip install`, creates `.env` if missing, and registers the daily **10:30** task. Then put your **`SMTP_PASSWORD`** in `.env` and test with `python send_daily_quran.py`.

From [python.org](https://www.python.org/downloads/) — check “Add python to PATH”.

## 2. Install dependencies

Open PowerShell or Command Prompt in this folder:

```bat
python -m pip install -r requirements.txt
```

## 3. Configure email

1. Copy `config.example.env` to **`.env`** in this same folder.
2. Fill in **SMTP_HOST**, **SMTP_PORT** (usually `587`), **SMTP_USER**, **SMTP_PASSWORD**, **MAIL_FROM**, **MAIL_TO**.

Outlook often blocks plain SMTP; if login fails, use **Gmail + App Password** or **SendGrid** SMTP and set `MAIL_FROM` / `MAIL_TO` as needed.

## 4. Test manually

```bat
python send_daily_quran.py
```

Or double-click `run_once.bat`.

## 5. Schedule 10:30 Eastern

**Easiest:** Set Windows clock timezone to **Eastern**, then run (PowerShell):

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
cd C:\Users\rober\quran-daily-free
.\register_scheduled_task.ps1
```

The task runs at **10:30** in whatever timezone the PC uses. For Eastern all year, keep Windows on **(UTC‑05:00) Eastern Time** with automatic DST.

**Remove the task:**

```powershell
Unregister-ScheduledTask -TaskName QuranDailyStudyEmail -Confirm:$false
```

## Reset progress

Delete `data\progress.json` (or edit `surah` / `ayah` inside it). Next run starts from **2:1** again.

## GitHub Actions (no PC on — free tier)

Workflow: [`.github/workflows/daily-quran-email.yml`](.github/workflows/daily-quran-email.yml). It runs **daily on GitHub’s clock (UTC)** and can be triggered manually under **Actions → Daily Quran email → Run workflow**.

1. Push this folder as a GitHub repository ( **`data/progress.json` is tracked** so the next ayah is remembered between runs).
2. **Settings → Secrets and variables → Actions → New repository secret** — add the same values you use in `.env`:

   | Secret | Notes |
   |--------|--------|
   | `SMTP_HOST` | e.g. `smtp.gmail.com` |
   | `SMTP_PORT` | e.g. `587` |
   | `SMTP_USER` | SMTP login |
   | `SMTP_PASSWORD` | App password / SMTP secret |
   | `MAIL_FROM` | From address |
   | `MAIL_TO` | Your inbox |

   Optional (same as local `.env`): `OPENAI_API_KEY`, `OPENAI_MODEL`, `OPENAI_GUIDANCE`, `CHUNK_SIZE`.

3. **Cron is UTC**, not Eastern. The workflow comment shows `30 15 * * *` (≈ 10:30 **EST**); for **EDT** you may prefer `30 14 * * *`. Use [crontab.guru](https://crontab.guru) to adjust.
4. **Turn off the Windows scheduled task** if you use Actions only, or you may get **two emails** and conflicting progress:

   ```powershell
   Unregister-ScheduledTask -TaskName QuranDailyStudyEmail -Confirm:$false
   ```

After the first successful run, Actions commits an updated `data/progress.json`. If **branch protection** blocks the bot from pushing, allow **GitHub Actions** write access or push from a fork/bot rule in repo settings.

## Comparison to n8n

Same idea as the n8n workflow: one scheduled run, HTTP to `api.alquran.cloud`, HTML email. **$0** for software; you only need a working SMTP account.
