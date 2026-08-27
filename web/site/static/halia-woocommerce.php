<?php
/**
 * Plugin Name: Halia for WooCommerce
 * Description: Optional helper for Halia (haliascore.com): one-tap cart links your team can send, and live baskets for the dashboard. Install by uploading this file to wp-content/mu-plugins/. Nothing is sent anywhere; Halia reads through your existing REST key.
 * Version: 1.0.0
 */
if ( ! defined( 'ABSPATH' ) ) { exit; }

/* 1) One-tap carts: /?halia-cart=PRODUCT:QTY,PRODUCT:QTY[:VARIATION] adds every item, then opens checkout. */
add_action( 'wp_loaded', function () {
    if ( empty( $_GET['halia-cart'] ) || ! function_exists( 'WC' ) || ! WC()->cart ) { return; }
    $added = 0;
    foreach ( explode( ',', sanitize_text_field( wp_unslash( $_GET['halia-cart'] ) ) ) as $item ) {
        $bits = array_map( 'absint', explode( ':', $item ) );
        $pid  = $bits[0] ?? 0; $qty = max( 1, $bits[1] ?? 1 ); $vid = $bits[2] ?? 0;
        if ( $pid && WC()->cart->add_to_cart( $pid, $qty, $vid ) ) { $added++; }
    }
    if ( $added ) {
        wp_safe_redirect( wc_get_checkout_url() );
        exit;
    }
}, 20 );

/* 2) Live baskets: GET /wp-json/wc-halia/v1/carts (your WooCommerce REST key authenticates, as with wc/v3). */
add_action( 'rest_api_init', function () {
    register_rest_route( 'wc-halia/v1', '/carts', array(
        'methods'             => 'GET',
        'permission_callback' => function () { return current_user_can( 'manage_woocommerce' ); },
        'callback'            => function () {
            global $wpdb;
            $rows = $wpdb->get_results( "SELECT session_key, session_value, session_expiry FROM {$wpdb->prefix}woocommerce_sessions
                                          WHERE session_expiry > UNIX_TIMESTAMP() ORDER BY session_expiry DESC LIMIT 500", ARRAY_A );
            $out = array();
            foreach ( (array) $rows as $r ) {
                if ( ! ctype_digit( (string) $r['session_key'] ) ) { continue; }          // logged-in customers only
                $sess = maybe_unserialize( $r['session_value'] );
                $cart = isset( $sess['cart'] ) ? maybe_unserialize( $sess['cart'] ) : array();
                if ( empty( $cart ) || ! is_array( $cart ) ) { continue; }
                $count = 0; $value = 0.0; $items = array();
                foreach ( $cart as $line ) {
                    $q = (int) ( $line['quantity'] ?? 0 ); $count += $q;
                    $value += (float) ( $line['line_total'] ?? 0 );
                    $p = wc_get_product( $line['variation_id'] ?: $line['product_id'] );
                    $items[] = array( 'title' => $p ? $p->get_name() : 'Item', 'qty' => $q );
                }
                if ( $count < 1 ) { continue; }
                $user = get_userdata( (int) $r['session_key'] );
                $out[] = array(
                    'customer_id' => (int) $r['session_key'],
                    'email'       => $user ? $user->user_email : '',
                    'value'       => round( $value, 2 ),
                    'count'       => $count,
                    'items'       => $items,
                    'updated'     => gmdate( 'Y-m-d', (int) $r['session_expiry'] - 2 * DAY_IN_SECONDS ),
                    'url'         => wc_get_cart_url(),
                );
            }
            return rest_ensure_response( $out );
        },
    ) );
} );
