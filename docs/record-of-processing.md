# Record of processing activities (UK GDPR Article 30)

Controller and processor: Halia (legal entity and registered address to be inserted). Data
protection contact: privacy@haliascore.com. ICO registration: number and tier to be inserted once
confirmed. Last reviewed: 21 September 2026. Review on any change to a processing activity and at
least annually.

Halia keeps this record because its processing is regular and profiling-based; the small-organisation
exemption in Article 30(5) does not apply.

## Part A. Processing on behalf of merchants (Halia as processor, Article 30(2))

| Item | Detail |
| --- | --- |
| Controllers | Each merchant using Halia; names and contacts held in the merchant account record |
| Categories of processing | Reading customer and order records from the merchant's commerce platform; scoring in memory for potential value; matching against public-register reference tables (HM Land Registry, Companies House, Charity Commission and named foreign equivalents); writing grades, reasons, outreach records and appointments to the customer record in the merchant's platform; drafting message text at a team member's request; rendering messages for a team member to send from their own account |
| Categories of data subjects | The merchant's customers and prospective customers; the merchant's staff |
| Categories of personal data | Name, email, phone, billing and shipping address, order history and products, open baskets, marketing-consent status, derived grade and reasons; staff names, work emails, sign-in tokens, and the record of which staff member contacted which customer |
| Special category data | None processed; origin-proxy signals off by default |
| Recipients | The merchant's own platform (write-back); the merchant's connected tools at its instruction (Klaviyo, Mailchimp, HubSpot, Slack); Anthropic for drafting when enabled |
| Transfers outside the UK/EEA | Anthropic (United States), only when the merchant enables AI drafting; UK Addendum to the EU SCCs plus transfer risk assessment |
| Retention | Customer data: in memory only, at most five minutes per scoring run, never written to disk. Grades and records: in the merchant's platform, under the merchant's retention. Aggregate counters: indefinitely, no customer identifier |
| Security measures | TLS in transit; encrypted credentials at rest; per-merchant session and token authentication; least-privilege access; no customer database for staff to access; incident response per docs/security-incident-response.md |

## Part B. Processing for Halia's own purposes (Halia as controller, Article 30(1))

| Activity | Purpose | Lawful basis | Data subjects | Personal data | Recipients | Retention |
| --- | --- | --- | --- | --- | --- | --- |
| Merchant accounts | Providing and billing the service | Contract (Article 6(1)(b)) | Merchant owners and staff | Name, work email, store domain, encrypted platform credentials, billing status, seat records | Render (hosting), Stripe (billing) | Account lifetime plus 6 years for billing records |
| Team sign-in | Securing the console and content editor | Legitimate interests (Article 6(1)(f)) | Halia staff and contractors | Name, work email, session tokens | Render | While on the team; removed on departure |
| Transactional email | Sign-in links, alerts, results, monthly recaps to merchants | Contract; legitimate interests for service messages | Merchant owners and staff | Email address, message content (may include a customer's first name in an alert) | Brevo (EU) | Brevo logs per its retention; Halia holds send counts only |
| Marketing email | Newsletter and lifecycle journeys to prospects and merchants | Consent (Article 6(1)(a)); soft opt-in for existing merchants; PECR reg. 22 | Prospects, merchants | Email, name, journey state, suppression list | Brevo | Until unsubscribe; suppression list kept indefinitely to honour it |
| Website and blog | Publishing the site; contact form | Legitimate interests | Visitors, enquirers | Contact-form name, email, message; no analytics cookies | Render, Brevo (relay of the form) | Enquiries 12 months |
| Usage metrics | Operating and improving the service | Legitimate interests | None identifiable | Per-merchant weekly counters and per-signal feedback tallies; no customer identifier | None | Indefinitely, aggregate only |
| Public-register reference tables | Building the scoring reference data | Legitimate interests | Persons named in open registers (company controllers, charity trustees) | Name, company or charity, tier; no contact details; held only on the operator's machine, never served or committed | None | Rebuilt from the source on each refresh; the previous table is replaced |

The reference-table activity is the one place Halia holds personal data drawn from public sources as a
controller. It processes only what the registers publish under their open licences, holds no contact
details, and uses the tables solely to compare a merchant's records against them in memory.

## Part C. Transfers summary

| Flow | Direction | Mechanism |
| --- | --- | --- |
| EU merchant to Halia (UK) | EEA to UK | EU adequacy decision for the UK while in force |
| Halia (UK) to Brevo (France) | UK to EEA | UK adequacy regulations for the EEA |
| Halia to Anthropic (United States) | UK to US | UK Addendum to the EU SCCs; transfer risk assessment; only when a merchant enables AI drafting |
| Halia to Render | Within UK/EEA, region to be confirmed | None required if UK/EU region; otherwise UK Addendum |
