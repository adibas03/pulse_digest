# Pulse (`pulse_digest`)

Daily exception digest for Odoo. Cross-app, cron-driven aggregator that surfaces
the specific **records to act on** across Accounting and Sales/CRM — not
aggregate counts — with statistical anomaly detection for outliers a fixed
threshold misses.

| | |
| --- | --- |
| Odoo | 19.0 Community |
| Licence | LGPL-3 |
| Depends | `base`, `mail`, `account`, `sale_management`, `crm` |
| Status | Beta (`19.0.0.0.1`) |

The full build specification, including design rationale and the API-drift
verification log, is in [`pulse_digest_spec.md`](pulse_digest_spec.md). **That
file is the source of truth for the Python** — this README describes the module,
it does not restate it.

---

## Install

```bash
# into your addons path
git clone https://github.com/adibas03/pulse_digest.git
```

Then update the apps list and install **Pulse**. Nothing beyond Odoo's own
dependencies is required: the only third-party import is `pytz`, which ships
with Odoo.

On install the module seeds the detector catalog, creates one hourly scheduled
action, and adds a `Pulse` menu. Create a configuration (Pulse → Configuration),
set the run hour and timezone, pick an audience, and enable the detectors you
want.

## Running the tests

Odoo only runs a module's tests during install or update, so the suite needs
`-i` (or `-u`) — `--test-enable` alone against an installed module silently does
nothing.

```bash
docker exec -it odoo sh /mnt/extra-addons/pulse_digest/scripts/run-tests.sh
```

The script drops `pulse_test`, reinstalls the module into a fresh database, and
runs the suite. Narrow it by passing a tag:

```bash
docker exec -it odoo sh /mnt/extra-addons/pulse_digest/scripts/run-tests.sh \
  /pulse_digest:TestSuppressionGate
```

Two flags in there are load-bearing. `--max-cron-threads=0` matters more for
this module than most: Pulse *is* a cron, and without it a cron thread can fire
`_cron_run_digests` against the test database mid-run and create `pulse.run`
records the assertions did not expect. `-p 8068` keeps the test process off the
port a running instance already holds, since Odoo binds HTTP during startup even
with `--stop-after-init`.

Because the script reinstalls from scratch, a failure before any test output is
usually a data-file load error, not a broken assertion. Read upward.

---

## Architecture

Four seams, each designed so that extending it is additive rather than a change
to existing code.

### Detectors

A detector is a plain Python class — no model, no registry file to edit, no UI
builder. Subclass the base, yield findings:

```python
from odoo.addons.pulse_digest.models.constants import SEVERITY_WARNING
from odoo.addons.pulse_digest.models.detectors.base import (
    PulseDetectorBase, PulseFinding,
)


class LowStockDetector(PulseDetectorBase):
    TECHNICAL_NAME = "stock.low_on_hand"
    DEFAULT_PARAMS = {"min_qty": 5.0}

    def compute(self, env, scope):
        domain = [
            ("qty_available", "<", self.params["min_qty"]),
            ("company_id", "=", scope.company.id),
        ]
        for product in env["product.product"].search(domain):
            yield PulseFinding(
                res_model="product.product",
                res_id=product.id,
                res_name=product.display_name,
                summary=f"{product.display_name}: {product.qty_available} on hand",
                severity=SEVERITY_WARNING,
            )
```

Add one `pulse.detector` record in XML pointing at the dotted class path and it
appears in the configuration UI with the same enable/disable and
parameter-override behaviour as the built-in six. Classes resolve dynamically
via `pulse.detector._get_detector_class()`, so no static import list exists to
keep in sync.

Detectors are **stateless**: `env` is passed to `compute()` rather than stored,
so one instance is safe to reuse across companies and users within a run.
`Scope` is an immutable value object — construct it via `Scope.company(company)`
or `Scope.user(user)`, both of which guarantee a coherent kind/company/user
combination.

`dependency_modules` on the catalog record hides a detector when the modules it
needs are not installed, so a detector written against Inventory causes no
trouble on a database without it.

### Channels

`PulseChannel` subclasses register into a dict at import:

```python
register_channel(SlackChannel)   # one class + one call
```

`_CHANNEL_FIELDS` in `models/pulse_config.py` maps each channel's
`TECHNICAL_NAME` to the `pulse.config` field that gates it company-wide and the
`res.users` field that gates it per recipient. Delivery requires **both**, so
nobody is subscribed to a channel they did not ask for.

Email and in-app ship enabled. WhatsApp is implemented but hard-readonly in the
form pending a tested real-world install — it needs Odoo's WhatsApp app and a
Meta-approved message template, neither of which this module can provision.

### Scheduling

One hourly `ir.cron` serves every company. Each configuration decides for itself
whether it is due (`_cron_is_due`), comparing the current hour in its own
timezone against its own `run_time`, and refusing to fire twice in the same local
hour. This is the standard Odoo pattern for "run at a configurable time" without
one cron record per company.

Resolution is hourly: `run_time` of `7.5` is treated as due during the 7:00–7:59
window, same as `7.0`. Documented limitation, not a bug.

### Security

Three groups, each implying the one below:

- `group_pulse_viewer` — read-only on `pulse.config` and the detector catalog.
  Implied by `base.group_user`, so every employee can see what Pulse is
  configured to do.
- `group_pulse_recipient` — receives per-user digests, sees own runs and findings
  via record rule.
- `group_pulse_admin` — configures everything, sees all runs.

A `pulse.run.line` points at an arbitrary `res_model` + `res_id` and caches
`res_name`, so rendering re-checks read access per line rather than trusting the
cache.

---

## Detectors included

Statistical detectors compare against a rolling per-customer or per-salesperson
baseline, so they find nothing until there is enough history — both ship
disabled.

| Detector | Surfaces |
| --- | --- |
| Overdue Invoices | Posted customer invoices past due with an outstanding balance |
| Credit Limit Breaches | Customers whose outstanding balance exceeds their configured limit |
| Payment Delay Outliers *(statistical)* | Customers whose latest payment delay is unusually high against their own baseline |
| Stale Opportunities | Open opportunities with no stage movement for N days |
| Deals Closing Today | Open opportunities closing inside a configurable horizon |
| Deal Velocity Drop *(statistical)* | Salespeople whose stage-advance count is unusually low against their own baseline |

## Known limits in v1

These are deliberate, not oversights.

**Every finding is delivered on every run.** The suppression contract exists —
`SUPPRESSIBLE` and `AGE_FIELD` on `PulseDetectorBase`, with `_suppression_gate`
in `pulse_config.py` — but the gate is currently a pass-through. The bias is
toward delivering: showing a problem again is loud and recoverable, hiding one is
silent and trust-killing, so the safe behaviour ships first and the back-off
schedule lands with the per-recipient state table that makes it correct.

**Per-user digests follow record ownership.** A record with no assigned user
cannot be routed to anyone and appears in the company-wide digest only. Running
both audiences is the recommended setup.

**Suppression state would be per-finding, not per-recipient.** When the back-off
lands, a recipient added mid-life of a finding could first see it late. The
`pulse.finding.state` table keyed `(config, recipient, fingerprint)` is the fix,
and ships in the same release as the back-off rather than before it.

## Roadmap

- WhatsApp delivery — next up, where Odoo's WhatsApp integration is available
- Suppression back-off + `pulse.finding.state` for per-recipient suppression
- Slack / Telegram channels
- Inventory detectors, then Project / HR / Calendar
- Acknowledgement workflow — mark a finding seen, drop it from tomorrow's digest
- Portal page at `/my/pulse/<run_id>`
- Custom detector authoring UI (Python-only for now)
- Odoo 18.0 branch — untested, deliberately out of scope for the first release

---

## Repo layout

```
pulse_digest/
├── models/
│   ├── constants.py              # shared enums (severity)
│   ├── pulse_detector.py         # catalog + dynamic class resolution
│   ├── pulse_config.py           # schedule, audience, dispatch, cron entry
│   ├── pulse_config_detector.py  # config <-> detector join, param overrides
│   ├── pulse_run.py              # execution record
│   ├── pulse_run_line.py         # individual findings
│   ├── pulse_channel.py          # channel base + registry
│   ├── res_users.py              # per-user channel preferences
│   └── detectors/
│       ├── base.py               # PulseDetectorBase, Scope, PulseFinding
│       ├── account/              # _common.py + three detectors
│       └── sale/                 # _common.py + three detectors
├── wizards/                      # "Run digest now"
├── security/                     # groups, ACL, record rules
├── data/                         # catalog seed, cron, mail template
├── views/
├── tests/                        # 13 test modules
└── scripts/run-tests.sh
```

## Licence

LGPL-3. See [`LICENSE`](LICENSE).
