# detectors/sale/_common.py
"""Shared crm.lead query fragments for the sales detectors.

Deduplicates the query shape, not the Odoo selection strings. Keeping the base
domain in one place prevents two detectors silently filtering different
opportunity sets.
"""


def open_opportunity_domain(company):
    """Base domain: live opportunities for `company`.

    `active = True` keeps only non-archived opportunities. Note that
    `active = False` is BROADER than "lost": leads are archived when lost, but
    also when merged, manually archived, or bulk-cleaned, and such leads may
    have no lost_reason_id. Do NOT treat `active = False` as a synonym for
    "lost" — if you need lost leads specifically, filter on the lost
    representation (lost_reason_id / the dedicated lost flag), not on `active`
    alone. For these detectors we want live, workable opportunities, so
    `active = True` is the correct filter regardless of why other leads were
    archived. Callers add further constraints (deadline, staleness, etc.).
    Won-stage exclusion is left to callers via `stage_id.is_won` — some
    detectors legitimately want won deals (e.g. velocity), so it is NOT baked
    in here.
    """
    return [
        ("type", "=", "opportunity"),
        ("active", "=", True),
        ("company_id", "=", company.id),
    ]
