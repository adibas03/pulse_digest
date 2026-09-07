# Pulse — Build Specification (v1)

**Technical module name:** `pulse_digest`
**Display name:** Pulse
**Tagline:** Daily exception digest for Odoo — find what needs attention across Accounting and Sales
**Target versions:** Odoo 18 Community, Odoo 19 Community
**Timeline:** 10 working days, scoped to Accounting + Sales/CRM

---

## 1. Strategic context

This module is built primarily as evidence for an Odoo R&D application. Secondary goal: a useful module that real SMEs install. Every architectural decision is made with both lenses in mind. When they conflict, signal-to-reviewer wins on internal design (extensibility, code quality, tests) and user value wins on UX surface (defaults, configuration screens, store copy).

The module is positioned against Odoo's built-in `digest` module, not against generic "daily summary" apps. The differentiation lives in five places:

1. **Records, not just counts.** The built-in digest reports "you have 12 new opportunities." Pulse reports "these 7 invoices are overdue, sorted by amount." Lists, not totals.
2. **Anomaly detection.** Statistical detectors flag deviations from baseline — payment delays jumping vs. an 8-week mean, deal velocity dropping, etc.
3. **Multi-channel delivery.** Email, in-app notification, WhatsApp (19+ only), all toggleable per user.
4. **Per-user filtering.** Each user receives a digest scoped to records they own (`user_id`, `team_id`, etc.), not the company-wide firehose.
5. **Free + extensible.** Odoo's built-in custom KPIs require Studio (Enterprise paid feature). Pulse's detector framework is extensible via plain Python modules under LGPL-3.

The store listing leads with the comparison table (see §10) so this differentiation is immediate.

---

## 1b. API-drift verification (Odoo 19, checked Nov 2025)

Live verification of every Odoo API the spec touches, against the
`odoo/odoo@19.0` source on GitHub. Items below are recorded as
**CONFIRMED**, **CORRECTED**, or **TO VERIFY ON DAY 1**.

### Accounting

| Item                                                                                                                                                     | Status                 | Source / Note                                                                                                                                                                                                                                   |
| -------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `account.move.payment_state` is a Selection with `not_paid`, `in_payment`, `paid`, `partial`, `reversed`, `invoicing_legacy`, plus newer `blocked` value | CONFIRMED              | `PAYMENT_STATE_SELECTION` is imported from `account.models.account_move` in `addons/account/report/account_invoice_report.py` on the 19.0 branch; selection values stable since 15.0                                                            |
| `move_type` selection includes `out_invoice`, `out_refund`, `in_invoice`, `in_receipt`, `out_receipt`, `entry`                                           | CONFIRMED              | Confirmed via 19.0 source references in invoice report SQL                                                                                                                                                                                      |
| `state` selection includes `draft`, `posted`, `cancel`                                                                                                   | CONFIRMED              | Standard since 13+                                                                                                                                                                                                                              |
| `invoice_date_due`, `amount_residual`, `partner_id`, `company_id`, `invoice_user_id` are the right field names                                           | CONFIRMED              | Stable; `invoice_date_due` is the canonical due-date field                                                                                                                                                                                      |
| `account.move._get_reconciled_payments()` exists as a helper to walk reconciled payments                                                                 | **TO VERIFY ON DAY 1** | Helper has shifted across versions; if missing in 19, fall back to walking `matched_payment_ids` or reading `account.partial.reconcile` directly. Logic in `payment_delay_outlier` is correct either way; only the method name needs confirming |

### CRM

| Item                                                                                 | Status    | Source / Note                                 |
| ------------------------------------------------------------------------------------ | --------- | --------------------------------------------- |
| `crm.lead.type` is a Selection with `lead` and `opportunity` values                  | CONFIRMED | Stable across 14+                             |
| `date_last_stage_update` is a Datetime, defaulted to `fields.Datetime.now`           | CONFIRMED | Confirmed in 19.0 model source                |
| `date_deadline` is a Date field for expected closing                                 | CONFIRMED | Stable across 14+                             |
| `expected_revenue` is a Monetary field on `company_currency`                         | CONFIRMED | Stable; see `crm_lead.py` field declarations  |
| `stage_id.is_won` is the boolean indicating a won stage                              | CONFIRMED | `crm.stage.is_won` flag is standard since 12+ |
| `active = False` means "archived" (broader than "lost") — see `_common.py` docstring | CONFIRMED | Behaviour unchanged in 19                     |
| `user_id` is the salesperson assignment                                              | CONFIRMED | Stable                                        |
| `company_currency` is the currency-field relation used by Monetary fields            | CONFIRMED | Standard pattern across all versions          |

### Partner / credit limit

| Item                                                                                                   | Status    | Source / Note                                                                                          |
| ------------------------------------------------------------------------------------------------------ | --------- | ------------------------------------------------------------------------------------------------------ |
| `res.partner.credit` (computed: current outstanding AR balance)                                        | CONFIRMED | Confirmed in 19.0 `partner.py` ("amount of their generated incoming/outgoing account moves")           |
| `res.partner.credit_limit` (admin-configured threshold)                                                | CONFIRMED | Same source                                                                                            |
| `res.partner.use_partner_credit_limit` is the gating toggle                                            | **CORRECTED (this iteration)** | Field exists but is a non-stored compute (`compute`/`inverse`, no `store`/`search`) — cannot appear in a search domain (`ValueError: ...use_partner_credit_limit to SQL because it is not stored`). It also means something narrower than "gating toggle": `True` only when a partner's `credit_limit` override differs from the company default, not "credit limit checking is active for this partner." Removed from `credit_limit_breach`'s domain entirely — `credit_limit`/`credit` already resolve the effective (override-or-default) limit on their own, so no extra flag is needed. |
| `res.partner.company_id` is nullable (shared partner) — handled via Python `.filtered` in the detector | CONFIRMED | Multi-company partner pattern unchanged                                                                |

### Mail templates

| Item                                                                                  | Status                 | Source / Note                                                                                                                                                                                                                       |
| ------------------------------------------------------------------------------------- | ---------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `mail.template` is the right model; `send_mail(res_id, email_values=...)` is the call | CONFIRMED              | Stable since 13+                                                                                                                                                                                                                    |
| `t-out` (escape-safe) and `t-raw` (raw-html) are current QWeb idioms                  | CONFIRMED              | `t-raw` deprecated nowhere in 19; `t-out` is the new safer default                                                                                                                                                                  |
| `ctx.get('...')` works inside `mail.template` body_html for runtime context injection | **TO VERIFY ON DAY 1** | The pattern works, but in 19 the recommended is to pass values through `email_values` and reference them on the record. If `ctx.get` is unreliable, switch to passing values through a temporary record field. Logic stays the same |

### WhatsApp — CORRECTED in this verification pass

| Item                                                                                                       | Status        | Source / Note                                                                                                                                                                  |
| ---------------------------------------------------------------------------------------------------------- | ------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Sending mechanism** — original spec had `whatsapp.template._send_message(phone, template_variables=...)` | **CORRECTED** | This method does not exist. The correct API is `whatsapp.composer` with `with_context(active_model=..., active_ids=...)` then `action_send_whatsapp_template()`                |
| **Variable passing** — original spec used `template_variables={...}` dict                                  | **CORRECTED** | Variables are typed fields on the composer (`free_text_1`, `free_text_2`, ...), mapped 1:1 to template free-text slots. Confirmed via Odoo SaaS 19.1 forum guidance (Mar 2026) |
| **Detection of WhatsApp availability** — original spec checked `"whatsapp.template" in env`                | **CORRECTED** | Now checks `"whatsapp.composer" in env` — what we actually invoke                                                                                                              |
| **Pre-approved template** is a Meta Business requirement (24-hour conversation window etc.)                | CONFIRMED     | WhatsApp Business Platform requirement, not Odoo-specific; deployment concern documented in spec                                                                               |
| **Template XML id** should be configurable via `ir.config_parameter`, not hardcoded                        | **CORRECTED** | Hardcoded `pulse_digest.whatsapp_template_xmlid` removed; admins now set the parameter and can swap templates without code                                                     |

### Cron

| Item                                                                       | Status    | Source / Note                    |
| -------------------------------------------------------------------------- | --------- | -------------------------------- |
| `ir.cron` with `state='code'`, `code='model._cron_run_digests()'`          | CONFIRMED | Standard pattern unchanged in 19 |
| `interval_type` values include `'hours'`                                   | CONFIRMED | Stable                           |
| `fields.Datetime.context_timestamp(...)` for timezone-aware "current hour" | CONFIRMED | Standard helper since 12+        |
| `ir.cron.numbercall` / `doall` fields                                     | **CORRECTED (this iteration)** | Both removed from `ir.cron` starting in Odoo 18, carrying into 19 — there is no call-count-limit field anymore; a cron just runs on `interval_number`/`interval_type` until `active` is turned off. Writing `numbercall` in `data/pulse_cron_data.xml` raises "Invalid field" and blocks module install. Simply omit it — the built cron doesn't set it. |

### Security / groups — corrected this iteration (not in original Nov 2025 pass)

| Item                                                                       | Status                          | Source / Note                    |
| --------------------------------------------------------------------------- | -------------------------------- | ----------------------------- |
| `res.groups.users` (Many2many members field)                              | **CORRECTED** | Renamed to `user_ids` in Odoo 19. `res.groups.category_id` was also removed, replaced by `privilege_id` (Many2one to a new `res.groups.privilege` model, which itself carries `category_id`). |
| `res.users.groups_id`                                                     | **CORRECTED** | Renamed to `group_ids` in Odoo 19. The rename cascades to anywhere that read `user.groups_id` directly. |
| `res.groups` also gained `all_user_ids` (Many2many, computed)             | **NEW, used in the build** | "Users and implied users" — includes members who only qualify via `implied_ids` (e.g. an Administrator who implies Recipient). Used instead of `user_ids` when fanning out per-user runs, so an admin doesn't need separate explicit Recipient membership to be included. |

### Net result for the build

Two real corrections from the original Nov 2025 pass (WhatsApp send mechanism + template XML id configurability), two Day-1 verification items left (`_get_reconciled_payments` helper name, mail template `ctx.get` pattern). Three further corrections surfaced during this iteration's build, not caught by the original pass: `res.partner.use_partner_credit_limit` is non-stored/non-searchable and means something narrower than assumed; `res.groups`/`res.users` had `users`→`user_ids`, `groups_id`→`group_ids`, and `category_id`→`privilege_id` renames in Odoo 19; `ir.cron.numbercall`/`doall` were removed in Odoo 18+. All three are now reflected in the tables above and in the built code.

---

## 2. Module manifest

**Actual `data` list differs**: `data/mail_template_data.xml` is still not
included (§6/§14), and `wizards/pulse_run_wizard_views.xml`,
`views/pulse_user_preferences_views.xml`, and `views/pulse_portal_templates.xml`
don't exist since those components were replaced or not yet built (§7/§14).
Built manifest instead includes `views/pulse_run_views.xml` (not in the
list below) for the run list/form the "Run Now"/"History" buttons open into.

```python
# pulse_digest/__manifest__.py
{
    "name": "Pulse",
    "version": "19.0.0.0.1",  # beta until core spec complete; 18.0.0.0.1 on the 18 branch
    # Promote to 19.0.1.0.0 / 18.0.1.0.0 once all six detectors, both audiences,
    # all channels, and the full test suite are done and surviving real installs.
    "summary": "Daily exception digest with cross-app anomaly detection",
    "description": """
Pulse — Daily Exception Digest
==============================
Pulse delivers a daily briefing of records that need attention across
Accounting and Sales/CRM, with built-in anomaly detection for outliers
that simple thresholds miss.

Unlike Odoo's built-in digest (which reports aggregate KPIs), Pulse lists
the specific records to act on, scoped per-user or per-company, delivered
by email, in-app notification, or WhatsApp.
    """,
    "author": "Anthony Adegbemi",
    "website": "https://github.com/adibas03/pulse_digest",
    "license": "LGPL-3",
    "category": "Productivity",
    "depends": [
        "base",
        "mail",
        "account",
        "sale_management",
        "crm",
    ],
    "data": [
        "security/pulse_security.xml",
        "security/ir.model.access.csv",
        "data/pulse_detector_data.xml",
        "data/pulse_cron_data.xml",
        "data/mail_template_data.xml",
        "views/pulse_config_views.xml",
        "views/pulse_detector_views.xml",
        "views/pulse_run_views.xml",
        "views/pulse_user_preferences_views.xml",
        "views/pulse_menus.xml",
        "views/pulse_portal_templates.xml",
        "wizards/pulse_run_wizard_views.xml",
    ],
    "demo": [
        "demo/pulse_demo.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "pulse_digest/static/src/**/*",
        ],
    },
    "installable": True,
    "application": True,
}
```

Note on the manifest: per Odoo's vendor guidelines, `name` is short (5 chars, well under the 25-char limit), no adjectives, no company name. Version follows the major-minor-bugfix convention prefixed with the Odoo version.

---

## 3. File tree

**Not fully built**: `tests/` (entirely, §9), `wizards/` (entirely, §7/§14),
`controllers/portal.py` + `views/pulse_portal_templates.xml` (§14),
`views/pulse_user_preferences_views.xml` (no built preference fields to back
it, §4.5), `static/description/index.html` and `static/src/scss/`. Also
added but not shown below: `views/pulse_run_views.xml`.

```
pulse_digest/
├── __init__.py
├── __manifest__.py
├── README.md
├── data/
│   ├── pulse_detector_data.xml      # Detector catalog seed records
│   ├── pulse_cron_data.xml          # ir.cron records for daily run
│   └── mail_template_data.xml       # Email templates (digest body, etc.)
├── demo/
│   └── pulse_demo.xml               # Demo data: a config, an enabled detector
├── models/
│   ├── __init__.py
│   ├── constants.py                 # Shared enums (severity, etc.) — single source of truth
│   ├── pulse_detector.py            # The detector catalog model
│   ├── pulse_config.py              # Per-company configuration
│   ├── pulse_config_detector.py     # Join: config <-> detector with overrides
│   ├── pulse_run.py                 # Execution record
│   ├── pulse_run_line.py            # Individual findings within a run
│   ├── pulse_channel.py             # Channel registry + base class
│   ├── res_users.py                 # User-level channel preferences
│   └── detectors/                   # The actual detector implementations
│       ├── __init__.py
│       ├── base.py                  # PulseDetectorBase abstract class
│       ├── account/
│       │   ├── __init__.py
│       │   ├── _common.py           # Shared account.move query fragments
│       │   ├── overdue_invoices.py
│       │   ├── payment_delay_outlier.py
│       │   └── credit_limit_breach.py
│       └── sale/
│           ├── __init__.py
│           ├── _common.py           # Shared crm.lead query fragments
│           ├── stale_opportunities.py
│           ├── deals_closing_today.py
│           └── deal_velocity_drop.py
├── controllers/
│   ├── __init__.py
│   └── portal.py                    # /my/pulse/<run_id> portal page
├── security/
│   ├── pulse_security.xml           # Security groups, record rules
│   └── ir.model.access.csv          # ACL matrix
├── views/
│   ├── pulse_config_views.xml
│   ├── pulse_detector_views.xml
│   ├── pulse_run_views.xml
│   ├── pulse_user_preferences_views.xml
│   ├── pulse_menus.xml
│   └── pulse_portal_templates.xml   # QWeb templates for /my/pulse
├── static/
│   ├── description/
│   │   ├── icon.png                 # 256x256, the Pulse logo
│   │   ├── index.html               # Apps store listing page
│   │   └── screenshots/
│   └── src/
│       └── scss/
│           └── pulse_digest.scss
├── tests/
│   ├── __init__.py
│   ├── common.py                    # Test setUp helpers
│   ├── test_detector_framework.py
│   ├── test_detector_overdue_invoices.py
│   ├── test_detector_payment_delay_outlier.py
│   ├── test_detector_credit_limit_breach.py
│   ├── test_detector_stale_opportunities.py
│   ├── test_channel_dispatch.py
│   ├── test_run_execution.py
│   ├── test_per_user_filtering.py
│   ├── test_security.py
│   ├── test_suppression_gate.py
│   └── test_portal.py
└── wizards/
    ├── __init__.py
    ├── pulse_run_wizard.py          # "Run digest now" admin action
    └── pulse_run_wizard_views.xml   # Wizard form with the "Run" button
```

This structure follows OCA conventions, which is what an Odoo R&D reviewer will expect. Detectors split by app under `models/detectors/` makes adding a new app a contained operation in v1.1.

---

## 4. Data model

> All model files in this section share the standard Odoo imports
> (`from odoo import models, fields, api`). Where a model references shared
> enums, it also imports them from the constants module, e.g.:
> `from odoo.addons.pulse_digest.models.constants import SEVERITY_SELECTION, SEVERITY_INFO`.
> The code blocks below omit the import headers for brevity and show only the
> model bodies.

> **Built this iteration — API/implementation notes not reflected in the code
> blocks below:**
> - All `_sql_constraints = [...]` lists in this section were built using the
>   newer `models.Constraint(...)` API instead (e.g.
>   `_technical_name_uniq = models.Constraint("UNIQUE(technical_name)", "...")`
>   on `pulse.detector`) — same effect, different declaration form.
> - `pulse.detector` gained an `is_available` computed Boolean not in the
>   original spec (`compute="_compute_is_available"`, non-stored, batched
>   over `dependency_modules` vs. installed `ir.module.module` state). It's
>   what actually drives "detector is hidden if any dependency module isn't
>   installed," which the spec described in prose but didn't implement.
> - `pulse.config._compute_last_run` and `pulse.run._compute_line_count`
>   (referenced by name in the field declarations below but never given a
>   body in this spec) are implemented: `last_run_date` is the max
>   `finished_at` across `status == "done"` runs; `line_count` is
>   `len(line_ids)`.
> - `pulse.detector` also gained `_get_detector_class()` (instance method,
>   resolves `detector_class`'s dotted path via `importlib`), replacing the
>   `_resolve_detector_class` staticmethod §7 originally placed on
>   `pulse.config` — see §7's implementation note for why.

### 4.1 `pulse.detector` — the catalog

One record per anomaly type the module knows how to compute. Seeded via XML in `data/pulse_detector_data.xml`. Users do not create these directly; vendors and v1.1+ modules extend the catalog.

```python
class PulseDetector(models.Model):
    _name = "pulse.detector"
    _description = "Pulse Detector Catalog"
    _order = "category, sequence, name"

    name = fields.Char(required=True, translate=True)
    technical_name = fields.Char(required=True, index=True)
    # Used to look up the Python class. Must be globally unique.
    # Convention: <app>.<detector> e.g. "account.overdue_invoices"

    category = fields.Selection([
        ("accounting", "Accounting"),
        ("sales", "Sales"),
    ], required=True)

    description = fields.Text(translate=True)
    rationale = fields.Text(translate=True,
        help="Why this detector matters. Shown in the configuration UI.")

    sequence = fields.Integer(default=10)

    detector_class = fields.Char(required=True,
        help="Dotted Python path, e.g. "
             "odoo.addons.pulse_digest.models.detectors.account.overdue_invoices."
             "OverdueInvoicesDetector")

    dependency_modules = fields.Char(
        help="Comma-separated list of Odoo modules this detector requires. "
             "Detector is hidden if any of these are not installed.")

    is_default_enabled = fields.Boolean(default=False,
        help="If True, this detector is active by default for new configs.")

    is_statistical = fields.Boolean(default=False,
        help="If True, requires baseline data and may be noisy on small samples. "
             "Surfaced separately in the UI.")

    default_params = fields.Json(default=dict,
        help="Default parameter values. Schema documented per detector.")

    _sql_constraints = [
        ("technical_name_uniq", "UNIQUE(technical_name)",
         "Detector technical names must be unique."),
    ]
```

### 4.2 `pulse.config` — per-company configuration

```python
class PulseConfig(models.Model):
    _name = "pulse.config"
    _description = "Pulse Configuration"
    _inherit = ["mail.thread"]

    name = fields.Char(required=True, default="Pulse Digest")
    company_id = fields.Many2one("res.company", required=True,
        default=lambda self: self.env.company)
    active = fields.Boolean(default=True, tracking=True)

    # Schedule
    run_time = fields.Float(default=7.0,
        help="Hour of the day (0-24) when the digest runs.")
    timezone = fields.Selection(_tz_get, required=True,
        default=lambda self: self.env.user.tz or "UTC")

    # Audience
    digest_mode = fields.Selection([
        ("company", "Company-wide only"),
        ("per_user", "Per-user only"),
        ("both", "Both"),
    ], default="both", required=True, tracking=True)

    company_recipient_ids = fields.Many2many("res.users",
        string="Company digest recipients",
        domain="[('company_ids', 'in', company_id)]")

    user_group_id = fields.Many2one("res.groups",
        string="Users to include (per-user mode)",
        default=lambda self: self.env.ref("pulse_digest.group_pulse_recipient"))

    # Detectors
    detector_line_ids = fields.One2many(
        "pulse.config.detector", "config_id",
        string="Detectors")

    # Reporting
    run_ids = fields.One2many("pulse.run", "config_id")
    last_run_date = fields.Datetime(compute="_compute_last_run", store=True)

    _sql_constraints = [
        ("company_uniq", "UNIQUE(company_id)",
         "Only one Pulse config per company."),
    ]
```

### 4.3 `pulse.config.detector` — the join

```python
class PulseConfigDetector(models.Model):
    _name = "pulse.config.detector"
    _description = "Pulse Config Detector"

    config_id = fields.Many2one("pulse.config", required=True, ondelete="cascade")
    detector_id = fields.Many2one("pulse.detector", required=True, ondelete="cascade")

    active = fields.Boolean(default=True)
    params = fields.Json(default=dict,
        help="Overrides for the detector's default_params.")

    # Convenience computed fields for the UI
    category = fields.Selection(related="detector_id.category", store=True)
    is_statistical = fields.Boolean(related="detector_id.is_statistical", store=True)

    _sql_constraints = [
        ("config_detector_uniq", "UNIQUE(config_id, detector_id)",
         "Each detector can only be linked once per config."),
    ]
```

### 4.4 `pulse.run` and `pulse.run.line`

```python
class PulseRun(models.Model):
    _name = "pulse.run"
    _description = "Pulse Run"
    _order = "started_at DESC"

    config_id = fields.Many2one("pulse.config", required=True, ondelete="cascade")
    company_id = fields.Many2one(related="config_id.company_id", store=True)

    audience = fields.Selection([
        ("company", "Company-wide"),
        ("user", "Per-user"),
    ], required=True)
    user_id = fields.Many2one("res.users",
        help="The user this run was scoped to (if audience='user').")

    started_at = fields.Datetime(default=fields.Datetime.now)
    finished_at = fields.Datetime()
    duration_ms = fields.Integer()
    status = fields.Selection([
        ("running", "Running"),
        ("done", "Done"),
        ("failed", "Failed"),
    ], default="running")
    error_message = fields.Text()

    line_ids = fields.One2many("pulse.run.line", "run_id")
    line_count = fields.Integer(compute="_compute_line_count", store=True)

    # Delivery state per channel
    email_sent = fields.Boolean()
    inapp_sent = fields.Boolean()
    whatsapp_sent = fields.Boolean()


class PulseRunLine(models.Model):
    _name = "pulse.run.line"
    _description = "Pulse Run Finding"

    run_id = fields.Many2one("pulse.run", required=True, ondelete="cascade")
    detector_id = fields.Many2one("pulse.detector", required=True)

    # The record this finding points to
    res_model = fields.Char(required=True)
    res_id = fields.Integer(required=True)
    res_name = fields.Char(help="Cached display name of the record.")

    # Severity & display
    severity = fields.Selection(
        SEVERITY_SELECTION, default=SEVERITY_INFO)

    summary = fields.Char(required=True)
    detail = fields.Text()

    # Metric values for statistical detectors
    metric_value = fields.Float()
    baseline_value = fields.Float()
    deviation = fields.Float(
        help="How many standard deviations from baseline.")

    # Suppression: every detected finding is RECORDED (so history and
    # resolution-detection stay accurate), but only delivered=True lines appear
    # in the digest body. Detection is never gated by suppression — only
    # delivery is. See §7 _execute_detector and the suppression contract on
    # PulseDetectorBase.
    #
    # NOT YET BUILT (this iteration — see §7/§14): the suppression gate is a
    # pass-through, so nothing currently sets delivered=False or populates
    # suppression_reason. These two fields don't exist on pulse.run.line yet;
    # add them when the backoff schedule lands.
    delivered = fields.Boolean(default=True)
    suppression_reason = fields.Char(
        help="If not delivered, why (e.g. 'recurrence backoff, age 12d').")
```

### 4.5 `res.users` extension — channel preferences

**NOT YET BUILT.** `models/res_users.py` exists with the `_inherit = "res.users"`
scaffold but every field below is commented out — no channel-preference
fields exist on `res.users` yet. This blocks `WhatsAppChannel` (needs
`pulse_phone`) and any future per-channel opt-out UI. Tracks with channel
dispatch overall being unbuilt this iteration (§6/§14).

```python
class ResUsers(models.Model):
    _inherit = "res.users"

    pulse_email_enabled = fields.Boolean(default=True)
    pulse_inapp_enabled = fields.Boolean(default=True)
    pulse_whatsapp_enabled = fields.Boolean(default=False)
    pulse_phone = fields.Char(
        help="Phone number for WhatsApp digest delivery (19+).")
```

---

## 5. The detector framework

This is the architectural centerpiece. A reviewer who opens the repo should see this file first and immediately understand the extensibility story.

### 5.0 Shared constants

Severity is referenced across four layers — the `pulse.run.line` model, the detectors, the views, and the tests — so it lives in one neutral module that depends on nothing and is imported by everything. This keeps the dependency graph pointing one way (a core model must never import from the detector layer) and prevents the same enum drifting out of sync across files.

```python
# models/constants.py
"""Shared constants for pulse_digest. Single source of truth for enums
used across models, detectors, channels, views, and tests.

Plain string constants (not enum.Enum) because Odoo's fields.Selection
expects [(value, label), ...] tuples of plain strings — matching the
framework's grain avoids conversion at every boundary.
"""

# Severity levels, ordered low -> high.
SEVERITY_INFO = "info"
SEVERITY_WARNING = "warning"
SEVERITY_CRITICAL = "critical"

SEVERITY_SELECTION = [
    (SEVERITY_INFO, "Info"),
    (SEVERITY_WARNING, "Warning"),
    (SEVERITY_CRITICAL, "Critical"),
]

# Tuple of valid values, for validation and tests.
SEVERITIES = tuple(value for value, _label in SEVERITY_SELECTION)

# Ordering helper — useful for sorting findings by urgency.
SEVERITY_ORDER = {SEVERITY_INFO: 0, SEVERITY_WARNING: 1, SEVERITY_CRITICAL: 2}
```

Hoist a value into `constants.py` only when it crosses a layer boundary. Severity crosses all four, so it qualifies. Values that live in a single layer (e.g. detector `technical_name` strings, which appear only in the catalog seed and the detector class) stay where they are — moving them here would just relocate clutter.

### 5.1 Base class

```python
# models/detectors/base.py
from abc import abstractmethod

# NOTE: Detectors are plain Python classes, NOT models.Model subclasses, so
# they do not get `fields`, `relativedelta`, etc. for free. Every detector
# module that needs them imports explicitly:
#     from odoo import fields
#     from dateutil.relativedelta import relativedelta
# Severity values are plain strings ("info" | "warning" | "critical"); the
# canonical names live in constants.py. base.py imports only SEVERITIES, which
# it uses below to validate PulseFinding. Detectors, models, and tests import
# the severity constants from constants.py directly — there is one canonical
# import path, not via base. (If base ever becomes a deliberate facade for the
# detector API, re-exporting the severity names here would be the place to do
# it — but it is not one today.)
from odoo.addons.pulse_digest.models.constants import SEVERITIES


class PulseDetectorBase:
    """Abstract base for all Pulse detectors.

    Subclasses MUST set:
        TECHNICAL_NAME: matches the technical_name on the pulse.detector record
        DEFAULT_PARAMS: dict of default params (overridable per config)

    Subclasses MUST implement:
        compute(env, scope): yields PulseFinding instances

    Detectors are STATELESS: they receive `env` as an argument on every call
    rather than storing it. This keeps a single detector instance safe to reuse
    across companies/users within one run.

    Scope is either:
        Scope.company(company)   — return findings for whole company
        Scope.user(user)         — return findings filtered to records this
                                   user owns/is responsible for
    """

    TECHNICAL_NAME = None
    DEFAULT_PARAMS = {}

    # --- Recurrence suppression contract (v1) ---
    # Default to NOT suppressing. The dangerous failure for a digest is hiding a
    # finding (silent, trust-killing); the safe failure is showing it again
    # (loud, recoverable). So an undeclared detector shows every finding every
    # run. A detector opts INTO suppression explicitly — the surprising,
    # withholding behaviour is never inherited silently.
    #
    #   SUPPRESSIBLE: can this detector's findings recur into noise?
    #     False (default) = self-limiting (sliding window / one-off statistical
    #     finding) -> always delivered, never suppressed.
    #     True = persisting-condition finding (same record matches day after day
    #     until resolved) -> eligible for suppression.
    #
    #   AGE_FIELD: name of the date/datetime field on the source record from
    #     which "valid since" age is derived. None = age is not derivable from
    #     the record. A detector that is SUPPRESSIBLE but has AGE_FIELD = None
    #     (e.g. credit_limit_breach) is delivered every run in v1 — suppression
    #     for it requires the per-finding state table planned for v1.1.
    #
    #   SHELVED THIS ITERATION: the capped age-based backoff schedule
    #   (formerly _suppression_phase_shows, §7) that would act on AGE_FIELD is
    #   deferred to the next version, alongside the per-recipient state table.
    #   For now, _suppression_gate delivers every finding every run regardless
    #   of SUPPRESSIBLE/AGE_FIELD — these two attributes exist as forward-
    #   compatible plumbing on the contract, but nothing reads AGE_FIELD's
    #   value yet. See §7 and §14 for current status.
    SUPPRESSIBLE = False
    AGE_FIELD = None

    def __init__(self, params=None):
        self.params = {**self.DEFAULT_PARAMS, **(params or {})}

    @abstractmethod
    def compute(self, env, scope):
        """Yield PulseFinding instances."""
        raise NotImplementedError

    # Helper for subclasses: applies user-scope domain to a base domain.
    # Override in subclass if the user-scope filter is non-standard.
    # `env` is passed in (not stored) to keep the detector stateless.
    def apply_user_scope(self, env, domain, model_name, user):
        """Default: filter by user_id field if it exists on the model."""
        model = env[model_name]
        if "user_id" in model._fields:
            return domain + [("user_id", "=", user.id)]
        if "invoice_user_id" in model._fields:
            return domain + [("invoice_user_id", "=", user.id)]
        return domain

    # Helper for subclasses whose params include a severity->threshold mapping.
    # Guards against a config override supplying an invalid severity key
    # (e.g. {"warn": 30}). Uses SEVERITIES (the canonical tuple) for the
    # membership check — this is the tuple's job, distinct from the individual
    # SEVERITY_* names used as the actual keys.
    @staticmethod
    def validate_severity_thresholds(thresholds):
        bad = [k for k in thresholds if k not in SEVERITIES]
        if bad:
            raise ValueError(
                f"Invalid severity key(s) in thresholds: {bad}. "
                f"Valid values: {SEVERITIES}")
        return thresholds


class Scope:
    """Detector execution scope. Construct via Scope.user() or Scope.company();
    both guarantee a coherent kind/user/company combination.

    `kind` values are owned by this class (Scope.USER / Scope.COMPANY) rather
    than living in constants.py — they are a control-flow discriminant intrinsic
    to Scope, never persisted, never rendered in a view, never leaving the
    detector layer. (If a scope kind ever becomes a stored/selectable field,
    move the selection list to constants.py at that point — not before.)
    """

    USER = "user"
    COMPANY = "company"

    __slots__ = ("kind", "company", "user")

    def __init__(self, kind, company=None, user=None):
        if kind not in (self.USER, self.COMPANY):
            raise ValueError(f"Invalid scope kind: {kind!r}")
        if kind == self.USER and user is None:
            raise ValueError("user-scope requires a user")
        if kind == self.COMPANY and user is not None:
            raise ValueError("company-scope must not carry a user")
        if company is None:
            raise ValueError("scope requires a company")
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "company", company)
        object.__setattr__(self, "user", user)

    def __setattr__(self, *_):
        raise AttributeError("Scope is immutable")

    @classmethod
    def company(cls, company):
        if not company:
            raise ValueError("Scope.company requires a company record")
        return cls(cls.COMPANY, company)

    @classmethod
    def user(cls, user):
        if not user:
            raise ValueError("Scope.user requires a user record")
        return cls(cls.USER, user.company_id, user=user)

    @property
    def is_user(self):
        return self.kind == self.USER


class PulseFinding:
    """One finding returned by a detector. Maps 1:1 to a pulse.run.line."""
    def __init__(self, res_model, res_id, res_name, summary,
                 severity=SEVERITY_INFO, detail=None,
                 metric_value=None, baseline_value=None, deviation=None):
        assert severity in SEVERITIES, f"Unknown severity: {severity!r}"
        self.res_model = res_model
        self.res_id = res_id
        self.res_name = res_name
        self.summary = summary
        self.severity = severity
        self.detail = detail
        self.metric_value = metric_value
        self.baseline_value = baseline_value
        self.deviation = deviation
```

The `assert` against `SEVERITIES` means a detector that emits a typo'd severity (`"warn"` instead of `"warning"`) fails loudly rather than silently writing an invalid value the Selection field would reject later. Detectors assign severity using the named constants (`SEVERITY_CRITICAL`, etc.) imported from `constants.py`, so a typo'd _name_ is a `NameError` at import time — failing even earlier than the runtime assert. The same constants are used as the keys in a detector's `severity_thresholds` param dict and in the lookups that read it, so the key and the eventual assignment can never drift apart. Config-supplied overrides of that dict are guarded by `validate_severity_thresholds`, which uses `SEVERITIES` (the tuple) for the membership check. What detectors _do_ keep as plain strings is their own non-severity param names — keys like `"min_days_overdue"` or `"min_amount"` that are this detector's private config schema and have no coupling to the severity enum.

### 5.1b Shared account query helpers (`_common.py`)

Both accounting detectors query `account.move` and share a base fragment:
posted customer invoices for the company. They _differ_ on `payment_state`
(overdue wants unpaid/partial; the outlier detector wants paid), so the helper
covers only the genuinely-shared part and each detector appends its own filters.

The deduplication target here is the **query**, not the literal strings. The
Odoo selection values (`"out_invoice"`, `"posted"`) stay inline — they are
Odoo's vocabulary, not ours, so they don't belong in `constants.py`; extracting
them as constants would assert ownership we don't have and wouldn't protect
against the real risk (Odoo changing a value). What we _do_ own and want to
deduplicate is the _shape_ of the query, so that two detectors can't silently
drift onto different invoice sets. That lives in a plain function module:

```python
# models/detectors/account/_common.py
"""Shared account.move query fragments for the accounting detectors.

Deduplicates the *query shape*, not the Odoo selection strings (those stay
inline — they are Odoo's vocabulary). Keeping the base domain in one place
prevents two detectors silently filtering different invoice sets.
"""


def customer_invoice_domain(company):
    """Base domain: posted customer invoices for `company`.

    Deliberately does NOT constrain payment_state — callers add the
    payment_state filter they need (unpaid/partial vs paid), because that is
    exactly where the two detectors legitimately diverge.
    """
    return [
        ("move_type", "=", "out_invoice"),
        ("state", "=", "posted"),
        ("company_id", "=", company.id),
    ]
```

A reviewer reading this sees the right instinct: shared _logic_ extracted to a
helper, dependency-owned _values_ left inline and idiomatic. When the third
accounting detector (`credit_limit_breach`) lands, it composes from the same
base and adds its own partner-grouping — helpers specialize cleanly where a
flat bag of string constants would not.

### 5.2 Example deterministic detector (default-enabled)

```python
# models/detectors/account/overdue_invoices.py
from odoo import fields
from odoo.addons.pulse_digest.models.constants import (
    SEVERITY_INFO, SEVERITY_WARNING, SEVERITY_CRITICAL,
)
from odoo.addons.pulse_digest.models.detectors.account._common import (
    customer_invoice_domain,
)
from odoo.addons.pulse_digest.models.detectors.base import (
    PulseDetectorBase, PulseFinding,
)


class OverdueInvoicesDetector(PulseDetectorBase):
    TECHNICAL_NAME = "account.overdue_invoices"

    # Persisting condition: same invoice matches every day until paid. Age
    # would be derived from the due date once the backoff schedule ships
    # (see §7/§14) — SUPPRESSIBLE/AGE_FIELD are left at the base defaults
    # for this iteration since the gate doesn't act on them yet. Re-enable
    # (SUPPRESSIBLE = True, AGE_FIELD = "invoice_date_due") when it does.

    DEFAULT_PARAMS = {
        "min_days_overdue": 1,
        "min_amount": 0.0,
        "severity_thresholds": {
            SEVERITY_WARNING: 30,    # >= 30 days overdue -> warning
            SEVERITY_CRITICAL: 60,   # >= 60 days overdue -> critical
        },
    }

    def compute(self, env, scope):
        self.validate_severity_thresholds(self.params["severity_thresholds"])
        today = fields.Date.context_today(env.user)
        domain = customer_invoice_domain(scope.company) + [
            ("payment_state", "in", ("not_paid", "partial")),
            ("invoice_date_due", "<", today),
            ("amount_residual", ">", self.params["min_amount"]),
        ]

        if scope.is_user:
            domain = self.apply_user_scope(env, domain, "account.move", scope.user)

        invoices = env["account.move"].search(domain)

        for inv in invoices:
            days = (today - inv.invoice_date_due).days
            if days < self.params["min_days_overdue"]:
                continue

            sev = SEVERITY_INFO
            if days >= self.params["severity_thresholds"][SEVERITY_CRITICAL]:
                sev = SEVERITY_CRITICAL
            elif days >= self.params["severity_thresholds"][SEVERITY_WARNING]:
                sev = SEVERITY_WARNING

            yield PulseFinding(
                res_model="account.move",
                res_id=inv.id,
                res_name=inv.name,
                summary=f"{inv.partner_id.name}: {inv.amount_residual} "
                        f"{inv.currency_id.symbol} overdue {days}d",
                severity=sev,
                metric_value=days,
            )
```

### 5.3 Example statistical detector (off by default)

```python
# models/detectors/account/payment_delay_outlier.py
import statistics
from dateutil.relativedelta import relativedelta
from odoo import fields
from odoo.addons.pulse_digest.models.constants import (
    SEVERITY_WARNING, SEVERITY_CRITICAL,
)
from odoo.addons.pulse_digest.models.detectors.account._common import (
    customer_invoice_domain,
)
from odoo.addons.pulse_digest.models.detectors.base import (
    PulseDetectorBase, PulseFinding,
)


class PaymentDelayOutlierDetector(PulseDetectorBase):
    """Flag customers whose latest payment delay is unusually high vs. their
    own 8-week rolling mean."""

    TECHNICAL_NAME = "account.payment_delay_outlier"
    DEFAULT_PARAMS = {
        "lookback_weeks": 8,
        "min_payments_for_baseline": 4,
        "z_threshold": 1.5,
    }

    def compute(self, env, scope):
        # Find customers with paid invoices in the last week
        lookback_days = self.params["lookback_weeks"] * 7
        cutoff = fields.Date.today() - relativedelta(days=lookback_days)

        domain = customer_invoice_domain(scope.company) + [
            ("payment_state", "=", "paid"),
            ("invoice_date", ">=", cutoff),
        ]
        if scope.is_user:
            domain = self.apply_user_scope(env, domain, "account.move", scope.user)

        invoices = env["account.move"].search(domain)

        # Group by customer, compute days-to-pay for each
        by_partner = {}
        for inv in invoices:
            paid_date = self._first_payment_date(inv)
            if not paid_date or not inv.invoice_date_due:
                continue
            days_to_pay = (paid_date - inv.invoice_date_due).days
            by_partner.setdefault(inv.partner_id, []).append(
                (inv.invoice_date, days_to_pay, inv)
            )

        for partner, entries in by_partner.items():
            if len(entries) < self.params["min_payments_for_baseline"]:
                continue
            entries.sort(key=lambda e: e[0])
            *historical, latest = entries
            historical_delays = [d for _, d, _ in historical]
            mean = statistics.mean(historical_delays)
            stdev = statistics.stdev(historical_delays) if len(historical_delays) > 1 else 0
            if stdev == 0:
                continue
            latest_delay = latest[1]
            z = (latest_delay - mean) / stdev
            if z >= self.params["z_threshold"]:
                yield PulseFinding(
                    res_model="res.partner",
                    res_id=partner.id,
                    res_name=partner.name,
                    summary=f"{partner.name} paid {latest_delay}d late "
                            f"(baseline {mean:.1f}d, +{z:.1f}σ)",
                    severity=SEVERITY_WARNING if z < 2.5 else SEVERITY_CRITICAL,
                    metric_value=latest_delay,
                    baseline_value=mean,
                    deviation=z,
                )

    def _first_payment_date(self, invoice):
        # Walk reconciled payments to find first payment date
        payments = invoice._get_reconciled_payments()
        if not payments:
            return None
        return min(p.date for p in payments)
```

### 5.3b `credit_limit_breach` (deterministic, default-on)

The third accounting detector. Unlike the first two it does _not_ query
`account.move` directly — credit limits live on `res.partner`. So this detector
doesn't compose from `customer_invoice_domain`; it queries partners with a
configured limit and a current outstanding balance that exceeds it.

> **API status (verified Nov 2025).** Confirmed in Odoo 19 source: `credit`
> (computed outstanding), `credit_limit` (threshold), and `use_partner_credit_limit`
> (toggle) are the correct field names on `res.partner`. See §1b for the full
> verification report. The detector's logic and field references are
> API-accurate; no further verification needed on these.

This is the detector that's `SUPPRESSIBLE = True` + `AGE_FIELD = None` — it
wants suppression (a customer can sit over limit for weeks; same partner
flagged daily becomes noise) but has no natural age anchor on the partner
record. The v1 suppression gate falls through to "deliver every run" for this
case; the per-recipient `pulse.finding.state` table in v1.1 will close the gap.
Documented at the call site so the limitation is visible, not hidden.

```python
# models/detectors/account/credit_limit_breach.py
from odoo.addons.pulse_digest.models.constants import (
    SEVERITY_WARNING, SEVERITY_CRITICAL,
)
from odoo.addons.pulse_digest.models.detectors.base import (
    PulseDetectorBase, PulseFinding,
)


class CreditLimitBreachDetector(PulseDetectorBase):
    """Flag customers whose outstanding AR balance exceeds their credit limit."""

    TECHNICAL_NAME = "account.credit_limit_breach"

    # Persisting condition: same partner can sit over limit day after day.
    # But there is no natural age field on res.partner for "when did the
    # breach start." AGE_FIELD = None signals to _suppression_gate that this
    # detector wants suppression but cannot provide its own age — so v1
    # delivers it every run. v1.1 per-recipient state closes this.
    SUPPRESSIBLE = True
    AGE_FIELD = None

    DEFAULT_PARAMS = {
        "min_breach_amount": 0.0,
        "severity_thresholds": {
            # Fraction of credit_limit by which `credit` exceeds it.
            # 0.10 = 10% over -> warning; 0.25 = 25% over -> critical.
            SEVERITY_WARNING: 0.10,
            SEVERITY_CRITICAL: 0.25,
        },
    }

    def compute(self, env, scope):
        self.validate_severity_thresholds(self.params["severity_thresholds"])

        # `res.partner.credit` is company-dependent (same partner has
        # different outstanding-AR values per company). Without with_company,
        # both the search and the per-record reads below would use whatever
        # company env happened to be in — typically the cron user's main
        # company, not necessarily scope.company. Scope all reads explicitly.
        Partner = env["res.partner"].with_company(scope.company)

        domain = [
            ("use_partner_credit_limit", "=", True),
            ("credit_limit", ">", 0),
            ("credit", ">", 0),
        ]

        # User-scope: narrow to partners where this user is the assigned
        # salesperson. Partners with NO assigned salesperson are deliberately
        # invisible to per-user digests in v1 — they appear only in the
        # company-wide digest, which is the safety net.
        if scope.is_user:
            domain.append(("user_id", "=", scope.user.id))

        # Multi-company filtering on res.partner is handled by record rules
        # together with with_company() above; no Python .filtered() for
        # company is needed.
        partners = Partner.search(domain)

        for partner in partners:
            breach_amount = partner.credit - partner.credit_limit
            if breach_amount <= self.params["min_breach_amount"]:
                continue

            breach_ratio = breach_amount / partner.credit_limit
            sev = SEVERITY_WARNING
            if breach_ratio >= self.params["severity_thresholds"][SEVERITY_CRITICAL]:
                sev = SEVERITY_CRITICAL

            yield PulseFinding(
                res_model="res.partner",
                res_id=partner.id,
                res_name=partner.name,
                summary=f"{partner.name}: {partner.credit:.0f} "
                        f"vs limit {partner.credit_limit:.0f} "
                        f"({breach_ratio:+.0%})",
                severity=sev,
                metric_value=partner.credit,
                baseline_value=partner.credit_limit,
                deviation=breach_ratio,
            )
```

Three things in the compute method that are easy to miss and matter:

**`with_company(scope.company)` is load-bearing, not decorative.** `res.partner.credit` and `credit_limit` are `company_dependent` fields — the same partner has different values per company. Without scoping `env` to `scope.company`, the cron (running as `base.user_root` in some default company) would read AR balances from the _wrong_ company's books. Both the search domain and the in-loop reads (`partner.credit`, `partner.credit_limit`) depend on this context; doing it once at the `Partner = env[...].with_company(...)` line covers both.

**No Python `.filtered()` for multi-company.** Once `with_company()` is set, Odoo's standard `res.partner` record rules handle company visibility. Doing it again in Python risks disagreeing with the framework's own rules (e.g. via `allowed_company_ids` semantics). The earlier version of this code did both and was redundant at best, contradictory at worst.

**Deliberate gap: partners with no assigned salesperson.** The user-scope filter (`user_id = scope.user.id`) excludes partners where `user_id` is `False`. In a per-user digest, those partners never appear. This is intentional — the company-wide digest is the v1 safety net for them — but worth being explicit so it doesn't read as an oversight. A future detector could optionally include them in _every_ per-user digest as a "no salesperson, please assign" signal; that's a v1.1+ refinement.

**Day-1 verification:** confirm `credit` and `credit_limit` still carry `company_dependent=True` in Odoo 19's `res.partner`. If they were refactored to per-company stored records, `with_company` is still the right mechanism but the underlying storage differs; detector logic is unaffected either way.

### 5.4 Sales detectors

> **API status (verified Nov 2025).** Confirmed in Odoo 19 source:
> `type` ('lead'|'opportunity'), `active`, `date_last_stage_update`,
> `stage_id.is_won`, `date_deadline`, `expected_revenue`, and `user_id` are
> the correct field names on `crm.lead`. `active = False` is broader than
> "lost" (see `open_opportunity_domain` docstring). See §1b for the full
> verification report. No further verification needed on these fields.

#### Shared helper (`sale/_common.py`)

As with accounting, the shared fragment is "open opportunities for this
company." Each detector appends its own filters. Odoo's selection values
(`"opportunity"`) stay inline — they are CRM's vocabulary, not ours.

```python
# models/detectors/sale/_common.py
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
```

#### `stale_opportunities` (deterministic, default-on)

Open opportunities with no stage movement for N days — deals rotting in the
pipeline. The staleness signal is `date_last_stage_update` older than the
threshold.

```python
# models/detectors/sale/stale_opportunities.py
from dateutil.relativedelta import relativedelta
from odoo import fields
from odoo.addons.pulse_digest.models.constants import (
    SEVERITY_INFO, SEVERITY_WARNING, SEVERITY_CRITICAL,
)
from odoo.addons.pulse_digest.models.detectors.sale._common import (
    open_opportunity_domain,
)
from odoo.addons.pulse_digest.models.detectors.base import (
    PulseDetectorBase, PulseFinding,
)


class StaleOpportunitiesDetector(PulseDetectorBase):
    TECHNICAL_NAME = "sale.stale_opportunities"

    # Persisting condition: same deal sits stale every day until touched.
    # Age would be derived from date_last_stage_update once the backoff
    # schedule ships (see §7/§14) — left at base defaults for this
    # iteration, same as overdue_invoices. Re-enable (SUPPRESSIBLE = True,
    # AGE_FIELD = "date_last_stage_update") when it does.

    DEFAULT_PARAMS = {
        "stale_days": 14,
        "min_expected_revenue": 0.0,
        "severity_thresholds": {
            SEVERITY_WARNING: 14,    # >= 14 days stale -> warning
            SEVERITY_CRITICAL: 30,   # >= 30 days stale -> critical
        },
    }

    def compute(self, env, scope):
        self.validate_severity_thresholds(self.params["severity_thresholds"])
        today = fields.Date.context_today(env.user)
        cutoff = today - relativedelta(days=self.params["stale_days"])

        domain = open_opportunity_domain(scope.company) + [
            ("stage_id.is_won", "=", False),
            ("date_last_stage_update", "<", cutoff),
            ("expected_revenue", ">", self.params["min_expected_revenue"]),
        ]
        if scope.is_user:
            domain = self.apply_user_scope(env, domain, "crm.lead", scope.user)

        leads = env["crm.lead"].search(domain)

        for lead in leads:
            last_move = fields.Date.to_date(lead.date_last_stage_update)
            days = (today - last_move).days if last_move else self.params["stale_days"]

            sev = SEVERITY_INFO
            if days >= self.params["severity_thresholds"][SEVERITY_CRITICAL]:
                sev = SEVERITY_CRITICAL
            elif days >= self.params["severity_thresholds"][SEVERITY_WARNING]:
                sev = SEVERITY_WARNING

            yield PulseFinding(
                res_model="crm.lead",
                res_id=lead.id,
                res_name=lead.name,
                summary=f"{lead.name} ({lead.stage_id.name}): no movement "
                        f"for {days}d — {lead.expected_revenue:.0f} "
                        f"{lead.company_currency.symbol}",
                severity=sev,
                metric_value=days,
            )
```

#### `deals_closing_today` (deterministic, default-on)

Open opportunities whose expected-close date falls within the next N days
(default: today only) — an "act now" nudge so deadlines don't slip unnoticed.

```python
# models/detectors/sale/deals_closing_today.py
from dateutil.relativedelta import relativedelta
from odoo import fields
from odoo.addons.pulse_digest.models.constants import SEVERITY_WARNING
from odoo.addons.pulse_digest.models.detectors.sale._common import (
    open_opportunity_domain,
)
from odoo.addons.pulse_digest.models.detectors.base import (
    PulseDetectorBase, PulseFinding,
)


class DealsClosingTodayDetector(PulseDetectorBase):
    TECHNICAL_NAME = "sale.deals_closing_today"
    DEFAULT_PARAMS = {
        "horizon_days": 0,   # 0 = today only; N = today through today+N
        "min_expected_revenue": 0.0,
    }

    def compute(self, env, scope):
        today = fields.Date.context_today(env.user)
        horizon = today + relativedelta(days=self.params["horizon_days"])

        domain = open_opportunity_domain(scope.company) + [
            ("stage_id.is_won", "=", False),
            ("date_deadline", ">=", today),
            ("date_deadline", "<=", horizon),
            ("expected_revenue", ">", self.params["min_expected_revenue"]),
        ]
        if scope.is_user:
            domain = self.apply_user_scope(env, domain, "crm.lead", scope.user)

        leads = env["crm.lead"].search(domain, order="date_deadline, expected_revenue desc")

        for lead in leads:
            deadline = fields.Date.to_date(lead.date_deadline)
            when = "today" if deadline == today else f"by {deadline}"
            yield PulseFinding(
                res_model="crm.lead",
                res_id=lead.id,
                res_name=lead.name,
                summary=f"{lead.name} closes {when} — "
                        f"{lead.expected_revenue:.0f} "
                        f"{lead.company_currency.symbol}",
                severity=SEVERITY_WARNING,
                metric_value=lead.expected_revenue,
            )
```

#### `deal_velocity_drop` (statistical, default-off)

The CRM analogue of the payment-delay outlier: flag a salesperson whose
deal-progression rate this week is unusually low versus their own rolling
baseline. "Progression" here is counted as stage advances (leads whose
`date_last_stage_update` falls in the period), which is a cheap proxy for
pipeline activity without needing a full stage-history log.

```python
# models/detectors/sale/deal_velocity_drop.py
import statistics
from collections import defaultdict
from dateutil.relativedelta import relativedelta
from odoo import fields
from odoo.addons.pulse_digest.models.constants import (
    SEVERITY_WARNING, SEVERITY_CRITICAL,
)
from odoo.addons.pulse_digest.models.detectors.sale._common import (
    open_opportunity_domain,
)
from odoo.addons.pulse_digest.models.detectors.base import (
    PulseDetectorBase, PulseFinding,
)


class DealVelocityDropDetector(PulseDetectorBase):
    """Flag salespeople whose stage-advance count this week is unusually low
    vs their own rolling weekly baseline.

    NOTE: counts stage *updates* in each week as a proxy for velocity. A more
    precise version would read mail.tracking / a stage-history model; that is a
    v2 refinement. Documented so the simplification is explicit, not hidden.
    """

    TECHNICAL_NAME = "sale.deal_velocity_drop"
    DEFAULT_PARAMS = {
        "lookback_weeks": 8,
        "min_weeks_for_baseline": 4,
        "z_threshold": 1.5,
    }

    def compute(self, env, scope):
        weeks = self.params["lookback_weeks"]
        today = fields.Date.context_today(env.user)
        start = today - relativedelta(weeks=weeks)

        # This detector is inherently per-salesperson, so it only makes sense
        # to evaluate velocity grouped by user. In company scope we evaluate
        # every salesperson; in user scope, just that user.
        domain = open_opportunity_domain(scope.company) + [
            ("date_last_stage_update", ">=", start),
            ("user_id", "!=", False),
        ]
        if scope.is_user:
            domain = self.apply_user_scope(env, domain, "crm.lead", scope.user)

        leads = env["crm.lead"].search(domain)

        # Bucket stage-advances per (user, week-index)
        by_user = defaultdict(lambda: defaultdict(int))
        for lead in leads:
            d = fields.Date.to_date(lead.date_last_stage_update)
            if not d:
                continue
            week_index = (today - d).days // 7   # 0 = current week
            if 0 <= week_index < weeks:
                by_user[lead.user_id][week_index] += 1

        for user, week_counts in by_user.items():
            current = week_counts.get(0, 0)
            historical = [week_counts.get(w, 0) for w in range(1, weeks)]
            if len(historical) < self.params["min_weeks_for_baseline"]:
                continue
            mean = statistics.mean(historical)
            stdev = statistics.stdev(historical) if len(historical) > 1 else 0
            if stdev == 0:
                continue
            # Velocity DROP: current is unusually LOW, so z is negative.
            z = (current - mean) / stdev
            if z <= -self.params["z_threshold"]:
                yield PulseFinding(
                    res_model="res.users",
                    res_id=user.id,
                    res_name=user.name,
                    summary=f"{user.name}: {current} stage advances this week "
                            f"(baseline {mean:.1f}, {z:.1f}σ)",
                    severity=SEVERITY_WARNING if z > -2.5 else SEVERITY_CRITICAL,
                    metric_value=current,
                    baseline_value=mean,
                    deviation=z,
                )
```

A note on the velocity detector's user-scope semantics: unlike the other
detectors, this one is _intrinsically_ per-salesperson — it groups by `user_id`
regardless of scope. In company scope it evaluates every salesperson; in user
scope, `apply_user_scope` narrows the lead set to one user, who is then the only
key in `by_user`. The grouping logic is identical either way, which is why it
reads cleanly without a scope branch in the aggregation.

### 5.5 v1 detector catalog (seeded in XML)

| Technical name                  | Category   | Default | Statistical |
| ------------------------------- | ---------- | ------- | ----------- |
| `account.overdue_invoices`      | Accounting | ✓       | –           |
| `account.payment_delay_outlier` | Accounting | –       | ✓           |
| `account.credit_limit_breach`   | Accounting | ✓       | –           |
| `sale.stale_opportunities`      | Sales      | ✓       | –           |
| `sale.deals_closing_today`      | Sales      | ✓       | –           |
| `sale.deal_velocity_drop`       | Sales      | –       | ✓           |

Six detectors. Four on by default (deterministic, low-noise). Two off by default (statistical, opt-in for engaged users).

---

## 6. The channel dispatcher

**NOT YET BUILT THIS ITERATION — still intended, see §14.** `models/pulse_channel.py` exists with the
registry/base-class/three-channel shape below, but nothing calls it —
`run_digest`/`run_all_audiences` compute and persist findings, then stop.
There is no `_dispatch_run` anywhere. `EmailChannel` is otherwise correct but
depends on `data/mail_template_data.xml`, which isn't in the manifest yet
(§2). `InAppChannel` has a real bug: it calls `run.message_post(...)`, but
`pulse.run` doesn't inherit `mail.thread`, so that method doesn't exist on
it. `WhatsAppChannel` in the built code still uses the *original, uncorrected*
API this section's Nov 2025 pass already flagged as wrong (`whatsapp.template
._send_message(...)`, checking `"whatsapp.template" in env`) — the corrected
version below was never actually applied to `pulse_channel.py`. It also
depends on `res.users.pulse_phone` (§4.5, not built) and `pulse.run.
get_portal_url()` (never defined). None of this is reachable today since
nothing calls `send()`, but all three need fixing when dispatch gets wired.

Same shape as the detector framework: registry pattern, base class, three implementations.

```python
# models/pulse_channel.py

class PulseChannel:
    """Base class for delivery channels."""
    TECHNICAL_NAME = None  # 'email', 'inapp', 'whatsapp'

    def is_available(self, env):
        """Return True if this channel can be used in the current environment."""
        return True

    def send(self, env, recipient, run, body_html, subject):
        raise NotImplementedError


class EmailChannel(PulseChannel):
    TECHNICAL_NAME = "email"
    def send(self, env, recipient, run, body_html, subject):
        template = env.ref("pulse_digest.mail_template_pulse_digest")
        template.with_context(
            body_html=body_html,
            subject=subject,
        ).send_mail(run.id, email_values={"email_to": recipient.email})


class InAppChannel(PulseChannel):
    TECHNICAL_NAME = "inapp"
    def send(self, env, recipient, run, body_html, subject):
        # Post a mail.message to the user's inbox via the run record
        run.message_post(
            partner_ids=[recipient.partner_id.id],
            subject=subject,
            body=body_html,
            message_type="notification",
            subtype_xmlid="mail.mt_comment",
        )


class WhatsAppChannel(PulseChannel):
    """WhatsApp delivery via Odoo's whatsapp.composer.

    API verified against Odoo 19 sources (Nov 2025). The earlier draft used
    `whatsapp.template._send_message(...)`, which does not exist — the
    correct path is to create a `whatsapp.composer` record with context
    pointing at the active model and IDs, then call
    `action_send_whatsapp_template()`. Free-text variables are set via
    typed fields on the composer (`free_text_1`, `free_text_2`, ...), NOT
    a `wa_variable_ids` mapping, per the SaaS 19.1 forum guidance.

    Pre-approved template setup is a deployment concern:
      1. Admin creates a `whatsapp.template` in the WhatsApp app pointing at
         `pulse.run` as the model, with two free-text variables for the
         portal URL and the finding count.
      2. The template's XML id is stored in `ir.config_parameter` as
         `pulse_digest.whatsapp_template_xmlid` so admins can swap templates
         without code changes.
    """
    TECHNICAL_NAME = "whatsapp"

    def is_available(self, env):
        # WhatsApp is Odoo 19+. Check the composer model, not the template
        # model — both exist on 19, but composer is what we actually use.
        return "whatsapp.composer" in env

    def send(self, env, recipient, run, body_html, subject):
        if not recipient.pulse_phone:
            return
        template_xmlid = env["ir.config_parameter"].sudo().get_param(
            "pulse_digest.whatsapp_template_xmlid")
        if not template_xmlid:
            return
        template = env.ref(template_xmlid, raise_if_not_found=False)
        if not template:
            return

        portal_url = run.get_portal_url()
        composer = env["whatsapp.composer"].with_context(
            active_model="pulse.run",
            active_ids=run.ids,
        ).create({
            "res_model": "pulse.run",
            "res_ids": str(run.ids),
            "wa_template_id": template.id,
            # Free-text variables are positional on the composer; the
            # template must declare them as free_text type, mapped 1:1.
            "free_text_1": portal_url,
            "free_text_2": str(len(run.line_ids)),
        })
        composer.action_send_whatsapp_template()


# Registry — populated at module init
CHANNELS = {}

def register_channel(cls):
    CHANNELS[cls.TECHNICAL_NAME] = cls()
    return cls

register_channel(EmailChannel)
register_channel(InAppChannel)
register_channel(WhatsAppChannel)
```

A reviewer adding Slack/Telegram in v1.1 writes one class and one `register_channel` call. No core code changes.

**Note on schema growth (per-channel fields):** each channel currently costs 3
stored Boolean columns — `pulse.config.<channel>_enabled`,
`res.users.pulse_<channel>_enabled`, `pulse.run.<channel>_sent` — read via a
small dict (`_CHANNEL_FIELDS` in `pulse_config.py`) that maps each channel's
`TECHNICAL_NAME` to that pair of field names. A `fields.Json`-dict alternative
(one column per model, keyed by channel technical name, driven by the
`CHANNELS` registry above) was considered to stop this scaling with channel
count, and declined — Odoo's upgrade path (`-u pulse_digest`) adds
nullable/defaulted columns automatically, so this isn't an upgrade-safety
problem, just a field-count one. Plain typed fields are correct for
closed/bounded state like this (channels, severities, statuses); `fields.Json`
stays reserved for genuinely unbounded per-item data — e.g.
`pulse.config.detector.default_params`/`params` already use it since params
vary per detector, and the planned v1.1 `pulse.finding.state` suppression
store should too. Revisit this decision if a 4th+ channel is ever added.

---

## 7. Cron and execution

**BUILT — real method names/structure differ from the original design below.**
An **hourly** cron, gated per-config on `run_time`, so each company fires at
its own configured hour without needing one cron per company. Reads config,
executes detectors, builds the run record. Does **not** dispatch via channels
yet (§6). What's actually in `pulse_config.py`:

```python
# In pulse.config — actual implementation
import logging
import pytz
from odoo import api, fields
from odoo.addons.pulse_digest.models.detectors.base import Scope

_logger = logging.getLogger(__name__)


def _same_local_hour(self, dt_a, dt_b):
    """True if dt_a and dt_b (naive UTC datetimes) fall in the same local
    calendar hour, in this config's own timezone. Shared by the cron gate
    and the per-audience dedup check below so both use one comparison."""
    tz = pytz.timezone(self.timezone or "UTC")
    a = pytz.utc.localize(dt_a).astimezone(tz)
    b = pytz.utc.localize(dt_b).astimezone(tz)
    return (a.date(), a.hour) == (b.date(), b.hour)


def _get_duplicate_runs(self, audience, user=None):
    """Runs already created for this exact (config, audience, user) in the
    current local hour. Not in the original spec — added so run_digest is
    itself idempotent within an hour, regardless of caller (cron, a manual
    'Run Now' click, or a future wizard)."""
    self.ensure_one()
    now_utc = fields.Datetime.now()
    return self.run_ids.filtered(
        lambda r: r.audience == audience
        and r.user_id.id == (user.id if user else False)
        and r.started_at
        and self._same_local_hour(r.started_at, now_utc)
    )


def run_digest(self, audience, user=None, force=False):
    """Execute all active, available detectors for one audience and persist
    the results as a pulse.run + pulse.run.line records. force=True bypasses
    the dedup check — used by manual triggers, where a click should always
    run, not silently no-op if the hour already fired once."""
    self.ensure_one()

    if not force:
        duplicate_runs = self._get_duplicate_runs(audience, user)
        if duplicate_runs:
            return duplicate_runs[0]

    company = user.company_id if user else self.company_id
    scope = Scope.user(user) if user else Scope.company(company)

    run = self.env["pulse.run"].create({
        "config_id": self.id,
        "audience": audience,
        "user_id": user.id if user else False,
    })

    lines = self.detector_line_ids.filtered(
        lambda l: l.active and l.detector_id.is_available)

    for line in lines:
        detector_id = line.detector_id
        detector_cls = detector_id._get_detector_class()  # see §4 note: lives
                                                            # on pulse.detector,
                                                            # not pulse.config
        params = {**detector_id.default_params, **(line.params or {})}
        detector = detector_cls(params=params)
        for finding in detector.compute(self.env, scope):
            if not self._suppression_gate(detector_cls, finding):
                continue
            self.env["pulse.run.line"].create({
                "run_id": run.id,
                "detector_id": detector_id.id,
                "res_model": finding.res_model,
                "res_id": finding.res_id,
                "res_name": finding.res_name,
                "severity": finding.severity,
                "summary": finding.summary,
                "detail": finding.detail,
                "metric_value": finding.metric_value or 0.0,
                "baseline_value": finding.baseline_value or 0.0,
                "deviation": finding.deviation or 0.0,
            })  # one create() per finding — see implementation note below

    run.write({
        "status": "done",
        "finished_at": fields.Datetime.now(),
        "duration_ms": int((fields.Datetime.now() - run.started_at).total_seconds() * 1000),
    })
    return run


def run_all_audiences(self, force=False):
    """Fan out one config into however many runs its digest_mode implies."""
    self.ensure_one()
    if self.digest_mode in ("company", "both"):
        self.run_digest("company", force=force)
    if self.digest_mode in ("per_user", "both"):
        for user in self.user_group_id.all_user_ids:  # includes members via
                                                        # implied_ids, e.g. an
                                                        # Administrator — see
                                                        # §1b
            self.run_digest("user", user=user, force=force)


def _cron_is_due(self, now_utc):
    """True if now_utc falls in this config's scheduled hour, in its own
    timezone, AND no run has already fired during that same local hour.
    Cron runs hourly, so this can only resolve to hour granularity — a
    run_time of 7.5 (7:30) is treated as due during the 7:00-7:59 hour, same
    as 7.0. Documented limitation, not a bug."""
    self.ensure_one()
    tz = pytz.timezone(self.timezone or "UTC")
    local_now = pytz.utc.localize(now_utc).astimezone(tz)
    if local_now.hour != int(self.run_time):
        return False
    if self.last_run_date and self._same_local_hour(self.last_run_date, now_utc):
        return False  # already ran this hour
    return True


def _cron_run_digests(self):
    """Entry point for cron_pulse_run_digests (data/pulse_cron_data.xml).
    One hourly cron serves every company: each active config decides for
    itself whether it's due."""
    now_utc = fields.Datetime.now()
    for config in self.search([("active", "=", True)]):
        if config._cron_is_due(now_utc):
            config.run_all_audiences()


def _suppression_gate(self, detector_cls, finding, today):
    """Decide whether a finding is delivered this run. Returns (bool, reason).

    SHELVED THIS ITERATION (see §14): the capped age-based backoff schedule
    originally specified here (see the commented-out _suppression_phase_shows
    below) is deferred to the next version, alongside per-recipient
    suppression state. For now this gate is intentionally a pass-through —
    every branch delivers, because there is no backoff logic behind it yet.
    SUPPRESSIBLE/AGE_FIELD remain on the contract (§5.1) as forward-compatible
    plumbing; nothing currently reads AGE_FIELD's value.
    """
    if not detector_cls.SUPPRESSIBLE:
        return True, None                # self-limiting -> always deliver
    if detector_cls.AGE_FIELD is None:
        return True, None                # suppressible but no derivable age
                                          # (credit_limit_breach) -> always
                                          # deliver
    return True, None                    # SUPPRESSIBLE + has an AGE_FIELD:
                                          # backoff not implemented this
                                          # iteration -> still always deliver


# DEFERRED TO NEXT VERSION — not implemented this iteration (see §14).
# Kept here, commented out, as the reference design for when it lands.
#
# @staticmethod
# def _suppression_phase_shows(age_days):
#     """Capped backoff schedule. Returns True if a finding of this age should
#     be shown today. The backoff is capped at one week: every unresolved
#     finding is shown at LEAST once per 7-day window, no matter how old. The
#     cap converts the worst case of a suppression bug from 'hidden forever'
#     to 'shown up to a week late' — bounding the only failure mode that would
#     destroy trust.
#
#     Phase 1 (days 1-3):   show every day        (fresh, actionable)
#     Phase 2 (4-6):        show every other day
#     Phase 3 (7+):         show once per 7 days   (the cap — never longer)
#
#     Keyed to the finding's PROBLEM age (read from the record), not a
#     per-recipient alert age — that upgrade ships with the
#     pulse.finding.state table in the same version this schedule lands in.
#     Applies only to overdue_invoices and stale_opportunities (the only two
#     detectors that would declare SUPPRESSIBLE = True with a real AGE_FIELD).
#     """
#     if age_days <= 3:
#         return True
#     if age_days <= 6:
#         return age_days % 2 == 0
#     return age_days % 7 == 0


```

The cron is registered in `data/pulse_cron_data.xml` running **hourly** (no
`numbercall` field — see §1b); `_cron_is_due` checks whether the current hour
(in the config's timezone) equals `run_time`'s hour AND that no run has
already fired this hour, so each config fires once a day at its own
configured time without double-firing. This is the standard Odoo pattern for
"run at a configurable time" without spawning a cron per record.

**Implementation notes — where the built version differs from the design above:**

- **Detector resolution lives on `pulse.detector`**, not as a `_resolve_detector_class` staticmethod on `pulse.config`. `pulse.detector._get_detector_class()` does the same `importlib` resolution, called as `detector_id._get_detector_class()`. Rationale: it's the catalog record's own dotted path being resolved, so the method belongs with the data it acts on.
- **No `with_user(user)` context switch for per-user runs.** The design above ran each per-user computation as that user (`self.with_user(user)._execute_one_run(...)`), which would apply that user's own record-rule restrictions during the detector's `search()` calls. The built version stays in the calling env throughout and relies entirely on each detector's own domain filtering (`apply_user_scope`, or a direct `user_id` domain term) to scope results — simpler, but doesn't get the extra safety net of the user's own access rights being enforced during computation. Worth revisiting if detectors are ever written against a model with meaningful record-rule restrictions beyond ownership.
- **One `create()` per finding, not a single bulk `create(line_vals)`.** The N+1 discipline the original design calls for isn't implemented — `pulse.run.line` rows are created one at a time inside the loop. Correct, just not batched.
- **No exception isolation yet — NEXT TASK, not yet built.** The design called for `run_digest`'s per-audience execution to be wrapped in try/except (mark the run `status="failed"`, re-raise) and for `_cron_run_digests`'s per-config loop to catch and log so one company's failure can't block another's. Neither exists yet: today, one detector raising inside `run_digest` propagates uncaught, leaves that run stuck at `status="running"` forever, and can abort the entire `_cron_run_digests` transaction for every other config being processed in the same cron tick. This is the immediate next piece of work.
- **Manual trigger is a set of `pulse.config` action methods, not a wizard.** The file tree (§3) specifies `wizards/pulse_run_wizard.py` with its own form view. The built version instead adds `action_run_now(audience=None)`, `action_admin_run_now(audience=None, user_id=None)`, and `action_view_runs()` directly on `pulse.config`, all funneling their returned client action through a shared `_runs_action(domain_extra=None)` helper — a "Run Now" / "History" button pair in the config form header instead of a separate wizard screen. `action_run_now` restricts `audience` to `None`/`"company"` only (per-user manual triggers would need a user-picker UI that doesn't exist); `action_admin_run_now` is the fuller variant that does support targeting one specific user via `user_id`. No `wizards/` directory exists.

---

## 8. Security

**SCOPE CHANGE from original plan — a third group was added.** The build
started from the two-tier design below, then added a `group_pulse_viewer`
tier during collaborative UX review, because the original plan left
`pulse.config`/`pulse.detector` fully inaccessible to non-admins (the
Recipient column showed "–" for both below) — meaning a Recipient could
never see *what* they were configured to receive, only their own run
history. What's actually built:

### 8.1 Groups (`security/pulse_security.xml`) — actual: three tiers, each implying the one below

- `group_pulse_viewer` — read-only visibility into `pulse.config` and the
  `pulse.detector` catalog. **Implied by `base.group_user`** (Odoo's
  "Internal User" group), so it's granted automatically to every employee —
  not something an admin assigns individually. Answers "what is Pulse
  configured to do," not "do I receive anything."
- `group_pulse_recipient` — implies `group_pulse_viewer`. Receives per-user
  digests. Sees own run history and findings (`pulse.run`/`pulse.run.line`),
  scoped by record rule.
- `group_pulse_admin` — implies `group_pulse_recipient` (and transitively
  `group_pulse_viewer`). Configures detectors, recipient lists, schedule.
  Sees all runs.

All three share one `res.groups.privilege` (`pulse_privilege`, under a new
`module_category_pulse` category) so they render together as a group under
Settings → Users, rather than as unrelated checkboxes. `res.groups.privilege`
is itself an Odoo 19 addition — `res.groups.category_id` was removed in favor
of `privilege_id` pointing at this new model (§1b).

### 8.2 ACL (`security/ir.model.access.csv`) — actual

| Model                   | Viewer (read) | Recipient (read)       | Admin (read/write/create/delete) |
| ----------------------- | -------------- | ---------------------- | --------------------------------- |
| `pulse.detector`        | ✓ read         | (inherits Viewer)      | ✓ all                              |
| `pulse.config`          | ✓ read         | (inherits Viewer)      | ✓ all                              |
| `pulse.config.detector` | ✓ read         | (inherits Viewer)      | ✓ all                              |
| `pulse.run`             | –              | own only (record rule) | ✓ all                              |
| `pulse.run.line`        | –              | via run                | ✓ all                              |

Actual content-visibility (run results, findings) stays gated at the
Recipient tier, unchanged from the original design — only the
config/catalog visibility moved down to the universal Viewer tier.

### 8.3 Record rules — mostly as designed, one gap still open

**NOT YET BUILT — a real gap, matches this section's own stated risk.** The
mitigation called for below (`env[res_model].browse(res_id).check_access_rule
('read')` re-check on every `pulse.run.line` before display) has never been
implemented, because no digest-rendering code exists yet (§6). Must land
before any rendering does.

**Also still open**: `pulse.run.line` itself has no record rule tying it back
to "only lines belonging to runs I can see" (unlike `pulse.run`, which has
the rule below). Harmless today only because the sole way to reach
`pulse.run.line` is nested inside an already-scoped `pulse.run` form — if it
is ever exposed as a standalone list/report, this needs its own rule
mirroring `pulse_run_user_rule`.

Critical: a `pulse.run.line` references arbitrary `res_model` + `res_id`. If a user can read run lines they shouldn't be able to read, we leak record names via the `res_name` cache. Mitigation: when rendering the digest, _always_ re-check access with `env[res_model].browse(res_id).check_access_rule('read')` and skip lines the user can't access. Cheap belt-and-braces.

Record rule on `pulse.run` (built as designed):

```xml
<record id="pulse_run_user_rule" model="ir.rule">
    <field name="name">Pulse Run: own runs only</field>
    <field name="model_id" ref="model_pulse_run"/>
    <field name="domain_force">
        [('user_id', '=', user.id), ('audience', '=', 'user')]
    </field>
    <field name="groups" eval="[(4, ref('group_pulse_recipient'))]"/>
</record>
```

Two additional record rules were built beyond this section's original scope:
an explicit `pulse_run_admin_rule` (`domain_force = [(1, '=', 1)]` for
`group_pulse_admin`) so the admin-sees-everything behavior is legible in the
rule matrix rather than implicit, and two `global=True` multi-company rules
(`pulse_run_company_rule`, `pulse_config_company_rule`) restricting both
models to companies the current user has `allowed_company_ids` access to —
the standard Odoo multi-company pattern, applied uniformly regardless of
Pulse group.

---

## 9. Test plan

**BUILT.** `tests/` exists with 9 files (plus `common.py` for shared fixtures) and passes against a real Odoo 19 instance (`scripts/run-tests.sh`). Table below reflects the actual files and their real coverage, not the original aspirational split (e.g. detector tests are consolidated per-app, not one file per detector; there is no separate per-user-filtering file — that coverage is inline in `test_run_execution.py` and each detector file's own user-scope tests).

Tests live in `tests/`.

### 9.1 Test files

| File                            | What it proves                                                                                                                                                                                                                                                                                                                                                    |
| -------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `test_detector_framework.py`    | Detector registration/lookup works; missing-dependency detectors are hidden; param overrides apply; `Scope` rejects incoherent construction (user-kind without user, company-kind with user, missing company) and is immutable after construction                                                                                                              |
| `test_detectors_accounting.py`  | The three accounting detectors (`overdue_invoices`, `payment_delay_outlier`, `credit_limit_breach`): severity buckets against `SEVERITY_*` constants, statistical baseline/z-score behavior, `with_company` correctness across companies, the no-salesperson exclusion from per-user runs, user-scope filtering                                                |
| `test_detectors_sales.py`       | The three sales/CRM detectors (`stale_opportunities`, `deals_closing_today`, `deal_velocity_drop`): same shape of coverage as the accounting file, scoped to `crm.lead`                                                                                                                                                                                          |
| `test_run_execution.py`         | `run_digest`/`run_all_audiences`, per-hour dedup (including per-user scoping and the `force` bypass), `_cron_is_due`/`_cron_run_digests` gating, and exception isolation — a failing detector marks its run failed without killing the process, and one config's failure doesn't block another company's cron tick                                             |
| `test_security.py`              | The three-tier group hierarchy (implication chain, every internal user gets Viewer); ACL and the "own per-user runs only" record rule enforced per tier; non-admins (plain internal users and Recipients alike) are blocked from `action_admin_run_now` and from the `pulse.run.wizard`, with admin positive controls for both                                 |
| `test_suppression_gate.py`      | **Scope reduced this iteration** (backoff schedule shelved — see §14): self-limiting detectors (`SUPPRESSIBLE = False`) always deliver; `SUPPRESSIBLE = True` + `AGE_FIELD = None` always delivers (the credit_limit_breach case) — the gate is a pass-through for every v1 combination. Deferred to the version that ships the backoff: phase-schedule correctness, the 7-day cap, missing/null anchor defaulting to deliver, and `suppression_reason` population. |
| `test_channel_dispatch.py`      | `_dispatch_run`'s config-level × user-level channel gate; `email_sent`/`inapp_sent`/`whatsapp_sent` verified against the real `mail.mail` queue and `run.message_ids`, not just the flags; WhatsApp's no-op when the `whatsapp` module isn't installed; per-channel and per-recipient failure isolation via a fake channel patched into the registry            |
| `test_pulse_run_wizard.py`      | `allowed_user_ids` reflects the config's `user_group_id`; `action_run` raises on a missing `user_id` for per-user audience and delegates correctly to `action_admin_run_now` for both audiences; pins the known gap that `user_id` isn't re-validated server-side against the allowed group                                                                    |
| `test_pulse_run_fields.py`      | `pulse.run`'s severity-stat computed fields (`critical_count`/`warning_count`/`info_count`/`worst_severity`) and `pulse.run.line.severity_sequence`, including worst-first ordering via `search(..., order="severity_sequence")`                                                                                                                                |

### 9.2 Tour test

**NOT YET BUILT.** One QUnit/HOOT tour: install module, configure a detector, enable a non-default one, trigger a manual run, see the result in the run list view. This is the smoke test that proves the UI works end-to-end. It's also the kind of test R&D reviewers like — it demonstrates you write the same kind of tests Odoo writes.

---

## 10. Store listing

### 10.1 Hero line

> **Pulse — Daily exception digest for Odoo**
> Find what needs attention across Accounting and Sales every morning. Lists the actual records — not just counts — with built-in anomaly detection.

### 10.2 The comparison table (top of listing)

| Feature                               | Odoo's built-in Digest       | Pulse                      |
| ------------------------------------- | ---------------------------- | -------------------------- |
| Aggregate KPIs (counts, totals)       | ✓                            | ✓                          |
| **Specific records that need action** | –                            | **✓**                      |
| **Statistical anomaly detection**     | –                            | **✓**                      |
| **Per-user filtering by ownership**   | –                            | **✓**                      |
| **In-app notification delivery**      | –                            | **✓**                      |
| **WhatsApp delivery (Odoo 19+)**      | –                            | **✓**                      |
| Custom metrics                        | Requires Studio (Enterprise) | Free, via Python detectors |
| Channel: Email                        | ✓                            | ✓                          |

### 10.3 Description structure

1. The hero line and tagline.
2. The comparison table.
3. "How it works" — three screenshots: the configuration UI, an email digest example, the run history list.
4. "Detectors included in v1" — six bullet points naming each detector and what it flags.
5. "Extending Pulse" — short developer-facing section: how to add your own detector in ~30 lines of Python. This is positioned for partners/integrators _and_ for R&D reviewers.
6. Versions supported, license, support email.

### 10.4 Keywords (for store search)

`digest, daily digest, briefing, anomaly, alert, exception, kpi, dashboard, notification, overdue invoices, payment, sales, crm, automation, cron`

---

## 11. Day-by-day build schedule

| Day | Focus                                                                                                        | Output                                                                                   |
| --- | ------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------- |
| 1   | Module skeleton, manifest, dependency tree, security groups                                                  | Module installs cleanly on Odoo 19 dev instance; menus appear; basic ACL works           |
| 2   | `pulse.detector` + `pulse.config` + `pulse.config.detector` models with views                                | Can create a config, see detector catalog, enable/disable detectors with param overrides |
| 3   | Detector framework: base class, registry, two simplest detectors (`overdue_invoices`, `stale_opportunities`) | Can run these manually from a wizard and see findings stored in `pulse.run.line`         |
| 4   | Remaining deterministic detectors + the two statistical ones                                                 | All six detectors implemented and unit-tested                                            |
| 5   | Run execution + cron + per-user filtering                                                                    | Cron triggers correctly per timezone; per-user runs produce filtered results             |
| 6   | Channel dispatcher: email + in-app                                                                           | Digest arrives by email and in user inbox; mail template renders cleanly                 |
| 7   | Portal controller + WhatsApp channel (19 branch only)                                                        | `/my/pulse/<id>` works; WhatsApp test message delivered                                  |
| 8   | Tests: write all critical tests, fix what they expose                                                        | All tests pass; coverage report >= 70% on `models/`                                      |
| 9   | Port to Odoo 18 branch (drop WhatsApp); polish views; write README; capture screenshots                      | Both 18 and 19 branches install cleanly; README is reviewer-ready                        |
| 10  | Apps store submission (both versions); buffer for review feedback                                            | Listings submitted; you push small fixes if Odoo's automated checks flag anything        |

**Built-in buffer:** the schedule has roughly a day of slack baked into Day 8 and Day 10. Days 1–7 are aggressive; if any slip, Day 8 absorbs it without pushing submission.

**What happens after Day 10:**

- Days 11–14: respond to any Apps store review feedback. Watch for first installs. Read the store comments.
- Week 3: v1.1 — Inventory detectors. Public roadmap commit.
- Week 4: v1.2 — Project/HR detectors. Maybe Slack channel.

---

## 12. Reapplication evidence — what to point to

When reapplying to Odoo R&D in ~6 months, the artifacts you'll cite:

1. **Merged PRs to `odoo/odoo`** (from Week 2 work — separate from this module)
2. **Pulse on apps.odoo.com** — link to the listing, install count, ratings
3. **The Pulse GitHub repo** — point to the detector framework as the "show me how you design" exhibit
4. **Pulse changelog** — v1.0 → v1.1 → v1.2 demonstrates "ships, then iterates"
5. **One or two thoughtful issue threads** on the repo where you triaged and resolved community feedback

The cover letter should mention each by name. The strongest single line you can write is something like: "I shipped Pulse, a daily exception digest module for Odoo, to apps.odoo.com in [month]. It has [N] installs and [N] merged community contributions across versions 18 and 19." Specific numbers beat adjectives every time.

---

## 13. Risks and mitigations

| Risk                                                                      | Mitigation                                                                                                                                                |
| ------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Built-in digest gets a major upgrade in Odoo 20 that closes the gap       | Differentiation on anomaly detection + per-user filtering + multi-channel is unlikely to all be closed at once; keep the roadmap moving                   |
| Statistical detectors produce noise on small datasets and get bad reviews | Conservative defaults (off by default), clear UI labelling "statistical / may be noisy on <4 weeks of data", documentation explains baseline requirements |
| Performance: detectors do N+1 queries on large databases                  | Each detector base class encourages bulk search + single ORM call; tests include a "1000 invoice" benchmark detector test that must finish in <2s         |
| WhatsApp setup is a known pain point on Odoo 19                           | Ship 18 fully working without WhatsApp; treat WhatsApp as a "bonus" for 19 users; clear setup docs in README                                              |
| Apps store review delay pushes submission past reapplication window       | Submit by end of Week 3 (Day 10) so 6-week review buffer exists before reapplying at month 6                                                              |

---

## 14. Out of scope for v1 (explicit roadmap)

These are deliberate non-goals for v1 so they don't creep:

- Inventory detectors (v1.1)
- Project / HR / Calendar detectors (v1.2+)
- **Suppression backoff + per-recipient suppression state (v1.1) — SCOPE CHANGE from original plan.** The original plan shipped v1 with a capped recurrence-backoff schedule (max 7-day, never permanent) keyed to the finding's _problem age_, via `SUPPRESSIBLE = True` + `AGE_FIELD` declared on `overdue_invoices`/`stale_opportunities`. That schedule (`_suppression_phase_shows`) was shelved during this iteration, along with those two detectors' `SUPPRESSIBLE`/`AGE_FIELD` declarations — see §7 for the current pass-through gate and the commented-out reference implementation kept for when this lands. v1 now delivers every finding every run, full stop; `SUPPRESSIBLE`/`AGE_FIELD` exist on the base contract but nothing acts on them yet. v1.1 restores the backoff schedule AND adds the `pulse.finding.state` table keyed `(config, recipient, finding_fingerprint)`, computing age from the recipient's own `first_seen` rather than the source record — closing the original per-recipient residual and the newly-deferred backoff in one pass. Also opens suppression to `credit_limit_breach` and other `SUPPRESSIBLE = True` + `AGE_FIELD = None` detectors that neither v1 nor the original v1.1 plan could suppress.
- Acknowledgement workflow ("I saw this, hide tomorrow") (v1.3)
- Slack / Telegram channels (v1.1)
- Custom detector authoring UI (v2 — Python-only in v1)
- Configurable digest layout (v1 ships one layout, period)
- Mobile push notifications (relies on Odoo's mobile app infra; v2)
- Multi-language digest body (v1.1 — strings translatable but body in user lang only in v1.1)

**Additional items shelved this iteration, not in the original roadmap:**

- **Channel dispatch (email/in-app/WhatsApp delivery) — still intended, not ready yet.** The channel classes exist (§6) but nothing calls them; `run_digest` computes and persists findings, then stops. Also blocked on: `data/mail_template_data.xml` not in the manifest, `pulse.run` not inheriting `mail.thread` (breaks `InAppChannel`), `WhatsAppChannel` still on the pre-correction API, and `res.users` channel-preference fields (§4.5) not built. Immediate next-next task after exception isolation below.
- **Full cron/execution robustness (exception isolation) — still intended, not ready yet, immediate next task.** The cron mechanics themselves are built and working (§7: `_cron_run_digests`/`_cron_is_due`/`run_digest`/`run_all_audiences`), but the per-run and per-config try/except (§7's implementation notes) that make the pipeline production-safe were never added. One bad detector currently aborts its whole run permanently and can take down every other company's run in the same cron tick.
- **Portal page — permanently out of scope, not deferred.** The file tree's `controllers/portal.py` (`/my/pulse/<run_id>`) and `views/pulse_portal_templates.xml` will not be built. Every Pulse recipient is an internal Odoo user with backend access (`group_pulse_recipient`/`group_pulse_admin` are implied by `base.group_user`) — there's no external/customer audience for this module, so the portal infrastructure (built for users *without* backend accounts, and requiring the `portal` module dependency this manifest deliberately doesn't declare) doesn't match the actual need. The polished backend `pulse.run` list/form view (§7) plus `get_run_url()` pointing at it is the intended design, not a stand-in.
- **Manual per-user trigger wizard — built.** `wizards/pulse_run_wizard.py` + `wizards/pulse_run_wizard_views.xml` expose `pulse.config.action_admin_run_now`'s existing per-user targeting (previously only reachable at the model layer) via a "Run For User..." header button on `pulse.config`'s form, admin-only. The wizard restricts `user_id` to the config's own `user_group_id` membership so an admin can't accidentally trigger a run for someone the config never intended to include.
- **`pulse.run.line` access re-check on render, and its own record rule — both still open.** See §8.3.

Pin this list to the GitHub repo as a README section. It signals discipline.
