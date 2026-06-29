# reference_data/ — curated reference lists (tracked in git)

Non-PII lookup lists used to enrich and score customers. Unlike `sample_data/`,
these **are** committed to the repo.

- `postcodes/hnwi_postcodes.csv` — ultra-prime UK postcode prefixes (HNWI signal).
- `postcodes/affluent_postcodes.csv` — broader affluent postcode prefixes (starter).
- `venues/luxury_venues.csv` — luxury hotels/clubs/stores used as address signals.
- `domains/wealth_employer_domains.csv` — wealth-signalling employer email domains
  (banking, private equity, hedge funds, wealth management, family offices).

Each file has a header row and a `tier` column (1 = strongest signal). These are
starter lists with a few examples — extend them with your own entries. Keep the
column names stable so the scoring code can rely on them.
