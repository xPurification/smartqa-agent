# SmartQA Agent — AI-Powered Autonomous Test Automation

An intelligent QA agent that analyzes web applications, generates test cases using Claude AI, executes browser tests with Selenium, self-heals broken selectors, prioritizes high-risk tests, and produces structured QA reports — all with minimal human intervention.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      SmartQA Agent                          │
│                     (Orchestrator)                          │
├─────────┬──────────┬──────────┬───────────┬────────────────┤
│  Web    │  Test    │  Test    │  Test     │   Reporting    │
│Analyzer │ Planner  │Generator │ Executor  │    Engine      │
│(Selenium│ (Claude  │(Enriches │(Selenium  │  (Rich CLI +   │
│  page   │  API)    │ + adds   │ runner +  │   JSON output) │
│ inspect)│          │ navigate │ self-heal)│                │
└────┬────┴────┬─────┴────┬─────┴─────┬────┴───────┬────────┘
     │         │          │           │            │
     ▼         ▼          ▼           ▼            ▼
 PageAnalysis  TestPlan  TestCase[] ExecutionReport QAReport
```

## System Workflow

```
1. INPUT: Target URL
       │
2.     ├──► Web Analyzer ──► Extracts forms, buttons, links, inputs
       │
3.     ├──► Test Planner ──► Claude AI generates structured test scenarios
       │
4.     ├──► Test Generator ──► Enriches with navigation, assertions, durations
       │
5.     ├──► Prioritizer ──► Ranks by risk (element importance, page criticality,
       │                     failure probability, interaction frequency)
       │
6.     ├──► Executor ──► Selenium runs each test case step-by-step
       │        │
       │        └──► Self-Healer ──► Retries with fallback selectors on failure
       │
7.     └──► Reporter ──► Rich terminal output + structured JSON report

8. OUTPUT: QAReport with pass/fail, risk score, issues, screenshots
```

## Project Structure

```
smartqa_agent/
├── smartqa/
│   ├── __init__.py          # Package version
│   ├── agent.py             # Orchestrator tying all components together
│   ├── api.py               # FastAPI service (/analyze, /run-tests, /health)
│   ├── cli.py               # Click CLI with Rich output
│   ├── config.py            # Pydantic Settings + .env support
│   ├── executor.py          # Selenium test runner with screenshot capture
│   ├── logging_config.py    # Structured logging with Rich handler
│   ├── models.py            # Pydantic schemas and enums
│   ├── planner.py           # Claude API integration for test planning
│   ├── prioritizer.py       # Risk-based test scoring engine
│   ├── self_healer.py       # Selector fallback and retry strategies
│   ├── test_generator.py    # Converts plans to executable test cases
│   └── web_analyzer.py      # Selenium page inspection
├── tests/
│   ├── test_agent.py        # Agent orchestration tests
│   └── test_executor.py     # Executor and self-healer tests
├── pyproject.toml           # PEP 621 packaging
├── requirements.txt         # Dependencies
├── .env.example             # Environment variable template
├── README.md
└── main.py                  # Entry point
```

## Installation

```bash
# Clone the repository
git clone <repo-url>
cd smartqa_agent

# Create virtual environment (Python 3.11+ required)
python3.11 -m venv .venv
source .venv/bin/activate

# Install in development mode
pip install -e ".[dev]"

# Configure environment
cp .env.example .env
# Edit .env and set CLAUDE_API_KEY
```

### Prerequisites

- Python 3.11+
- Google Chrome browser installed
- An Anthropic API key (Claude)

## Usage

### CLI Commands

**Analyze a web application:**

```bash
smartqa analyze --url https://example.com
smartqa analyze --url https://example.com --output plan.json
```

**Run the full QA pipeline:**

```bash
smartqa run --url https://example.com
smartqa run --url https://example.com --output report.json
```

**Start the API server:**

```bash
smartqa serve
smartqa serve --host 127.0.0.1 --port 9000
```

### API Examples

**Health check:**

```bash
curl http://localhost:8000/health
```

```json
{"status": "healthy", "version": "0.1.0"}
```

**Analyze a URL:**

```bash
curl -X POST http://localhost:8000/analyze \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com"}'
```

**Run tests:**

```bash
curl -X POST http://localhost:8000/run-tests \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com"}'
```

### Sample QA Report

```json
{
  "application_url": "https://example.com",
  "tests_generated": 12,
  "tests_passed": 9,
  "tests_failed": 2,
  "self_healed_failures": 1,
  "risk_score": 22.0,
  "issues": [
    {
      "severity": "high",
      "description": "Test 'Login with SQL injection' failed: form accepted malicious input",
      "steps_to_reproduce": "1. Navigate to https://example.com\n2. Type ' OR 1=1 -- into #username\n3. Click #submit-btn\n4. Assert error message visible",
      "screenshot_path": "screenshots/Login_with_SQL_injection_a1b2c3d4.png",
      "test_case_name": "Login with SQL injection",
      "error_message": "Element '.error-message' not visible"
    }
  ],
  "generated_at": "2026-02-23T12:00:00Z"
}
```

## Design Decisions

**Claude for test planning.** LLM-generated test plans produce realistic, context-aware scenarios that static analysis cannot match. The agent sends structured page analysis data to Claude and receives typed JSON test plans.

**Self-healing selectors.** Web UIs change frequently. When a selector breaks, the self-healer applies a strategy chain — alternative selector types, text content matching, attribute matching (aria-label, placeholder), and partial class matching — to find the element without human intervention.

**Risk-based prioritization.** Not all tests are equally important. The prioritizer scores each test 0-100 using weighted factors: element interaction importance (30%), page criticality (25%), failure probability (25%), and interaction frequency (20%).

**Pydantic everywhere.** Every data flow uses validated Pydantic models. This ensures type safety, serialization consistency, and self-documenting API contracts.

**Dependency injection.** The `SmartQAAgent` orchestrator accepts all collaborating components via constructor injection, making it trivial to swap or mock any part of the system.

## Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=smartqa --cov-report=term-missing

# Run specific test file
pytest tests/test_agent.py -v
```

## Configuration

| Variable | Default | Description |
|---|---|---|
| `CLAUDE_API_KEY` | (required) | Anthropic API key |
| `CLAUDE_MODEL` | `claude-sonnet-4-20250514` | Claude model to use |
| `BROWSER` | `headless` | `headless` or `headed` |
| `TIMEOUT_SECONDS` | `30` | Browser operation timeout |
| `SCREENSHOT_DIR` | `screenshots` | Screenshot save directory |
| `MAX_RETRIES` | `3` | API call retry limit |
| `HEAL_ATTEMPTS` | `5` | Self-healing attempts per failure |
| `LOG_LEVEL` | `INFO` | Logging verbosity |
| `API_HOST` | `0.0.0.0` | FastAPI bind host |
| `API_PORT` | `8000` | FastAPI bind port |

## Limitations

- Requires Google Chrome to be installed on the host machine.
- Single-page applications with heavy JavaScript rendering may need additional wait strategies.
- Claude API costs apply for test plan generation.
- Self-healing works best when elements have stable attributes (id, aria-label, name); heavily dynamic UIs may require more healing attempts.
- The current executor runs tests sequentially; parallel execution is not yet supported.

## Future Improvements

- Parallel test execution across multiple browser instances.
- Support for Firefox and Safari via configurable WebDriver backends.
- Visual regression testing with screenshot diff comparison.
- Persistent test case storage with a database backend.
- CI/CD integration with GitHub Actions and Jenkins plugins.
- Historical trend analysis and flakiness detection.
- Support for authenticated flows with cookie/token injection.
