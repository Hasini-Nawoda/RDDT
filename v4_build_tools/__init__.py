"""Build-time workbook and compiled-configuration tooling for V4.

This package is intentionally outside the Snowflake-deployable ``v4`` runtime.
It is used to correct/audit the clinical workbook and regenerate the checked-in
shared-atom and phenotype-rule JSON packages under ``v4/config``.
"""

BUILD_TOOLS_VERSION = "4.0.0-build"
