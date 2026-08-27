<?php
/**
 * Order webhooks to Halia. Uses WooCommerce's own WC_Webhook so delivery, retries and the
 * signature header behave exactly like any webhook a merchant creates by hand.
 */

if ( ! defined( 'ABSPATH' ) ) {
    exit;
}

class Halia_Webhooks {

    const TOPICS = [ 'order.created', 'order.updated' ];

    public static function init() {
        // Re-check on admin loads so a webhook someone deleted by hand comes back.
        add_action( 'admin_init', [ __CLASS__, 'ensure' ] );
    }

    private static function ours() {
        if ( ! class_exists( 'WC_Data_Store' ) ) {
            return [];
        }
        $store = WC_Data_Store::load( 'webhook' );
        $found = [];
        foreach ( $store->search_webhooks( [ 'limit' => 200 ] ) as $id ) {
            $wh = new WC_Webhook( $id );
            if ( $wh->get_name() && strpos( $wh->get_name(), 'Halia ' ) === 0 ) {
                $found[ $wh->get_topic() ] = $wh;
            }
        }
        return $found;
    }

    public static function ensure( $force = false ) {
        $c = Halia_Connect::connection();
        if ( empty( $c['webhook_url'] ) || ! class_exists( 'WC_Webhook' ) ) {
            return;
        }
        if ( ! $force && get_transient( 'halia_webhooks_checked' ) ) {
            return; // once an hour is plenty for a repair pass
        }
        set_transient( 'halia_webhooks_checked', 1, HOUR_IN_SECONDS );
        $have = self::ours();
        foreach ( self::TOPICS as $topic ) {
            $wh = $have[ $topic ] ?? new WC_Webhook();
            if ( $wh->get_id() && $wh->get_delivery_url() === $c['webhook_url'] && $wh->get_status() === 'active' ) {
                continue;
            }
            $wh->set_name( 'Halia ' . $topic );
            $wh->set_user_id( get_current_user_id() ?: 1 );
            $wh->set_topic( $topic );
            $wh->set_delivery_url( $c['webhook_url'] );
            $wh->set_secret( wp_hash( 'halia-' . $c['shop'] ) );
            $wh->set_api_version( 'wp_api_v3' );
            $wh->set_status( 'active' );
            $wh->save();
        }
    }

    public static function remove() {
        foreach ( self::ours() as $wh ) {
            $wh->delete( true );
        }
    }

    public static function status() {
        $have = self::ours();
        $n    = count( array_filter( $have, fn( $wh ) => $wh->get_status() === 'active' ) );
        return $n . ' of ' . count( self::TOPICS ) . ' active';
    }
}
