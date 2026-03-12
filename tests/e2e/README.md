## E2E suite notes

The tests in this directory run against a real Garmin Connect session when `pytest --e2e` is enabled.

Some live checks are intentionally strict:

- `health hrv`
- `performance vo2max`
- `performance thresholds`

Those tests are default-enabled within the E2E suite and assume the Garmin account used for `--e2e` exposes those metrics. A `NOT_FOUND` response for those commands may indicate either missing account/device support or an endpoint regression, so the tests keep asserting success instead of treating `NOT_FOUND` as acceptable.

`activity weather` remains a best-effort live check against a recent activity and is left unchanged.
