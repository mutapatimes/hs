<?php
/**
 * Plugin Name: Halia
 * Plugin URI:  https://haliascore.com
 * Description: Private client intelligence for luxury retail. Connects your WooCommerce store to Halia with one click.
 * Version:     0.1.0
 * Author:      Halia
 * Author URI:  https://haliascore.com
 * License:     GPL-2.0-or-later
 * License URI: https://www.gnu.org/licenses/gpl-2.0.html
 * Text Domain: halia
 * Requires at least: 6.0
 * Requires PHP: 7.4
 * WC requires at least: 7.0
 */

if ( ! defined( 'ABSPATH' ) ) {
    exit;
}

define( 'HALIA_VERSION', '0.1.0' );
define( 'HALIA_FILE', __FILE__ );
define( 'HALIA_DIR', plugin_dir_path( __FILE__ ) );

if ( ! defined( 'HALIA_APP_URL' ) ) {
    define( 'HALIA_APP_URL', 'https://haliascore.com' );
}

require_once HALIA_DIR . 'includes/class-halia-connect.php';
require_once HALIA_DIR . 'includes/class-halia-cart.php';
require_once HALIA_DIR . 'includes/class-halia-webhooks.php';

add_action( 'before_woocommerce_init', function () {
    if ( class_exists( \Automattic\WooCommerce\Utilities\FeaturesUtil::class ) ) {
        \Automattic\WooCommerce\Utilities\FeaturesUtil::declare_compatibility( 'custom_order_tables', __FILE__, true );
    }
} );

add_action( 'plugins_loaded', function () {
    if ( ! class_exists( 'WooCommerce' ) ) {
        add_action( 'admin_notices', function () {
            echo '<div class="notice notice-warning"><p>Halia needs WooCommerce to be installed and active.</p></div>';
        } );
        return;
    }
    Halia_Connect::init();
    Halia_Cart::init();
    Halia_Webhooks::init();
} );
