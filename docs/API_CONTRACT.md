# API contract checked on 2026-11-02

Primary source: [Metaculus forecast serializers](https://github.com/Metaculus/metaculus/blob/main/questions/serializers/common.py), blob `bb24ac1b255220075ca2ac7f4105c3c392ce7803`.

- Multiple-choice current options must each have probability in [0.001, 0.999] and sum to 1.
- Numeric/discrete CDF length is inbound outcome count + 1, normally 201.
- After API rounding, each inbound probability increment is at least 0.01/count and at most 40/count.
- Closed endpoints are exactly 0 and 1; open endpoints retain at least 0.001 tail mass.
- The template's linear/log grid transform is used. Quantiles use nominal units; scaling metadata is included verbatim in the prompt.

[Comment service](https://github.com/Metaculus/metaculus/blob/main/comments/services/common.py) accepts a private comment before a forecast. `included_forecast=true` attaches the latest forecast if one exists, otherwise none. Our comment carries the aggregate and each rationale itself; sending it first avoids publishing without reasoning if the comment call fails.

Live authenticated HTTP behavior remains untested. No open tournament question was retrieved for testing. The fixture wrapper has an extra `fixture_only` flag and negative IDs to identify synthetic data.

The rules snapshot provided by the operator requires one attempt, automated submission and private reasoning. Failures and ambiguous HTTP responses remain recorded without automatic retry. Account creation and the participant form remain human prerequisites.
