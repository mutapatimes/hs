=== Halia ===
Contributors: halia
Tags: woocommerce, clienteling, luxury, crm, customers
Requires at least: 6.0
Tested up to: 6.6
Requires PHP: 7.4
Stable tag: 0.1.0
License: GPLv2 or later
License URI: https://www.gnu.org/licenses/gpl-2.0.html

Private client intelligence for luxury retail. Connects your WooCommerce store to Halia with one click.

== Description ==

Halia grades every client in your book by capacity to spend, using your own order history. It finds the hidden top clients, the ones who have gone quiet, and the ones about to become important, then gives your associates the tools to act: a Chrome extension on your store admin, WhatsApp Web and Gmail, and an iPhone keyboard.

This plugin does three things:

* Connects your store to Halia with one click (it creates a WooCommerce API key for Halia; no keys to copy).
* Sends new and updated orders to Halia so scores stay current.
* Handles basket links associates send to clients, so a link fills the basket and opens checkout.

Halia does not store your clients' data. Scores are computed in memory from the store you connect and written back to your own customer records as tags and metadata.

== Installation ==

1. Install and activate WooCommerce.
2. Install and activate Halia.
3. Go to Halia in the admin menu and press Connect to Halia.
4. Your dashboard opens in a new tab and a sign-in link is emailed to you.

== Frequently Asked Questions ==

= Where is the data stored? =

In your WooCommerce store. Halia reads it with the API key created at connection and keeps only opaque identifiers.

= Can I disconnect? =

Yes. Disconnect on the Halia page removes the API key and the webhooks.

== Changelog ==

= 0.1.0 =
* First release: connect flow, order webhooks, basket links.
