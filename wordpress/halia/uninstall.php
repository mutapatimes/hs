<?php
if ( ! defined( 'WP_UNINSTALL_PLUGIN' ) ) {
    exit;
}
$c = get_option( 'halia_connection' );
if ( is_array( $c ) && ! empty( $c['key_id'] ) ) {
    global $wpdb;
    $wpdb->delete( $wpdb->prefix . 'woocommerce_api_keys', [ 'key_id' => (int) $c['key_id'] ], [ '%d' ] );
}
delete_option( 'halia_connection' );
