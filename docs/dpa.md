# Data Processing Agreement (template)

> **Template only. Review with a solicitor before use.** This document is a starting
> point for the data-processing terms between a merchant (the client) and Halia. It is
> not legal advice and has not been reviewed by a qualified data-protection lawyer. Do
> not present it to a paying client, or rely on it, until it has been adapted and signed
> off by a solicitor for your jurisdiction.

This Agreement governs the processing of personal data by **Halia** ("the Processor") on
behalf of **the Merchant** ("the Controller") in connection with the Halia clienteling and
customer-scoring service ("the Service"). It supplements the main service terms; where it
conflicts with them on data protection, this Agreement prevails.

## 1. Roles

- The **Merchant is the Controller**. The Merchant determines the purposes and means of the
  processing: it owns the customer relationship, decides to use the Service, and acts on the
  scores Halia surfaces.
- **Halia is the Processor**. Halia processes the Merchant's customer data only on the
  Merchant's documented instructions, as set out in this Agreement and the Service
  configuration.
- Halia does not sell, rent, or share the Merchant's customer data, and does not use it to
  train any model.

## 2. Subject-matter, duration, nature and purpose

- **Subject-matter:** scoring a Merchant's customers to surface likely high-value clients
  ("hidden VICs") for human-led outreach by the Merchant's team.
- **Duration:** for the term of the service relationship; processing of any given customer
  record is transient (see §6, zero-retention).
- **Nature:** read-only ingestion from the Merchant's connected platform, in-memory scoring,
  presentation of results to the Merchant, and optional write-back of a grade to the
  Merchant's own systems.
- **Purpose:** clienteling / customer analytics, to inform human relationship-building. The
  Service does not take any automated decision that produces a legal or similarly significant
  effect on a customer (see §10).

## 3. Categories of data subject and personal data

**Data subjects:** the Merchant's customers (and prospects who have transacted with the
Merchant).

**Categories of personal data processed:**

| Category | Examples | Why |
|---|---|---|
| Identity | name, email, phone | join orders to a person; outreach |
| Address | billing / shipping address, postcode, country | wealth-area and prime-residence signals |
| Commercial | order history, spend, order count, currency | the core wealth facts that drive scoring |
| Derived | score, grade, signal reasons | the Service's output |

**Special-category data:** the Service is **not** designed to process special-category data
(Article 9) and the Merchant must not configure it to do so. By default the Service does **not**
use nationality, ethnicity, name-origin, or similar origin proxies as scoring signals (see
`docs/dpia-lia-support.md`). These remain off unless the Merchant has documented a lawful basis
and the operator has explicitly enabled them for that tenant.

## 4. Processor obligations

Halia shall:

1. **Process only on instruction.** Process the personal data only on the Merchant's documented
   instructions (this Agreement and the Service configuration), unless required by law, in which
   case Halia will inform the Merchant first where lawful to do so.
2. **Confidentiality.** Ensure that anyone authorised to process the data is bound by
   confidentiality.
3. **Security.** Implement appropriate technical and organisational measures (see §5).
4. **Zero-retention.** Hold customer personal data in memory only, for the minimum time needed to
   score and present it, and never write it to disk or database (see §6).
5. **Subprocessors.** Engage subprocessors only as listed in §7, under written terms no less
   protective than this Agreement, and give the Merchant notice of intended changes so it can
   object.
6. **Data-subject requests.** Assist the Merchant, by appropriate technical and organisational
   measures and insofar as possible, to respond to requests to exercise data-subject rights
   (access, rectification, erasure, objection, restriction, portability). Because Halia retains
   no standing copy of customer data, most requests are satisfied at the Merchant's source
   system; Halia's redaction endpoints evict any transient cache on demand.
7. **Assistance.** Assist the Merchant in ensuring compliance with its security, breach-
   notification, and data-protection-impact-assessment obligations, taking into account the
   nature of processing and the information available to Halia.
8. **Breach notice.** Notify the Merchant without undue delay after becoming aware of a personal-
   data breach, with the information the Merchant reasonably needs to meet its own obligations.
9. **Deletion on termination.** At the end of the relationship, delete or return all personal
   data and delete existing copies, unless law requires storage. In practice this is immediate
   for customer data (none is retained) and means deleting the Merchant's stored platform
   credentials.
10. **Audit.** Make available the information necessary to demonstrate compliance and allow for
    and contribute to audits, including inspections, conducted by the Merchant or an auditor it
    mandates, subject to reasonable confidentiality and scheduling.

## 5. Security measures

- Encryption in transit (TLS) for all platform connections and the dashboard.
- Customer personal data processed **in memory only**, evicted on a short TTL, on restart, and
  on redaction.
- The only persisted secrets are the Merchant's platform credentials, stored **encrypted**
  (Fernet) and deletable on demand.
- Per-tenant authentication; no cross-tenant access; no staff-browsable database of customer
  data, because none exists.
- Principle of least data: only the fields the active signals read are processed.

See `docs/compliance.md` and `docs/architecture.md` for the concrete implementation.

## 6. Zero-retention

Halia does not maintain a standing copy of the Merchant's customer data. Records are read,
scored in RAM, presented, and discarded. No customer personal data is written to Halia's
database or disk. This is the central data-minimisation control of the Service.

## 7. Subprocessors

| Subprocessor | Role | Data it sees |
|---|---|---|
| Render | application hosting | data in transit / in memory during processing; stored: only encrypted credentials |
| Brevo | transactional email (alerts, onboarding) | the Merchant's and its staff's contact details; alert contents the Merchant configures |
| The Merchant's connected platform(s) (e.g. Shopify, WooCommerce) and the Merchant's own marketing tool (e.g. Klaviyo, Mailchimp) | source of data / optional write-back | the Merchant's own customer data, in the Merchant's own accounts |

The Merchant authorises these subprocessors. Halia will give notice of additions or
replacements so the Merchant may object on reasonable data-protection grounds.

## 8. International transfers

Where processing involves a transfer of personal data outside the UK / EEA, Halia will ensure
an appropriate safeguard is in place (for example, adequacy or the relevant Standard Contractual
Clauses / UK Addendum) and will document it. The Merchant is responsible for the transfer terms
of its own connected platforms.

## 9. Liability, term, and changes

This Agreement runs for the term of the service relationship and survives to the extent needed to
give effect to deletion and audit obligations. Changes must be agreed in writing. Liability is as
set out in the main service terms.

## 10. Profiling and automated decision-making

The Service produces a **score and grade** to inform a **human** at the Merchant who decides
whether and how to reach out. It does not make a decision that produces a legal or similarly
significant effect on a customer, and its effect is to **elevate** attention, never to withhold
a service. Scoring uses **wealth, work, and address facts**; it does **not** use nationality,
ethnicity, or name-origin signals by default. The Merchant remains the Controller of any outreach
decision. See `docs/dpia-lia-support.md` for the supporting assessment and `docs/privacy-notice-profiling.md`
for the notice wording the Merchant should give its customers.

---

*Halia retains no standing copy of customer data; the strongest data-protection control here is
that there is almost nothing to protect at rest.*
