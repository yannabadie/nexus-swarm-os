# NEXUS V12.4 Driver Comparison & Routing Guide

Complete guide to LLM drivers available in NEXUS and how to optimize costs with intelligent routing.

## Quick Reference: Driver Capabilities

| Driver | Provider | Pricing (Input/Output per M tokens) | Savings vs Claude | Best For |
|--------|----------|-------------------------------------|-------------------|----------|
| **Claude Opus 4.6** | Anthropic | $15/$75 | - (baseline) | Complex reasoning, critical tasks, architecture |
| **Claude Sonnet 4.5** | Anthropic | $3/$15 | 80% cheaper | General development, coding, security |
| **Gemini 3 Pro** | Google | $2.50/$10 | 83% cheaper | Research, planning, creative tasks |
| **Gemini 2.5 Flash** | Google | $0.30/$2.50 | 98% cheaper | Simple tasks, data analysis |
| **DeepSeek V3** | DeepSeek | $0.14/$0.28 | **98% cheaper** | Coding, reasoning, budget tasks |
| **DeepSeek R1** | DeepSeek | $0.55/$2.19 | 93% cheaper | Complex reasoning with CoT |
| **Kimi K2.5** | Moonshot AI | $0.30/$2.50 (est) | 90% cheaper | Multimodal, vision, agent swarm |

## Detailed Driver Specifications

### 1. Claude Drivers (Anthropic)

#### Claude Opus 4.6
- **Model ID**: `claude-opus-4-6`
- **Context**: 200K tokens
- **Pricing**: $15/$75 per million tokens
- **Strengths**:
  - Highest quality reasoning
  - Best for complex architecture decisions
  - Excellent code review and security analysis
  - Superior creative writing
- **Weaknesses**:
  - Most expensive option
  - Higher latency (3-5s typical)
- **Use Cases**:
  - Critical business logic
  - Security audits
  - Complex refactoring
  - Evolution mutations (spawning new agents)

#### Claude Sonnet 4.5
- **Model ID**: `claude-sonnet-4-5-20250929`
- **Context**: 200K tokens
- **Pricing**: $3/$15 per million tokens
- **Strengths**:
  - Excellent coding ability (near Opus quality)
  - Faster responses (1-2s typical)
  - Great cost/performance balance
  - Prompt caching support (90% cost reduction on cache hits)
- **Weaknesses**:
  - Less creative than Opus
  - Occasional oversimplification
- **Use Cases**:
  - Daily development tasks
  - Code generation
  - Bug fixing
  - Documentation writing

### 2. Gemini Drivers (Google)

#### Gemini 3 Pro
- **Model ID**: `gemini-3-pro-preview`
- **Context**: 2M tokens
- **Pricing**: $2.50/$10 per million tokens
- **Strengths**:
  - Massive context window (2M tokens)
  - Excellent research capabilities
  - Strong multimodal support (future)
  - Good at planning and strategy
- **Weaknesses**:
  - Less precise for code than Claude
  - Occasional verbosity
- **Use Cases**:
  - Large codebase analysis
  - Research and web search
  - Strategic planning
  - Context-heavy tasks

#### Gemini 2.5 Flash
- **Model ID**: `gemini-2-5-flash-thinking`
- **Context**: 1M tokens
- **Pricing**: $0.30/$2.50 per million tokens
- **Strengths**:
  - Very fast (sub-second responses)
  - Excellent cost/performance for simple tasks
  - Good enough for most CRUD code
- **Weaknesses**:
  - Lower quality than Pro/Opus
  - Not suitable for complex reasoning
- **Use Cases**:
  - Simple code generation
  - Data transformation
  - Quick Q&A
  - High-volume tasks

### 3. DeepSeek Drivers (DeepSeek AI)

#### DeepSeek V3 (Chat)
- **Model ID**: `deepseek-chat`
- **Context**: 64K tokens
- **Pricing**: $0.14/$0.28 per million tokens (cache hit: $0.014/$0.28)
- **Strengths**:
  - **98% cheaper than Claude Sonnet**
  - Strong coding capabilities (competitive with GPT-4o)
  - Good reasoning for structured tasks
  - Free tier: 5M tokens for new users
  - Cache hits are 90% cheaper
- **Weaknesses**:
  - Smaller context than Claude/Gemini
  - Less creative than Claude
  - Newer model (less battle-tested)
- **Use Cases**:
  - Budget-constrained development
  - High-volume code generation
  - Automated testing
  - CI/CD integrations

#### DeepSeek R1 (Reasoner)
- **Model ID**: `deepseek-reasoner`
- **Context**: 64K tokens
- **Pricing**: $0.55/$2.19 per million tokens
- **Strengths**:
  - Chain-of-thought reasoning
  - Strong at complex logic problems
  - Still 93% cheaper than Claude
  - Good for math and formal verification
- **Weaknesses**:
  - Slower than V3 (due to CoT)
  - Can be verbose
- **Use Cases**:
  - Algorithm design
  - Complex business logic
  - Verification tasks
  - Multi-step reasoning

### 4. Kimi Driver (Moonshot AI)

#### Kimi K2.5
- **Model ID**: `kimi-k2.5`
- **Context**: 256K tokens
- **Pricing**: $0.30/$2.50 per million tokens (estimated, not officially disclosed)
- **Strengths**:
  - **Multimodal**: Native vision + language
  - **Agent Swarm**: Built-in multi-agent collaboration
  - Competitive with GPT-5 on coding tasks
  - 90% cheaper than Claude (estimated)
  - 1T params MoE (32B activated)
- **Weaknesses**:
  - API constraint: top_p must be 0.95 (not configurable)
  - Pricing not officially disclosed
  - Less documentation than Claude/Gemini
- **Use Cases**:
  - Vision tasks (diagram analysis, UI/UX)
  - Agent swarm experiments
  - Multimodal prototyping
  - Cost-effective creative work

## Routing Policies

NEXUS supports 3 routing policies via `ROUTING_POLICY` env variable:

### 1. `balanced` (Default)
- **Philosophy**: Best quality for the complexity
- **Behavior**:
  - Trivial tasks -> Flash/Haiku
  - Simple tasks -> Sonnet/Flash
  - Moderate tasks -> Sonnet/Pro
  - Complex tasks -> Opus/Pro
  - Expert tasks -> Opus
- **Cost**: Medium (optimized for quality/cost balance)
- **Use When**: General development, mixed workloads

### 2. `cost_optimized` (V12.4 Enhanced)
- **Philosophy**: Minimize costs while maintaining acceptable quality
- **Behavior**:
  - Trivial tasks -> **DeepSeek V3** (98% savings)
  - Simple tasks -> **DeepSeek V3** (98% savings)
  - Moderate tasks -> **Kimi K2.5** (90% savings)
  - Complex tasks -> Sonnet/Pro
  - Expert tasks -> Opus (quality preserved)
- **Cost**: 85-95% cheaper than balanced
- **Use When**:
  - Budget-constrained projects
  - High-volume automated tasks
  - CI/CD pipelines
  - Prototyping/experimentation

### 3. `quality_optimized`
- **Philosophy**: Always use the best model
- **Behavior**:
  - All tasks -> Opus 4.6 / Gemini 3 Pro
  - No downgrading to cheaper models
- **Cost**: Highest (no optimization)
- **Use When**:
  - Critical production code
  - Security-sensitive tasks
  - High-stakes decisions
  - When budget is not a constraint

## Cost Comparison Examples

### Example 1: Simple CRUD API Development (10K input / 50K output tokens)

| Policy | Driver Used | Cost | Savings |
|--------|-------------|------|---------|
| quality_optimized | Claude Opus 4.6 | $3.90 | - |
| balanced | Claude Sonnet 4.5 | $0.78 | 80% |
| cost_optimized | DeepSeek V3 | **$0.015** | **99.6%** |

### Example 2: Complex Architecture Design (50K input / 100K output tokens)

| Policy | Driver Used | Cost | Savings |
|--------|-------------|------|---------|
| quality_optimized | Claude Opus 4.6 | $8.25 | - |
| balanced | Claude Opus 4.6 | $8.25 | 0% |
| cost_optimized | Claude Opus 4.6 | $8.25 | 0% (preserved quality) |

### Example 3: Mixed Workload (100K input / 200K output, 50% simple / 50% complex)

| Policy | Drivers Used | Total Cost | Savings |
|--------|--------------|------------|---------|
| quality_optimized | All Opus | $16.50 | - |
| balanced | Mix Sonnet/Opus | $4.05 | 75% |
| cost_optimized | Mix DeepSeek/Opus | **$0.53** | **96.8%** |

## Configuration Guide

### Step 1: Set Driver Mode

```bash
# .env
NEXUS_DRIVER_MODE=auto  # auto | sdk | cli

# auto: SDK when API key available, else CLI subprocess
# sdk:  Force SDK drivers (requires API keys, recommended)
# cli:  Force CLI subprocess drivers (legacy)
```

### Step 2: Add API Keys

```bash
# Premium drivers (for quality_optimized or balanced)
ANTHROPIC_API_KEY=sk-ant-...
GOOGLE_API_KEY=AIza...

# Low-cost drivers (for cost_optimized)
DEEPSEEK_API_KEY=sk-...      # Get free 5M tokens at platform.deepseek.com
KIMI_API_KEY=sk-...          # Get at platform.moonshot.ai
```

### Step 3: Set Routing Policy

```bash
ROUTING_POLICY=cost_optimized  # balanced | cost_optimized | quality_optimized
```

### Step 4: (Optional) Configure Budget Limits

```bash
# Daily spending cap (USD)
BUDGET_LIMIT_USD=50.0

# Warning thresholds
BUDGET_WARNING_PCT=0.80   # Alert at 80%
BUDGET_CRITICAL_PCT=0.90  # Critical at 90%
```

## Advanced: Custom Model Selection

You can override default models per driver:

```bash
# Claude models
CLAUDE_OPUS_MODEL=claude-opus-4-6
CLAUDE_SONNET_MODEL=claude-sonnet-4-5-20250929

# Gemini models
GEMINI_PRO_MODEL=gemini-3-pro-preview
GEMINI_FLASH_MODEL=gemini-2-5-flash-thinking

# DeepSeek models
DEEPSEEK_MODEL=deepseek-chat  # or deepseek-reasoner

# Kimi models
KIMI_MODEL=kimi-k2.5  # or kimi-k2, kimi-latest
```

## Intelligent Routing: CascadedRouter

The CascadedRouter (based on MasRouter, arXiv:2502.11133) makes 3-stage decisions:

### Stage 1: Collaboration Mode Selection
Based on task complexity (0.0-1.0):
- `< 0.2` -> SPECIALIST (single agent)
- `0.2-0.4` -> SEQUENTIAL (ordered execution)
- `0.4-0.6` -> LEAD_SUPPORT (one leads, one assists)
- `0.6-0.8` -> PARALLEL or PING_PONG
- `> 0.8` -> Full PARALLEL

### Stage 2: Role Assignment
Based on mode + domain affinities:
- Claude: Coding, Security, Architecture
- Gemini: Research, Planning, Creative
- DeepSeek: Coding, Reasoning, Simple tasks
- Kimi: Multimodal, Vision, Swarm

### Stage 3: Model Selection (Policy-Aware)
Based on role tier + routing policy:

**balanced:**
- High tier -> Opus 4.6 / Gemini 3 Pro
- Medium tier -> Sonnet 4.5 / Gemini 3 Pro
- Low tier -> Sonnet 4.5 / Flash

**cost_optimized:**
- High tier -> Sonnet 4.5 / Gemini 3 Pro
- Medium tier -> **DeepSeek V3** / **Kimi K2.5**
- Low tier -> **DeepSeek V3** / **Kimi K2.5**

**quality_optimized:**
- All tiers -> Opus 4.6 / Gemini 3 Pro

## Performance Metrics

### Latency (Typical)

| Driver | Latency (p50) | Latency (p95) |
|--------|---------------|---------------|
| DeepSeek V3 | 800ms | 2s |
| Kimi K2.5 | 1.5s | 3.5s |
| Gemini Flash | 400ms | 1s |
| Gemini Pro | 1.2s | 3s |
| Claude Sonnet | 1.5s | 4s |
| Claude Opus | 3s | 8s |

### Quality (Subjective, for NEXUS tasks)

| Driver | Coding | Reasoning | Creative | Speed | Cost |
|--------|--------|-----------|----------|-------|------|
| Opus 4.6 | 10/10 | 10/10 | 10/10 | 6/10 | 2/10 |
| Sonnet 4.5 | 9/10 | 9/10 | 8/10 | 8/10 | 5/10 |
| Gemini 3 Pro | 8/10 | 8/10 | 9/10 | 7/10 | 6/10 |
| Gemini Flash | 7/10 | 7/10 | 7/10 | 10/10 | 9/10 |
| DeepSeek V3 | 8/10 | 8/10 | 6/10 | 9/10 | 10/10 |
| Kimi K2.5 | 8/10 | 7/10 | 8/10 | 7/10 | 9/10 |

## Recommendations

### For Development
- **Daily coding**: `cost_optimized` with DeepSeek V3 (98% savings)
- **Code review**: `balanced` with Sonnet 4.5
- **Architecture**: `quality_optimized` with Opus 4.6

### For Production
- **CI/CD**: `cost_optimized` with DeepSeek V3 (automated tests, linting)
- **Monitoring**: `balanced` (mixed complexity alerts)
- **Incident response**: `quality_optimized` (critical decisions)

### For Evolution/Swarm
- **Spawning agents**: Opus 4.6 (mutations are critical)
- **Agent collaboration**: `balanced` (SwarmEngine handles routing)
- **Benchmarking**: `cost_optimized` (high volume evaluations)

## Troubleshooting

### "DeepSeek driver not available"
- Add `DEEPSEEK_API_KEY` to `.env`
- Get free 5M tokens at https://platform.deepseek.com/

### "Kimi top_p error"
- Kimi only accepts `top_p=0.95`
- Driver automatically sets this (no action needed)

### "Budget exceeded"
- Check `workspace/logs/budget.log`
- Adjust `BUDGET_LIMIT_USD` or switch to `cost_optimized`

### "Model not found"
- Verify `NEXUS_DRIVER_MODE=sdk` (not cli)
- Check API key is set for requested provider

## Future Roadmap

### Planned Drivers (V12.5+)
- **OpenAI GPT-4o**: Premium quality alternative
- **GLM-4.7** (Zhipu AI): Chinese LLM, cost-effective
- **Qwen 2.5-Max**: Alibaba's flagship, competitive pricing
- **Mistral Large**: European alternative

### Planned Features
- **Auto-failover**: Cascade to backup driver on error
- **A/B testing**: Compare driver quality on same task
- **Cost analytics**: Dashboard for per-driver spending
- **Custom routing rules**: User-defined driver selection logic

---

**Version**: V12.4 COGNITIVE BOOST
**Last Updated**: 2025-02-19
**Author**: Claude (NEXUS Team)
