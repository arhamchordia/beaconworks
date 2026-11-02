# BeaconWorks Ticket Dashboard: Product Documentation (v2)
Last updated: 20 June 2026

## What it does
Tracks support tickets per customer account, with status, category and urgency.
Adds Priority Scoring, a single score that combines urgency and account segment.

## Priority Scoring formula (v2)
score = (urgency_weight * 50) + (segment_weight * 50)

- urgency_weight: high = 1.0, medium = 0.6, low = 0.3
- segment_weight: Enterprise = 1.0, Mid-Market = 0.6, SMB = 0.4
