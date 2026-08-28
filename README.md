# 🚀 Honest Degen Kalshi Auto Picker

Automated sports pick execution engine that ingests published picks from Google Sheets, evaluates market prices on **Kalshi**, calculates exact unit risk sizing with fractional contracts, and automatically executes orders on a free **GitHub Actions** cronjob.

---

## ⚡ Key Features

* **Real-Time Sheet Ingestion**: Reads directly from your Google Sheets CSV publish URL.
* **Smart Active Filter**: Only targets unsettled / pending picks (`Result == 'pending'` or blank).
* **Fractional Contract Sizing**: Uses Kalshi's fixed-point format (`count_fp`) to size bets to the exact penny based on your configurable unit size (default: **$0.50 / unit**).
* **Slippage Protection**: Calculates sheet implied probability and rejects market orders if the Kalshi ask is more than **10¢** above fair price.
* **100% Free Automation**: Runs on GitHub Actions on a 30-minute cron schedule with zero server costs.
* **Deduplication Ledger**: Commits `placed_trades.json` back to GitHub using SHA-256 trade hashing so trades are never duplicated across runs.
* **Discord Alerts**: Real-time rich embed notifications for placed trades, slippage skips, and errors.

---

## 📁 Repository Structure

```
honest-degen-auto-picker/
├── .github/
│   └── workflows/
│       └── auto_picker.yml      # GitHub Actions cron workflow
├── config/
│   ├── settings.py              # Configuration loader
│   ├── settings.json            # Local JSON settings (unit size, slippage, etc.)
│   └── team_mappings.json       # Team names to standard codes mapping
├── src/
│   ├── sheet_reader.py          # Google Sheets CSV fetcher and active pick parser
│   ├── odds_converter.py        # American odds <-> Kalshi cents and sizing logic
│   ├── kalshi_client.py         # Kalshi API v2 client with RSA-PSS signing
│   ├── market_matcher.py        # Resolves sheet picks to Kalshi market tickers
│   ├── notifier.py              # Discord webhook embed notifications
│   └── trader.py                # Core orchestration engine
├── tests/                       # Full pytest test suite (22 tests)
├── placed_trades.json           # State ledger tracking placed orders
├── main.py                      # Main entrypoint
├── requirements.txt             # Python dependencies
├── .env.example                 # Local environment template
└── README.md
```

---

## ⚙️ Configurable Settings

You can customize your unit size, slippage tolerance, and fractional trading options through any of the following methods (in order of precedence):

### 1. Direct JSON Settings (`config/settings.json`)
```json
{
  "unit_size_dollars": 0.50,
  "price_slippage_tolerance_cents": 10,
  "allow_fractional_contracts": true
}
```

### 2. Environment Variables / GitHub Secrets
Set `UNIT_SIZE_DOLLARS="1.00"` in `.env` or your GitHub Repository Secrets.

### 3. Command-Line Arguments (Local or Manual GitHub Runs)
```bash
python main.py --unit-size 0.75 --slippage 8 --dry-run
```

---

## 🛠️ GitHub Actions Setup (Free Hosting)

### 1. Push This Repository to GitHub
Create a **Public** repository on GitHub (free unlimited Actions runner minutes) and push this codebase.

### 2. Configure GitHub Secrets
Go to your repository on GitHub:
**Settings** $\to$ **Secrets and variables** $\to$ **Actions** $\to$ **New repository secret**

Add the following secrets:

| Secret Name | Description | Example / Default |
| :--- | :--- | :--- |
| `KALSHI_API_KEY_ID` | Your Kalshi API Key ID | `a1b2c3d4-e5f6-7890-abcd-1234567890ab` |
| `KALSHI_PRIVATE_KEY` | Your RSA Private Key (PEM format) | `-----BEGIN RSA PRIVATE KEY-----\n...\n-----END RSA PRIVATE KEY-----` |
| `KALSHI_ENV` | Kalshi Environment (`prod` or `demo`) | `prod` (or `demo` for testing) |
| `UNIT_SIZE_DOLLARS` | Dollar amount per 1 unit | `0.50` |
| `PRICE_SLIPPAGE_TOLERANCE_CENTS` | Max price premium in cents | `10` |
| `DISCORD_WEBHOOK_URL` | Discord webhook URL for alerts | `https://discord.com/api/webhooks/...` |

### 3. Enable Workflow Permissions
Go to **Settings** $\to$ **Actions** $\to$ **General** $\to$ **Workflow permissions**:
* Select **Read and write permissions** (allows the bot to commit `placed_trades.json` back to the repository).

---

## 💻 Local Quickstart & Testing

### 1. Install Dependencies
```bash
python -m venv venv
venv\Scripts\activate  # Windows (or `source venv/bin/activate` on Mac/Linux)
pip install -r requirements.txt
```

### 2. Run Test Suite
```bash
pytest -v
```

### 3. Run in Dry-Run Simulation Mode
```bash
python main.py --dry-run
```

---

## ⚙️ Sizing & Sizing Math

Given a pick with $U$ units, base unit size $\$S$ (default: \$0.50), and Kalshi contract ask price $P_{\text{cents}}$:

$$\text{Target Risk} = U \times S$$
$$\text{Price Dollars} = \frac{P_{\text{cents}}}{100}$$
$$\text{Contract Count} = \frac{\text{Target Risk}}{\text{Price Dollars}}$$

**Example:**
* **Pick:** 1.5 units @ -130 (Implied Price = 57¢)
* **Target Risk:** $1.5 \times \$0.50 = \$0.75$
* **Contracts (`count_fp`):** $\frac{\$0.75}{\$0.57} = 1.32 \text{ contracts}$
* **Actual Cost:** $1.32 \times \$0.57 = \$0.7524$
