# Data handling policy

The rules for every byte of customer data Halia touches, and the controls that enforce them. Each
rule names its control; a rule with no control is a wish, and this document has none of those.

## 1. Real customer data never enters the repository

A retailer's export lives in the vault, a directory outside the checkout that only the operator's
user can read (`HALIA_REAL_DATA_DIR`, default `~/HaliaVault`, mode 700, files 600). The
repository's `sample_data/` holds synthetic files only.

Controls: `.gitignore` excludes `sample_data/` and every `*.xlsx`; `halia.datavault.real_source`
resolves exports by name from the vault and refuses a path inside the repository;
`scoring.loader.load_data` redirects a repo path to its vault copy and refuses a real file found
inside the checkout; `tests/test_datavault.py` asserts `sample_data/` holds only synthetic files.

## 2. Anything public is built from synthetic data only

Every page, image or document under `web/` or `docs/` is generated from a file named
`synthetic_*.xlsx` or written by hand with invented people.

Controls: `halia.datavault.public_safe_source` is the only door the demo builders take, and it
refuses by name before reading; the scanner (`scripts/check_no_pii.py`, rules in
`halia.datavault.scan_text`) refuses tracked text with the tells of a real consumer export; the
pre-commit hook runs it on every commit; CI runs it as the first job and the test suite runs it
over the whole tree; the app calls `assert_public_tree_clean` before serving a request and refuses
to start if the public tree carries a real export. A leak cannot be committed, merged, or deployed.

## 3. Halia's server retains no customer record

Customer and order data are processed in memory, held only while the store is in use (refreshed hourly
for up to twelve hours after the store last opened Halia, released within an hour of the last use, and
cleared by any restart), and never written to disk. Results
are written into the merchant's own store. Halia's database holds merchants, staff, encrypted
credentials and aggregate counters.

Controls: `halia/cache.py` is the only place customer data rests, RAM with a TTL, evicted on
uninstall and redaction; `tests/test_datavault.py::test_the_schema_holds_no_customer_table` fails
if any table gains customer-shaped columns; the legacy customer tables are dropped on every
deploy; `tests/test_halia_api.py` proves two populated shops never see each other's book.

## 4. No person reaches a log line

Controls: Halia's access log records paths and hashed caller references only;
`halia.logredact` masks email addresses and long digit runs in every record on the root, Halia
and uvicorn loggers, installed at app start; `tests/test_datavault.py` pins the redaction.

## 5. Third parties receive the minimum, under contract

Only the sub-processors listed in the privacy policy receive anything, and none receives a
standing copy of a merchant's customers. The AI drafting provider receives one draft request at a
time, only when a merchant enables the feature, under the UK Addendum.

Controls: `docs/dpa.md` sub-processor table and transfer clause; `docs/record-of-processing.md`;
the public list at `/privacy#subprocessors` with 30 days' notice of changes.

## 6. When it goes wrong

Follow `docs/security-incident-response.md`: contain, assess, notify the controller without undue
delay (Article 33(2)), record. Incident records are kept privately, outside this repository.

## Operator checklist, every time real data is handled

- [ ] The file is in the vault, not the repository, and was never in the repository.
- [ ] The script was given the file's name, not a path inside the checkout.
- [ ] Nothing under `web/` or `docs/` was rebuilt while the real file was the source.
- [ ] `python scripts/check_no_pii.py` is clean before the commit.
- [ ] Local build outputs (`output/`) made from the real file are deleted when the work is done.
