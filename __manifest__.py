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

    # any module necessary for this one to work correctly
    "depends": [
        "base",
        "mail",
        "account",
        "sale_management",
        "crm",
    ],

    # always loaded
    'data': [
        # 'security/ir.model.access.csv',
        'views/views.xml',
        'views/templates.xml',
    ],
    # only loaded in demonstration mode
    'demo': [
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
