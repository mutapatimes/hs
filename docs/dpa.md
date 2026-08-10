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

Halia reads the Controller's customer and order data through the Shopify Admin API to compute a
private potential-value score ("hidden VIC" grade) and to surface the reasons and recommended next
action, so the Controller can prioritise personal outreach to high-value clients. Halia does not use
the data to make decisions producing legal or similarly significant effects on data subjects.

## 4. Types of personal data and categories of data subjects

- **Data subjects:** the Controller's customers, prospective customers, and site visitors.
- **Personal data:** name, email, phone, billing/shipping address, and order history (including order
  totals and dates). Halia derives location-based and behavioural signals from this data.

## 5. Controller instructions

Halia processes personal data only per this DPA and the Controller's use of the app. Halia will not
process the data for its own purposes, and will not sell the data.

## 6. Zero retention

Halia is designed for data minimisation. It processes customer and order records to compute the score
and **retains the resulting score and signals, not the underlying customer records**. Halia does not
build or keep a standalone copy of the Controller's customer database.

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

Halia uses a limited set of sub-processors to run the service (for example, cloud hosting). Halia
maintains a current list and will inform the Controller of intended changes, giving the Controller the
opportunity to object. **List your sub-processors here** (e.g. Render for hosting; Stripe for
non-Shopify billing; any email/LLM provider).

## 10. Assistance to the Controller

Taking into account the nature of processing, Halia assists the Controller in responding to data
subject requests and in meeting the Controller's security, breach-notification, and data-protection
obligations.

## 11. Personal data breaches

Halia notifies the Controller without undue delay after becoming aware of a personal data breach
affecting the Controller's data, with the information the Controller needs to meet its own obligations.

## 12. International transfers

Where personal data is transferred across borders, the parties rely on a lawful transfer mechanism
(for example, UK/EU Standard Contractual Clauses / the UK Addendum). **Confirm the mechanism with
counsel based on where you host and operate.**

## 13. Audits

Halia makes available information reasonably necessary to demonstrate compliance with this DPA and
allows for audits, subject to reasonable notice and confidentiality.

---

_Placeholders to finalise with counsel: legal entity name and address for "Halia", governing law,
the sub-processor list, and the international-transfer mechanism._
