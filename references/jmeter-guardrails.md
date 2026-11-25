# Performance & API Load-Testing Guardrails

Generated `.jmx` plans give you a fast, clean baseline—not an automatic sign-off for production traffic. Before running load tests in JMeter, check these four engineering guardrails:

1. **Avoid Single-Account / Static-ID Cache Illusion**:
   - Replaying one recorded ID or one user token repeatedly hits application/Redis caches and produces artificially inflated TPS.
   - Attach a JMeter `CSV Data Set Config` with diverse synthetic test IDs and multi-user tokens before measuring real throughput.
2. **Keep Environment Isolation Strict**:
   - Always pass `-JAUTH_TOKEN=...` and override `BASE_HOST` only to isolated test or staging environments.
   - Never run replay or concurrency ramps against production hosts or shared customer tenants.
3. **Avoid `417 Expectation Failed` Behind Reverse Proxies**:
   - Leaving `HTTPSampler.implementation` unset uses JMeter's standard Java client rather than sending `Expect: 100-continue` headers on POST bodies > 1 KB, preventing spurious `417` errors behind Nginx or enterprise gateways.
4. **Look Beyond Averages When Diagnosing Bottlenecks**:
   - Track P95/P99 latency, error rate, database connection pools, thread pools, and lock contention alongside TPS—especially during stepped concurrency ramps and soak runs.
