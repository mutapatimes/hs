<?php
/**
 * Client pages on the store's own domain: yourstore.com/?halia-page=i/<token> (an appointment
 * invite) and ?halia-page=c/<slug> (the capture form). WordPress fetches the page from Halia and
 * serves it here, so a client only ever sees the store's address.
 */

if ( ! defined( 'ABSPATH' ) ) {
    exit;
}

class Halia_Pages {

    const PATTERN = '~^(i/[A-Za-z0-9._-]+|c/[A-Za-z0-9_-]+(/check)?)$~';

    public static function init() {
        add_action( 'wp_loaded', [ __CLASS__, 'maybe_serve' ], 5 );
    }

    public static function valid( $page ) {
        return is_string( $page ) && preg_match( self::PATTERN, $page ) === 1;
    }

    public static function maybe_serve() {
        if ( empty( $_GET['halia-page'] ) ) {
            return;
        }
        $page = wp_unslash( $_GET['halia-page'] );
        if ( ! self::valid( $page ) ) {
            status_header( 404 );
            exit;
        }
        $url = HALIA_APP_URL . '/' . $page;
        if ( ! empty( $_GET['by'] ) && strpos( $page, 'c/' ) === 0 ) {
            $url = add_query_arg( 'by', sanitize_text_field( wp_unslash( $_GET['by'] ) ), $url );
        }
        $args = [ 'timeout' => 20, 'headers' => [ 'Accept' => '*/*' ] ];
        if ( 'POST' === ( $_SERVER['REQUEST_METHOD'] ?? 'GET' ) ) {
            $args['headers']['Content-Type'] = 'application/json';
            $args['body'] = file_get_contents( 'php://input' );
            $resp = wp_remote_post( $url, $args );
        } else {
            $resp = wp_remote_get( $url, $args );
        }
        if ( is_wp_error( $resp ) || (int) wp_remote_retrieve_response_code( $resp ) !== 200 ) {
            status_header( 404 );
            exit;
        }
        nocache_headers();
        $type = wp_remote_retrieve_header( $resp, 'content-type' );
        header( 'Content-Type: ' . ( $type ? $type : 'text/html; charset=utf-8' ) );
        $disp = wp_remote_retrieve_header( $resp, 'content-disposition' );
        if ( $disp ) {
            header( 'Content-Disposition: ' . $disp );
        }
        echo wp_remote_retrieve_body( $resp ); // phpcs:ignore WordPress.Security.EscapeOutput
        exit;
    }
}
