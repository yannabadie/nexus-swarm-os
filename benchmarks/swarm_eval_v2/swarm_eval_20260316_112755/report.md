# Swarm Evaluation Harness

- Generated: 2026-03-16T11:24:33.318147+00:00
- Tasks: 7

## Strategy Summary

| Strategy | Pass Rate | Avg Score | Avg Latency (s) | Avg Tokens | Recovery Rate | Score Variance |
|----------|-----------|-----------|-----------------|------------|---------------|----------------|
| `single_agent` | 29% | 0.502 | 1.157 | 106.4 | 0% | 0.0223 |
| `deterministic_pipeline` | 71% | 0.703 | 3.543 | 345.0 | 0% | 0.0211 |
| `swarm` | 86% | 0.768 | 24.058 | 306.4 | 43% | 0.0167 |

## Task Runs

| Task | Strategy | Mode | Score | Coverage | Latency (s) | Tokens | Recovered |
|------|----------|------|-------|----------|-------------|--------|-----------|
| `auth_expiry_bug` | `single_agent` | `single_agent` | 0.505 | 50% | 1.400 | 110 | no |
| `auth_expiry_bug` | `deterministic_pipeline` | `deterministic_pipeline` | 0.841 | 100% | 3.600 | 330 | no |
| `auth_expiry_bug` | `swarm` | `lead_support` | 0.841 | 100% | 0.025 | 330 | no |
| `memory_storage_contradiction` | `single_agent` | `single_agent` | 0.498 | 50% | 1.000 | 95 | no |
| `memory_storage_contradiction` | `deterministic_pipeline` | `deterministic_pipeline` | 0.508 | 50% | 3.300 | 300 | no |
| `memory_storage_contradiction` | `swarm` | `red_blue` | 0.508 | 50% | 56.038 | 200 | yes |
| `provider_compatibility_gap` | `single_agent` | `single_agent` | 0.170 | 0% | 1.000 | 100 | no |
| `provider_compatibility_gap` | `deterministic_pipeline` | `deterministic_pipeline` | 0.500 | 50% | 3.600 | 360 | no |
| `provider_compatibility_gap` | `swarm` | `parallel` | 0.836 | 100% | 0.009 | 240 | no |
| `security_recovery` | `single_agent` | `single_agent` | 0.673 | 75% | 1.100 | 110 | no |
| `security_recovery` | `deterministic_pipeline` | `deterministic_pipeline` | 0.836 | 100% | 3.500 | 345 | no |
| `security_recovery` | `swarm` | `red_blue` | 0.836 | 100% | 56.143 | 345 | yes |
| `code_review_adversarial` | `single_agent` | `single_agent` | 0.516 | 50% | 1.300 | 120 | no |
| `code_review_adversarial` | `deterministic_pipeline` | `deterministic_pipeline` | 0.633 | 67% | 3.500 | 350 | no |
| `code_review_adversarial` | `swarm` | `red_blue` | 0.633 | 67% | 51.735 | 350 | yes |
| `architecture_debate` | `single_agent` | `single_agent` | 0.524 | 50% | 1.200 | 110 | no |
| `architecture_debate` | `deterministic_pipeline` | `deterministic_pipeline` | 0.864 | 100% | 4.100 | 410 | no |
| `architecture_debate` | `swarm` | `lead_support` | 0.864 | 100% | 4.439 | 410 | no |
| `multi_step_pipeline` | `single_agent` | `single_agent` | 0.628 | 67% | 1.100 | 100 | no |
| `multi_step_pipeline` | `deterministic_pipeline` | `deterministic_pipeline` | 0.736 | 83% | 3.200 | 320 | no |
| `multi_step_pipeline` | `swarm` | `sequential` | 0.855 | 100% | 0.016 | 270 | no |

## Notes

- This harness is deterministic and local-first. It compares strategies with a simulated dual-agent environment while exercising the real HybridSwarmEngine.
- Best average score in this run: `swarm` (0.768).
- Recovery rate reflects runs where swarm degraded and still returned a usable result.
