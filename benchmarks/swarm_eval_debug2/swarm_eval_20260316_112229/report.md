# Swarm Evaluation Harness

- Generated: 2026-03-16T11:20:14.279042+00:00
- Tasks: 4

## Strategy Summary

| Strategy | Pass Rate | Avg Score | Avg Latency (s) | Avg Tokens | Recovery Rate | Score Variance |
|----------|-----------|-----------|-----------------|------------|---------------|----------------|
| `single_agent` | 25% | 0.462 | 1.125 | 103.8 | 0% | 0.0332 |
| `deterministic_pipeline` | 50% | 0.671 | 3.500 | 333.8 | 0% | 0.0280 |
| `swarm` | 75% | 0.755 | 28.106 | 278.8 | 50% | 0.0204 |

## Task Runs

| Task | Strategy | Mode | Score | Coverage | Latency (s) | Tokens | Recovered |
|------|----------|------|-------|----------|-------------|--------|-----------|
| `auth_expiry_bug` | `single_agent` | `single_agent` | 0.505 | 50% | 1.400 | 110 | no |
| `auth_expiry_bug` | `deterministic_pipeline` | `deterministic_pipeline` | 0.841 | 100% | 3.600 | 330 | no |
| `auth_expiry_bug` | `swarm` | `lead_support` | 0.841 | 100% | 0.025 | 330 | no |
| `memory_storage_contradiction` | `single_agent` | `single_agent` | 0.498 | 50% | 1.000 | 95 | no |
| `memory_storage_contradiction` | `deterministic_pipeline` | `deterministic_pipeline` | 0.508 | 50% | 3.300 | 300 | no |
| `memory_storage_contradiction` | `swarm` | `red_blue` | 0.508 | 50% | 56.255 | 200 | yes |
| `provider_compatibility_gap` | `single_agent` | `single_agent` | 0.170 | 0% | 1.000 | 100 | no |
| `provider_compatibility_gap` | `deterministic_pipeline` | `deterministic_pipeline` | 0.500 | 50% | 3.600 | 360 | no |
| `provider_compatibility_gap` | `swarm` | `parallel` | 0.836 | 100% | 0.008 | 240 | no |
| `security_recovery` | `single_agent` | `single_agent` | 0.673 | 75% | 1.100 | 110 | no |
| `security_recovery` | `deterministic_pipeline` | `deterministic_pipeline` | 0.836 | 100% | 3.500 | 345 | no |
| `security_recovery` | `swarm` | `red_blue` | 0.836 | 100% | 56.135 | 345 | yes |

## Notes

- This harness is deterministic and local-first. It compares strategies with a simulated dual-agent environment while exercising the real HybridSwarmEngine.
- Best average score in this run: `swarm` (0.755).
- Recovery rate reflects runs where swarm degraded and still returned a usable result.
