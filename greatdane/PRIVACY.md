# Dane privacy notes

- Push: like Firefox, Dane keeps a connection to Mozilla's push service (`wss://push.services.mozilla.com/`) for web notifications; Mozilla sees your IP address, a random per-install ID and the endpoints of sites you've allowed, but message contents are end-to-end encrypted. It can be turned off with `dom.push.enabled=false`.
