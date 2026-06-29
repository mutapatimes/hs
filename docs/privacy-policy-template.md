# Halia — Privacy Policy (TEMPLATE — review with legal before publishing)

> A public privacy-policy URL is required to request Shopify Protected Customer Data access.
> This template reflects Halia's zero-retention architecture; have it reviewed by a lawyer
> and host it at a stable URL.

**Last updated:** _[date]_

## Who we are
Halia ("we") provides a clienteling-intelligence app that scores a merchant's existing
customers to surface high-potential clients. Contact: _[email]_.

## What data we process, and for how long
To produce a score we read, **from the merchant's Shopify store**, customer fields such as
name, email, phone, billing/shipping address, and order history. We process this data **only
in volatile memory** to compute a score and present it to the merchant. **We do not store
customer personal data** on our servers or databases. Transient in-memory data is discarded
within minutes and on every restart.

The only data we retain are the merchant's own API credentials (Shopify access token, Klaviyo
key), stored encrypted, solely to operate the service, and deleted when the app is uninstalled.

## How data is used
Solely to compute and display clienteling scores to the merchant, and — at the merchant's
direction — to write a grade back to their Shopify store or their own Klaviyo account. We do
not sell data, use it for advertising, or share it with third parties beyond the merchant's
own connected tools.

## Sub-processors
- _[Hosting provider — e.g. Render]_ (compute/database for encrypted credentials).
- The merchant's own connected platforms (Shopify, Klaviyo) act on the merchant's instruction.

## Security
TLS in transit; encryption at rest for stored credentials; least-privilege access;
data-minimisation and zero customer-data retention by design.

## Your rights (GDPR/CCPA)
Because we retain no customer personal data, erasure and access requests are satisfied
immediately. Merchants/end-customers may contact us at _[email]_; we also honour Shopify's
`customers/data_request`, `customers/redact`, and `shop/redact` requests automatically.

## Changes
We will post updates here with a revised "last updated" date.
