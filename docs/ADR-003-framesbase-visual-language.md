# ADR-003: Framesbase-inspired participant experience

## Status

Accepted for prototype

## Decision

Use the publicly visible Framesbase visual language as a reference: paper background, ink typography, acid-lime/orange/violet signal colors, rounded information cards, and quiet monospace metadata. A locally stored crop of the public `app.framesbase.app/og.png` card composition is used as a decorative visual reference at `public/framebase-cards.webp`.

## Access boundary

Framesbase library and background APIs require the user's authenticated browser session and return `401` without it. This environment cannot read or reuse Google browser cookies. No private content was bypassed or copied. Private library exports or screenshots can be added later with explicit authorization.

## Consequence

The participant-facing assessment feels warm and editorial while the research and review views remain available as secondary routes. The product does not depend on a third-party asset host at runtime.
