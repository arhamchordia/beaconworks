# BeaconWorks Ticket Dashboard: Product Documentation (current, v3)
Last updated: 8 September 2026

## What it does
Tracks support tickets per customer account, with status, category and urgency.
New in this version: Priority Scoring (beta), which combines ticket urgency,
account segment and days open into a single 0 to 100 risk score.

## Priority Scoring formula (current, v3)
score = (urgency_weight * 40) + (segment_weight * 30) + (days_open_capped * 30 / 14)

- urgency_weight: high = 1.0, medium = 0.6, low = 0.3
- segment_weight: Enterprise = 1.0, Mid-Market = 0.6, SMB = 0.4
- days_open_capped: min(days since the ticket opened, 14)

## Access
Available to all authenticated internal users. No customer-facing view yet.

## Known limitation
Accounts missing from the customers table fail to resolve on the dashboard's
account-detail view (see engineering ticket TICKET-0008). Tracked, not yet
fixed as of this document's date.
