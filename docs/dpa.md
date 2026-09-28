# Data Processing Agreement (DPA) — DRAFT

**⚠️ DRAFT for lawyer review. Do not send to merchants until counsel has confirmed it for your
jurisdictions (UK GDPR, EU GDPR, and any others you sell into). This captures how Halia actually
processes data so a lawyer can finalise it quickly.**

This Data Processing Agreement forms part of the agreement between the merchant ("**Controller**") and
Halia ("**Processor**") for the Controller's use of the Halia application.

## 1. Roles

The Controller determines the purposes and means of processing its customers' personal data. Halia
processes that personal data only on the Controller's behalf and documented instructions, as a
Processor.

## 2. Subject matter and duration

Halia processes personal data for as long as the Controller uses the app. On termination or
uninstall, Halia deletes the Controller's stored data as described in Section 8.

## 3. Nature and purpose of processing

Halia reads the Controller's customer and order data through the Controller's own commerce platform
(Shopify, WooCommerce, BigCommerce or Centra, at the Controller's choice) to compute a private
potential-value score ("hidden VIC" grade) and to surface the reasons and a recommended next action,
so the Controller can prioritise personal outreach to high-value clients. Halia does not use the data
to make decisions producing legal or similarly significant effects on data subjects: a member of the
Controller's team always decides whether and how to act.

**3.1 Public-register matching (documented instruction).** As part of the scoring, and on the
Controller's instruction recorded here, Halia compares the Controller's records against reference
tables that Halia builds from publicly available open data: HM Land Registry price-paid data (area
property values by postcode district), the Companies House persons-with-significant-control and
company registers (control of an active company), the Charity Commission for England and Wales
register (trusteeship), and the equivalent open registers of other countries listed in the
Processing Schedule. The comparison happens inside Halia's processing memory against tables Halia
already holds. Halia does not send any customer identifier to a register, a data broker or any
other third party, and does not look up any individual customer. The Controller may withdraw this
instruction for any register in writing, and Halia will exclude that register from the Controller's
scoring.

**3.2 Messaging tools.** Halia provides the Controller's team with message templates, per-client
drafts and a guided sequence for messaging several clients. Every message is sent by a member of the
Controller's team from the Controller's own or the team member's own messaging account (email,
WhatsApp, SMS, LINE). Halia does not send marketing messages to the Controller's customers.

## 4. Types of personal data and categories of data subjects

- **Data subjects:** the Controller's customers, prospective customers, and site visitors.
- **Personal data:** name, email, phone, billing/shipping address, order history (including order
  totals, dates and products), open baskets, and marketing-consent status as recorded in the
  Controller's platform. Halia derives location-based and behavioural signals from this data and,
  under Section 3.1, matches it against public-register facts (area property values, control of a
  company, trusteeship of a charity). Halia does not process special category data, and by default
  does not use signals that would act as proxies for nationality, ethnicity or origin (see the DPIA
  support document).
- **Team data:** names, work email addresses and sign-in tokens of the Controller's staff who use
  Halia's tools, and the record of which staff member contacted which customer, which Halia writes
  into the Controller's own platform.

## 5. Controller instructions

Halia processes personal data only per this DPA and the Controller's use of the app. Halia will not
process the data for its own purposes, and will not sell the data.

## 6. Zero retention

Halia is designed for data minimisation. Customer and order records are processed in memory and
discarded within minutes (five minutes by default). Scores, grades, reasons, outreach records and
appointments are written back into the Controller's own platform as tags and metafields on the
customer record, where the Controller controls them. Halia's own database holds the Controller's
account, settings, encrypted platform credentials, and aggregate counts only; it holds no customer
record, no score, and no customer identifier. Halia does not build or keep a copy of the
Controller's customer database, and does not use the Controller's customer data to train or improve
any model for other customers of Halia.

## 6A. Electronic marketing and consent

The Controller is responsible for its own compliance with the Privacy and Electronic Communications
Regulations 2003 (and, for EU customers, the ePrivacy Directive as implemented locally) in respect of
any electronic marketing message its team sends to a customer, including messages drafted or
suggested by Halia and messages sent through Halia's guided messaging sequence. Halia displays the
customer's email and SMS marketing-consent status as recorded in the Controller's platform, and the
date of the customer's most recent contact, before a message is sent, so that the Controller's team
can act knowingly. Halia does not gate messages on that status, does not send messages itself, and
is not a party to the communication. The Controller will ensure its team is trained on when consent
or the soft opt-in applies and will honour opt-outs in its own platform.

## 7. Confidentiality and security

- Personnel with access to personal data are bound by confidentiality.
- Personal data is encrypted in transit (TLS) and secrets/tokens at rest; backups are encrypted.
- Access to protected-data endpoints is logged.
- Access is least-privilege. See the Security Incident Response Policy (docs/security-incident-response.md).

## 8. Return and deletion

On uninstall or request, Halia deletes the Controller's stored data. Halia implements Shopify's
mandatory privacy webhooks: `customers/redact`, `shop/redact`, and `customers/data_request`. Because
Halia does not retain customer records, redaction requests are satisfied by removing any transient
cache and the Controller's stored configuration and tokens.

## 9. Sub-processors

Halia uses a limited set of sub-processors to run the service. Because Halia retains no customer
data, no sub-processor receives a standing copy of the Controller's customers. The current list is
published at haliascore.com/privacy#subprocessors and, at the date of this DPA, is:

| Sub-processor | Purpose | Customer data involved | Region |
| --- | --- | --- | --- |
| Render Services, Inc. | Hosting and managed database for the Halia application | None stored; customer records pass through server memory during scoring | UK/EU region, confirmed at contract |
| Stripe Payments Europe, Ltd. | Subscription billing for the Controller's account | None; the Controller's billing details only | EU/UK |
| Brevo (Sendinblue SAS) | Transactional email to the Controller's team: sign-in links, alerts, results | The Controller's team addresses; a customer's first name may appear in an alert to the team | EU (France) |
| Anthropic, PBC | Drafting and polishing message text, unless the Controller turns AI drafting off in Settings | The text of one draft request at a time: the customer's name, grade, order count and last order date, the products bought, the reasons the client surfaced, and the conversation excerpt on the team member's screen. Not used for training under the provider's API terms; retained by the provider for its standard limited period unless a zero-retention agreement is in place | United States, under the UK Addendum to the EU SCCs |

Halia will inform the Controller of intended changes to this list at least 30 days in advance,
giving the Controller the opportunity to object. The Controller's own connected platforms (Shopify,
WooCommerce, BigCommerce, Centra, Klaviyo, Mailchimp, HubSpot, Slack) operate under the
Controller's own accounts and terms and are not Halia's sub-processors.

## 10. Assistance to the Controller

Taking into account the nature of processing, Halia assists the Controller in responding to data
subject requests and in meeting the Controller's security, breach-notification, and data-protection
obligations.

## 11. Personal data breaches

Halia notifies the Controller without undue delay after becoming aware of a personal data breach
affecting the Controller's data, with the information the Controller needs to meet its own obligations.

## 12. International transfers

Halia processes personal data in the United Kingdom and the European Economic Area. Transfers from
the EEA to the United Kingdom rely on the European Commission's adequacy decision for the United
Kingdom while it remains in force; transfers from the United Kingdom to the EEA rely on the United
Kingdom's adequacy regulations. The one onward transfer outside the UK and EEA is to Anthropic in
the United States for AI drafting, which occurs only when the Controller enables that feature, and
relies on the UK International Data Transfer Addendum to the EU Standard Contractual Clauses together
with a transfer risk assessment held by Halia. Should adequacy lapse, the parties will put the UK
Addendum or the EU Standard Contractual Clauses in place for the affected flow within 30 days.

## 13. Audits

Halia makes available information reasonably necessary to demonstrate compliance with this DPA and
allows for audits, subject to reasonable notice and confidentiality.

---

## Processing Schedule

| Item | Detail |
| --- | --- |
| Subject matter | Scoring the Controller's customers for potential value and supporting the Controller's team's personal outreach |
| Duration | For the term of the Controller's subscription; customer data held in memory for at most five minutes per scoring run |
| Nature | Reading customer and order records; scoring in memory; matching against public-register reference tables (Section 3.1); writing grades, reasons, outreach records and appointments to the customer record in the Controller's platform; drafting message text at the team's request |
| Purpose | Identifying and serving high-value clients through personal attention; never pricing, credit, eligibility or refusal |
| Data subjects | The Controller's customers and prospective customers; the Controller's staff |
| Personal data | As Section 4 |
| Public registers (UK) | HM Land Registry price-paid data; Companies House PSC and company registers; Charity Commission for England and Wales register; Registers of Scotland-derived area statistics |
| Public registers (other countries, where the Controller's customers are located) | France DVF property transactions; Dubai Land Department transactions; New South Wales Valuer General sales; Australian Taxation Office postcode statistics; Canada Revenue Agency FSA statistics; United States IRS SOI ZIP statistics |
| Storage of customer data by Halia | None |
| Location of processing | United Kingdom / EEA (Render); United States for AI drafting only (Anthropic) |

---

_Placeholders to finalise with counsel: legal entity name and address for "Halia", governing law,
the Render region, and the transfer risk assessment for Anthropic._
