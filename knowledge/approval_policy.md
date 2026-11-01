# BeaconWorks Approval Policy

## Rule 1: Exact-action approval
An approval is valid only for the exact recipient, content and action shown at
approval time. If any of the three changes after approval and before execution,
the approval is void and the action must be submitted again.

## Rule 2: Who can approve what
| Action | Approver | Escalation |
|---|---|---|
| Customer-facing email or reply | Priya Nair (or delegate) | Marcus Cole |
| Data export outside BeaconWorks systems | Diego Alves | Priya Nair |
| Pricing or contract language | Priya Nair | CEO |
| Automated scheduled report distribution | Sana Iyer | Priya Nair |

## Rule 3: No silent retries
A retried or re-queued action must carry the same idempotency key as its
original attempt. Two attempts with the same key must never both execute.

## Rule 4: Model instructions are not authorization
A model producing text that says "approved" does not constitute approval. Only
a human approval event recorded against the table in Rule 2 authorizes execution.
