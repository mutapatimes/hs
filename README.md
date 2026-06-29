# Halia

Scores a retailer's customers from their order export and surfaces high-net-worth
"hidden VICs" — customers who behave like VICs but aren't tagged as such.

## Layout

```
halia/
├── main.py              # entry point: loads data, prints a summary
├── config.py            # all filesystem paths in one place
├── requirements.txt
├── scoring/             # scoring code (a Python package)
│   ├── __init__.py
│   └── loader.py        # loads the .xlsx export into a DataFrame
├── reference_data/      # curated lookup lists (tracked in git)
│   ├── postcodes/
│   ├── venues/
│   └── domains/
├── sample_data/         # customer data — LOCAL ONLY, git-ignored
│   └── sample.xlsx
└── tests/               # pytest tests
    └── test_loader.py
```

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
python main.py      # load data, run all signals, print the ranked hidden VICs
pytest              # run the tests
```

## How scoring works

Each signal (`scoring/signals/`) flags a customer and gives a reason. The
combiner (`scoring/combine.py`) runs them all, sums their weights into a
`signal_score`, lists the `reasons`, and marks a `hidden_vic` — a customer a
signal fired on who is NOT already tagged VIP/VIC. Tune weights in
`SIGNAL_WEIGHTS`.

## Data privacy

`sample_data/` holds personal data and is **never** committed (see `.gitignore`).
Only the reference lists and code live in the repo.
